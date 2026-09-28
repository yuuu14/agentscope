# AgentScope 2.0 源码学习地图

repo: `/Users/elias/Developer/yuuu14/agentscope`
fork: `yuuu14/agentscope` · upstream `agentscope-ai/agentscope`
版本: `v2.0.8-77-ga388212`（2.0 系列，与 1.x 是两套设计）
规模: 719 个 .py / 232,092 行；`src/agentscope` 621 个文件
要求: Python ≥3.11

## 0. 先认清：两个入口层次

| 层 | 位置 | 是什么 |
|---|---|---|
| SDK（Agent） | `src/agentscope/agent` + model/tool/message/formatter | 库：自己组装 Agent，进程内跑 |
| Agent Service | `src/agentscope/app`（197 文件） | FastAPI 多租户服务 + `examples/web_ui` |

学源码先只读 SDK 层，`app/` 是部署层，最后再看。

## 1. 核心抽象（先读这 6 个）

| 抽象 | 文件 | 规模 | 关键点 |
|---|---|---|---|
| `Msg` / blocks | `message/_base.py`、`message/_block.py` | 697 / 235 | 一切输入输出都是 `Msg`；内容是多态 block 列表：Text/Thinking/Hint/ToolCall/ToolResult/Data |
| `Agent` | `agent/_agent.py` | **3919** | ReAct 主循环，全仓最重的文件 |
| `ChatModelBase` | `model/_base.py` | 741 | `__call__` → `_call_api` 抽象；含重试、structured output、count_tokens |
| `ToolBase` / `Toolkit` | `tool/_base.py`、`tool/_toolkit.py` | 491 / 695 | 工具注册 + 权限判定 + MCP/skill 适配 |
| `FormatterBase` | `formatter/_formatter_base.py` | 231 | `Msg[]` → provider 原生 dict；每个模型一个 formatter |
| `PipelineProtocol` | `pipeline/_base.py` | 32 | 只有 `reply_stream` 一个方法，Agent 与 Pipeline 同构 |

`PipelineProtocol`（`pipeline/_base.py:11`）是全仓最小也最重要的接口：
能 `reply_stream(inputs) -> AsyncGenerator[AgentEvent | Msg]` 的东西就能顶替 Agent（`GoalPipeline` 就是这么做的）。

## 2. 主循环数据流（读懂这一条就等于读懂框架）

```
reply()/reply_stream()            agent/_agent.py:288 / :332
  └─ _reply()                     :892   包 middleware、发 ReplyStartEvent
      └─ _reply_impl()            :1027  ← 真正的骨架，分步注释都在这里
          ├─ _handle_incoming_messages()   :2027
          ├─ _reasoning_impl()             :1690  调模型 → 流式吐 block 事件
          │    └─ _call_model()            :3271
          ├─ _next_action()                :3492  决定继续 reasoning / acting / 结束
          └─ _acting_impl()                :2765  执行工具
               ├─ _batch_tool_calls()             :2088
               ├─ _execute_sequential_tool_calls  :2128
               ├─ _execute_concurrent_tool_calls  :2178
               ├─ _check_permission_impl()        :2404
               └─ _execute_tool_call()            :2423
```
读法：从 `_reply_impl` 先看那张"Step 1/2/3…"注释表，再按 step 跳进各方法，不用线性读 3919 行。

配套两条支线：
- 上下文压缩：`_compress_context_impl` `:490`、`_split_context_for_compression` `:2870`
- HITL（人在环）：`_check_incoming_event` `:1835`、`_handle_incoming_event` `:1918`，配 `event/_event.py` 里的 `RequireUserConfirmEvent` / `UserInterruptEvent`

## 3. 事件系统

`event/_event.py`，`AgentEvent` 是可流式输出的最小单元：
块级生命周期事件成对出现（`TextBlockStart/Delta/End`、`ToolCallStart/Delta/End`…），
另有 `ExceedMaxItersEvent`、`RequireUserConfirmEvent`、`RequireExternalExecutionEvent`。
前端只需消费事件流，不必解析 provider 格式 —— 这就是 formatter 存在的意义（对上游统一，对下游统一）。

## 4. 建议阅读顺序（4 遍）

1. **跑起来**：`examples/console/main.py`（最小完整例子，需要 `DASHSCOPE_API_KEY`）；只想读不跑就看 README 的 quickstart 段。
2. **数据模型**：`message/_block.py` → `message/_base.py`（先懂 block 再懂 Msg）→ `event/_event.py`。
3. **主循环**：`agent/_agent.py` 的 `_reply_impl` 单点突破 → 四个 `_xxx_impl` → `_next_action`。
4. **边界扩展**：`model/`（挑一个，如 `_deepseek` + `_openai_chat`）、`formatter/`、`tool/_toolkit.py`、`middleware/_base.py`、`workspace/_base.py`。
   最后看 `app/`（`_app.py` 出厂函数 + `_router/` + `_service/`）。

## 5. 其它模块速查

- `middleware/`：reply / reasoning / acting / model_call / system_prompt / compress_context / permission 七类钩子（`agent/_agent.py:206` 起按 hook 过滤，可直接看它认哪些钩子）
- `workspace/`：工具与代码的执行沙箱，后端可换 local / Docker / Apple Container / Bubblewrap / E2B / OpenSandbox / Daytona / K8s
- `credential/`：凭据与 API key 抽象，模型构造时传 credential 而非裸 key
- `rag/`、`embedding/`、`tts/`、`realtime/`、`classifier/`、`sop/`、`skill/`、`state/`：外围能力
- `docs/` 只有 NEWS/roadmap/changelog，**没有架构文档** → 结论必须从源码反推（或在 `docs.agentscope.io` 看线上文档）

## 6. 已知坑

- 系统 `python3` 里没装 agentscope，仓库里也没有 `.venv` → 要跑例子得先 `uv pip install -e .`（或单独建 venv）。
- `agent/_agent.py` 单文件 3919 行，别从第 1 行顺序读，按上面第 2 节的跳法。
- 2.0 与 1.x API 完全不同（1.x 是 `agentscope.init` + `msghub` 那套），网上旧教程/旧博客会误导。
