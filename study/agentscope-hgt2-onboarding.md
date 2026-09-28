# AgentScope 2.0 上手引导（面向 hgt-2 开发）

repo `/Users/elias/Developer/yuuu14/agentscope` · 分支 `study/arch-and-examples` · 基线 `a388212`

> 目标：为 hgt-2 迭代做开发准备。hgt-2 是数据 Agent 产品（内网 GitLab `ai_bigdata/algorithm/hgt-2`），
> 所以重点不在"跑通一个 demo"，而在**怎么把自有工具/数据接进来、怎么服务化、怎么接钉钉**。

## A. 先建立心智模型：AgentScope 是"四层积木"

```
第4层  应用服务  app/            FastAPI 多租户服务 + Web UI + IM 通道 + 存储 + 调度
第3层  编排      pipeline/ team  GoalPipeline / A2A / agent team
第2层  能力      middleware/ rag/ workspace/ memory/ tts/ realtime/ classifier/
第1层  内核      agent/  model/  tool/  message/  formatter/  event/  state/
```

**一句话**：第 1 层是"一个 Agent 长什么样"，第 2 层是"给它加能力"，第 3 层是"多个 Agent 怎么组队"，
第 4 层是"怎么变成线上服务"。hgt-2 大概率四层都要碰，但**从第 1 层读起，按 1→4 顺序**。

内核只有 6 个概念，记住这张表就够走通全仓：

| 概念 | 一句话 | 文件 |
|---|---|---|
| `Msg` | 唯一的信息载体，内容是 block 列表 | `message/_base.py`、`_block.py` |
| `AgentEvent` | 唯一的对外输出，流式事件 | `event/_event.py` |
| `Agent` | ReAct 循环的执行体 | `agent/_agent.py` |
| `ChatModelBase` | LLM 抽象，一个 provider 一个子类 | `model/_base.py` |
| `Toolkit`/`ToolBase` | 工具注册与执行 | `tool/` |
| `FormatterBase` | `Msg[]` → 各家 API 的 dict | `formatter/` |

## B. 读代码的方法（比读什么更重要）

1. **不读 `_agent.py` 全文**（3919 行）。只读 `_reply_impl` 的 Step 注释，再按需跳方法。详见 `notes/agentscope-reply-impl.md`。
2. **三处 `TODO`/注释是设计意图的金矿**：函数 docstring 常写"为什么这么设计"（例：`_acting_impl` 里 state-injected 工具的并发警告、`_batch_tool_calls` 里"未注册工具当并发"的理由）。
3. **每个子模块先看 `__init__.py`**：它是对外契约，30 秒知道这层能干什么。
4. **对照实验**：`examples/` 里每个例子都只演示一层，读例子比读文档快。
5. **`docs/` 里没有架构文档**，官方文档在 `docs.agentscope.io`；本地只有 NEWS/roadmap。

## C. examples 全景（10 个，各演示一层）

| 例子 | 演示的是 | 对应层 | 对 hgt-2 的相关度 |
|---|---|---|---|
| `console/main.py` | **最小完整 Agent**：model + workspace + toolkit + 记忆，终端交互 | 1+2 | ★★★ 起点，先跑这个 |
| `agent_service/main.py` | FastAPI 多租户服务 + Redis + Web UI | 4 | ★★★ 服务化底座 |
| `rag/`（2 个脚本） | 手搓 parser→chunker→embedding→vector store→KnowledgeBase | 2 | ★★★ 数据 Agent 的检索 |
| `long_term_memory/`（3 个） | Agentic / Mem0 / ReMe 三种长期记忆后端 | 2 | ★★ |
| `pipeline/goal/goal_pipeline.py` | 多 Agent 按固定逻辑跑，共用一条事件流 | 3 | ★★ |
| `a2a/`（server+client） | A2A 协议互通，`A2AAgent` 像本地 Agent 一样用 | 3 | ★ 跨系统集成时才需要 |
| `realtime/local_mic.py` | 语音到语音（DashScope） | 2 | ★ |
| `tui/main.py` | Textual 终端 UI | 2 | ★ |
| `workspace/apple-container-workspace.md` | 沙箱后端（Apple Container） | 2 | ★ |
| `web_ui/`（TS 前端） | 现成前端，直接连 agent_service | 4 | ★★ 可白嫖的前端 |

## D. 给 hgt-2 的定制课程（7 课时，每课一个可验证产出）

### 课 1：一个 Agent 的组成 —— `examples/console/main.py`
读懂 `Agent(name, system_prompt, model, toolkit, middlewares, ...)` 每个参数从哪来。
**产出**：能说清 `LocalWorkspace` 为什么同时提供 `list_tools()` 和 `list_skills()`。
对应代码 `agent/_agent.py:120` 的 `__init__` 签名 + `agent/_config.py` 四类 Config。

### 课 2：数据流 —— 为什么前端只消费事件
`Msg`/block ↔ `AgentEvent` 的映射。重点看 `_reasoning_impl` 里 `block_ids` 如何补齐 `*EndEvent`。
**产出**：能画出"用户发一条 Msg → 前端收到哪些事件"的完整序列。
这直接决定你们 Web 端/钉钉端要渲染什么。

### 课 3：接自有工具（hgt-2 的核心）
`tool/_base.py` 的 `ToolBase`（`check_permissions` / `check_read_only` / `match_rule`）
+ `tool/_adapters.py` 的 `FunctionTool`（普通函数直接变工具）+ `tool/_toolkit.py` 的注册/分组。
工具声明 `is_concurrency_safe` / `is_read_only` 会**直接决定循环里并发还是串行**（`_batch_tool_calls`）。
**产出**：把自己的一个数据查询函数包成工具，跑通 console。

### 课 4：服务化 —— `examples/agent_service/main.py` + `src/agentscope/app/`
`create_app()`（`app/_app.py`）+ `_router/`（15 个路由）+ `storage/`（Redis/SQL）+ 多租户会话。
**产出**：起服务，用 `examples/web_ui` 连上去。

### 课 5：接钉钉（你们的主战场）
`app/channel/` 已经有现成的 `DingTalkChannel`（还有 Feishu/Discord）。
看 `_base.py` 的 `ChannelBase`/`ChannelCapability`、`_gateway.py` 的 `ChannelGateway`、
`_dispatcher.py` 的生命周期对齐、`_credential_binding.py` 的凭据绑定流程。
**产出**：说清新通道接入要实现的接口面（这是你们可能需要新增 IM 通道时的模板）。

### 课 6：RAG + 记忆 —— `examples/rag/` + `examples/long_term_memory/`
手搓一遍 `parser→chunker→embedding→vector store`，再看 `middleware/_rag.py` 怎么把它挂到 Agent 上。
**产出**：理解"知识库"在框架里是中间件 + 独立 RAG 模块，不是 Agent 的内置能力。

### 课 7：编排 —— `examples/pipeline/goal/` + A2A + agent team
`PipelineProtocol` 只有一个方法，`GoalPipeline` 和 `Agent` 同构。
`app/` 里还有 leader-worker 的 team 能力。
**产出**：判断 hgt-2 该用"单 Agent + 多工具"还是"多 Agent 组队"。

## E. 起手式：环境

仓库里没有 `.venv`，系统 python 也没装。uv 缓存里已有 `agentscope-2.0.7.post1` 的 wheel（说明装过一次）。

```bash
cd /Users/elias/Developer/yuuu14/agentscope
uv venv && uv pip install -e ".[full]"      # 或最小装 uv pip install -e .
uv run python examples/console/main.py      # 需要 DASHSCOPE_API_KEY
```

若要跑 agent_service，还需 Redis（`brew install redis && brew services start redis`）+ Node ≥20 跑 web_ui。

## F. 三个高频坑

1. **别按 1.x 教程学**。2.0 没有 `agentscope.init` / `msghub`，API 完全不同。
2. **`model` 参数收的是一个 model 实例**，凭据走 `credential/` 里的对象，不是裸 API key。
3. **`is_concurrency_safe` 声明错会导致工具乱序或不该并发时并发** —— 写自有工具时必须显式想清楚。
