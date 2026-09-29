# 第 3 章 · 接自有工具

> 目标：把一个**真实业务能力**接进 AgentScope，做到**模型自己决定**何时调用、用哪个参数。
> 案例：hgt-2 的问数能力（`hgt2/service/agent/wenshu_agent.py` 背后的 cbb text-to-metrics）。

本章所有结论都来自实测，行号基于 `v2.0.8-77` 与 hgt-2 `master`。

## 3.1 先做设计选择：包 API，还是包 pipeline？

`wenshu_agent.py` 有 **1132 行**，是个完整的 `BaseAgent`。看起来"直接包它"很省事，但先看它
`run()` 的 docstring：

> 单次调用 cbb `/query`（**cbb 内部完成 split + 并行执行 + 聚合**）

也就是说**重活不在它身上**。hgt-2 侧只剩后处理：解析 results/notices、逐个结果做总结、
口径匹配评估、usage 累加。真正的能力边界是 **cbb 的一个 HTTP 接口**。

两条路对比：

| | **包 API**（本章选择） | 包 pipeline |
|---|---|---|
| 做法 | 工具内直接 `POST /text-to-metrics/query` | 构造 `AgentRequest` 调 `WenshuAgent.run()` |
| 额外依赖 | `httpx` | hgt-2 的 `AgentRequest` / `request.extra` / 事件总线 / `agent_log_context` / `LLMEngine` / `SUMMARIZATION_LLM_CONFIG` |
| 抽象层数 | 1（工具 → cbb） | 3（agentscope → hgt-2 `BaseAgent` → cbb） |
| 「总结成文」 | 交给外层 agent（它本来就有模型） | pipeline 内置，等于**第二个模型配置** |
| 可测试性 | 高：工具是纯函数 | 低：要造出完整 `request.extra` |

**结论：包 API。** 四条理由：

1. **能力边界本来就在 cbb** —— 包 pipeline 只是给它套了一层 hgt-2 的运行时胶水；
2. **避免"框架套框架"** —— 三层抽象叠起来，出问题不知道该看哪层；
3. **总结不该留在工具里** —— 「取数」与「成文」分开，职责干净（且工具返回原始数据比返回
   二手总结更可靠）；
4. **工具要能被 agentscope 直接注册** —— 纯 Python 类 + httpx，没有历史包袱。

> 反过来说：如果某个 pipeline 的价值**恰恰在它的后处理**（例如复杂的口径校验、多源融合），
> 那就该包 pipeline —— 判断标准是"重活在哪一侧"。

## 3.2 完整链路（实测打通）

工具需要 `agent_id` 和 `selected_data_model_ids`。这两个**不该写死** —— 它们由平台配置决定：

```
scope（业务域）
  └─► scene ref（平台场景码）
        └─► POST {backend_env_base_url}/msService/public/hgt-chatadmin/algo/queryAgentConfig
              └─► tool_context.<scene>.wenshu_agent
                    ├── agent_id
                    ├── selected_data_model_ids
                    ├── embed_config
                    └── disassembly_system_prompt / _user_prompt
                        └─► POST {cbb}/text-to-metrics/query  →  真实数据
```

实测的 scope → scene → agent 对应：

| scope（工具入参） | scene ref | agent_id | 数据模型数 |
|---|---|---|---|
| `business_operations` | `Operations` | **9** | 76 |
| `customer` | `Customer_Assistant` | **3** | 5 |

**好处**：平台改了数据模型清单，工具自动跟随，不用改代码。

## 3.3 `ToolBase` 的最小契约

写一个只读工具，只需要这几样（`tool/_base.py:100`）：

```python
class MyTool(ToolBase):
    name: str = "my_tool"                       # 呈给模型的名字
    description: str = "..."                    # 呈给模型的描述（决定它何时调用）
    input_schema: dict[str, Any] = {...}        # JSON Schema

    is_mcp: bool = False
    is_read_only: bool = True                   # 参与权限判定
    is_concurrency_safe: bool = True            # 决定 _batch_tool_calls 分批
    is_external_tool: bool = False              # 外部执行则不用实现 call()
    is_state_injected: bool = False             # True 则注入 _agent_state 参数

    async def check_permissions(self, tool_input, context) -> PermissionDecision:
        return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="...")

    async def call(self, **kwargs) -> ToolChunk:
        return ToolChunk(content=[TextBlock(text="...")])
```

三个要点：

- **重写 `call()` 而不是 `__call__()`** —— `__call__` 是中间件洋葱，`call` 才是你要实现的
  （`tool/_base.py:159` 注释明说 "This is the new override point"）；
- **`check_permissions` 是抽象方法**，必须实现；只读工具直接 `ALLOW` 或 `PASSTHROUGH`；
- **`is_concurrency_safe` / `is_read_only` 是正确性开关**（见第 2 章 §2.6）：只读查询就该
  声明 `True`，模型同时问两个业务域时才会并发而不是串行。

## 3.4 三个坑（都实测踩到了）

### 坑 1：`environment-url` 必须给**裸基址**

hgt-2 里 `WenshuAgent._build_environment_url()` 会把 `backend_env_base_url` **拼上**
`/msService/hgt-data-connector/algorithm/query`。照搬到跨服务调用就会出错 —— cbb 自己还会再拼一段：

```
Data connector error: 401, url='…/algorithm/query/msService/public/hgt-data-connector/algorithm/query'
                            ^^^^^^^^^^^^^^^^^^^^^^ 我拼的    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 它又拼的
```

**正确做法：`environment-url` 只给 `https://ubddev.supcon.com:8080`**，路径由 cbb 负责。

### 坑 2：`llm_config` / `embed_config` 是**选填**（cbb 层面）

hgt-2 的 `_parse_tool_context()` 强制要求 `embed_config`，**比 cbb 本身更严**。cbb 的 422 响应
`detail` 只报了两项：

```
{"loc": ["body", "user_id"],   "msg": "Field required"}
{"loc": ["body", "user_name"], "msg": "Field required"}
```

`llm_config` / `embed_config` 不在其中 —— 不传也能跑通。

### 坑 3：平台配置会**回填** `X-UserId`

配置接口传 `X-UserId: missing` 时，返回的 `wenshu_agent.user_id` 是 `null`；传真实用户 id 就回填。
所以**身份从请求头走**，工具里不需要另设一套用户映射。

## 3.5 实测证据

### 工具直调（不经模型）

```
scope=business_operations  query=2026年每个月的销售收入
  子问题：统计年月_v2为2026-01至2026-09的【中控技术】的销售收入
  数据：9 行 —— 2026-01 327,596,082.53 … 2026-06 1,347,365,731.64 …

scope=customer  query=客户总数是多少
  子问题：统计日期_v2截止2026-09-28的公司简称为【中控技术】的新增客户数量
  数据：{"公司简称_v2": "中控技术", "客户数量_v2": "67998"}
```

### Agent 闭环（86 个事件）

```
[007] >> 调用工具 wenshu_query
[013]    参数 {"query": "2026年每个月的销售收入", "scope": "business_operations"}
[017] << 工具结果 [success] 814 字
[084] 答复文本（markdown 表格 + 业务解读）
[086] == 回复结束 "completed"
```

模型**自己**判断出要调工具、**自己**选中 `business_operations`，并把 9 个月数据整理成表格，
还补了一句「6/3/9 月为年内高峰、2 月受春节影响为低点」。

## 3.6 设计要点回顾

| 决定 | 为什么 |
|---|---|
| 包 cbb API，不包 pipeline | 重活在 cbb；避免三明治抽象；总结留给外层 |
| 上下文运行时解析（scope → 配置 → agent_id） | 平台是唯一真相，改清单不用改代码 |
| 配置结果缓存 | 配置响应 ~256KB，每次查太浪费 |
| `is_read_only=True` / `is_concurrency_safe=True` | 只读查询，可并发 |
| 工具返回原始数据、不做总结 | 职责分离；外层模型更适合写结论 |
| `trust_env=False` | 内网调用不受系统代理影响（第 1 章坑 3） |

## 3.7 代码

| 文件 | 作用 |
|---|---|
| `study/wenshu_tool.py` | `WenshuQueryTool(ToolBase)`：scope → 配置 → cbb，返回可读文本 |
| `study/agent_with_wenshu.py` | 把工具接进 `Agent`（内网模型），跑一次真实问答 |

```bash
python3 study/wenshu_tool.py                       # 直调工具，验证链路
python3 study/agent_with_wenshu.py                 # 让模型自己调
python3 study/agent_with_wenshu.py --question "客户总数是多少"
```

## 3.8 加厚：同一案例做成**技能**（tool vs skill 对照）

§3.1–3.7 把问数做成了**工具**。现在把同一件事的**工艺知识**写成**技能**，
两者对照 —— 这是第 2 章 §2.5「三类内容载体」的实操版。

### 技能里放什么

`study/skills/wenshu-data-query/SKILL.md` —— 它**不取数**，只讲怎么问、怎么用结果：

| 内容 | 例子 |
|---|---|
| 何时用 / 不用 | 需要真实数值才用；概念解释、闲聊不用 |
| scope 怎么选 | 收入/回款/利润 → `business_operations`；客户/商机/丢标 → `customer`；**拿不准就换域重试一次** |
| 问法要求 | 时间**写死成绝对区间**（`2026-01 至 2026-09`，不用"最近"）；一次只问一件事；要分组就明说 |
| 结果处理 | 元 → **亿元**两位小数；**必须写出口径**；`data` 为空 ≠ 0；`error` 非空是取数失败，别当"没数据" |
| 输出规范 | 先结论再口径；不输出原始 JSON |

关键是这些**都是工艺，不是能力** —— 删掉它们，工具照样能取数。

### 挂载方式

```python
Toolkit(
    tools=[WenshuQueryTool()],            # 能力：能调用
    skills_or_loaders=[str(SKILL_DIR)],   # 工艺：不可调用，按需阅读
)
```

技能只有 `name` / `description` / `dir` 摘要进 system prompt（几行），全文由模型调
`Skill` 工具按需读取 —— 这就是第 2 章讲的**渐进式披露**。

### A/B 实测（同一个问题）

问题都是「2026年每个月的销售收入是多少？」：

| 对比项 | 只挂 tool | tool + skill |
|---|---|---|
| 事件数 | 86 | **152** |
| 工具调用 | 1 次 | **2 次**（先 `Skill` 读技能，再 `wenshu_query`） |
| 传给工具的 query | `2026年每个月的销售收入` | **`2026-01 至 2026-12 每个月的销售收入，按月分组`** |
| 回答含「数据口径」段 | ❌ | ✅ 指标 / 维度 / 时间范围 / 单位 |
| 业务解读 | 一句带过 | 分点：峰值月、春节影响、三季度偏弱 |
| 标注 10–12 月无数据 | ✅ | ✅ |

**最关键的是第三行**：模型读完技能后，**主动把自然语言问题改写成符合规范的查询** ——
写死了绝对时间区间、显式要求"按月分组"。全程没有任何代码分支，纯靠"读说明书"。

```text
[016] >> 调用工具 Skill
[021]    参数 {"skill": "wenshu-data-query"}
[042] 答复文本 "根据技能规范，我需要将用户的问题转化为符合规范的查询…"
[043] >> 调用工具 wenshu_query
[052]    参数 {"query": "2026-01 至 2026-12 每个月的销售收入，按月分组", …}
```

### 判断该写工具还是技能

> **把这段内容删掉，工具的"能做什么"会变吗？不会变 → 那是技能。**

| 用**工具** | 用**技能** |
|---|---|
| 一种**能力**（可调用的动作） | 一类**工艺**（怎么用能力、什么口径、什么规范） |
| 有输入输出契约，能执行 | 是知识/规范，**不可调用** |
| 取数、发邮件、查库 | 问数规范、口径说明、排查流程、输出格式约定 |

### 代价（实测，别忽略）

同一次问答：**事件 86 → 152**，墙钟 **18 秒 → 3 分 32 秒**。

> ⚠️ 这不是严格对照（两次相隔半小时，且挂技能那轮的第一次模型调用就占了 3 分钟），
> 但方向明确：**技能会增加一轮模型调用，并让后续输入的 prompt 变长**
> （第二轮 `in` 从 1572 → 2740 tokens）。

所以：**只有"工艺"确实会反复用到时才写成技能**。一次性的提示，直接放 system prompt 更省。

上一章：[第 2 章 · 框架机制](02-framework-mechanisms.md)
