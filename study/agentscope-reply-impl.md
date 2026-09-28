# 精读：`Agent._reply_impl` —— AgentScope 的 ReAct 主循环

文件 `src/agentscope/agent/_agent.py`（全仓 3919 行，循环主体在 1027–1295）

## 0. 三层入口：谁负责什么

| 层 | 位置 | 职责 |
|---|---|---|
| `reply_stream` | `:288` | 对外流式接口。把 `Msg` 过滤掉（除非 `yield_final_msg=True`），只吐事件 |
| `reply` | `:332` | 消费整条流，取最后一个 `Msg` 返回；一个都没拿到就 `RuntimeError` |
| `_reply` | `:892` | **middleware 包装层**（`on_reply` 链）+ `_receive_reply_end` 标志 |
| `_reply_impl` | `:1027` | **真正骨架**，下面逐段拆 |

`_reply` 的 chain 用递归 `execute_chain(index, ...)` 把 N 个 `on_reply` middleware 串成洋葱模型，每个 middleware 拿到 `input_kwargs` 和 `next_handler`，可以改参数、吞事件、或追加事件。

**关键机制 `_receive_reply_end`（`:965`/`:962`）**：`_reply` 在 yield `ReplyEndEvent` 前把标志置 True，被挂起的 `_reply_impl` 恢复后检查它。middleware 只要**收到但不 yield** 这个事件，标志就保持 False → 主循环拒绝退出、强制再来一轮。这是"middleware 可以续命循环"的官方后门。

## 1. Step 1–2：输入分派（`:1053`–`:1125`）

`inputs` 是一个大联合类型，实现上按 `isinstance` 分成互斥两类：

- **HITL 事件**：`UserConfirmResultEvent` / `UserInterruptEvent` / `ExternalExecutionResultEvent` → `event = inputs`
- **新消息**：`Msg | list[Msg] | None` → `msgs = inputs`

两个分支各有入口：

```
_check_incoming_event(event)   :1835
 ├─ True  → _handle_incoming_event(event)   :1918   续传被停泊的回复
 └─ False → _handle_incoming_messages(msgs) :2027   开新回复
            + 重置 state.reply_context = ReplyContext(reply_id=新id, cur_iter=0, ...)
            + yield ReplyStartEvent
```

**`UserInterruptEvent` 短路（`:1079`）**：只有在真有 awaiting tool calls 时才构造 `INTERRUPTED` 的 `ReplyEndEvent`；否则整通调用是无害 no-op（会话闲着，没必要报中断）。两种情况都直接 `return`，不进循环。

**结构输出工具每次重建（`:1115`）**：先 `remove_tool(_GenerateStructuredOutput.name)`，若 `reply_context.structured_schema` 存在再 add 一个带 schema 的新实例。所以结构化输出是**每轮回复动态挂载的工具**，不是常驻工具。

## 2. Step 3：主循环（`:1127`–`:1275`）

```python
made_progress = True
while True:
    next_action = self._next_action(final_msg)     # 只读决策
    match next_action: ...                          # Exit | Reasoning | Acting
    if not self.state.get_unfinished_tool_calls(self.name):
        self.state.cur_iter += 1                    # 一轮结束才计数
```

三个设计点：

1. **决策与副作用分离**。`_next_action` 自己声明是 read-only，所有写状态的动作（append hint、压缩、写 context）都在循环体里做。
2. **`made_progress` 忙循环防护**。middleware 连续两次吞掉 `ReplyEndEvent`、中间又没有任何 reasoning/acting → 直接 `RuntimeError`，提示去调 `cur_iter`/`max_iters`/结构化输出状态。
3. **`cur_iter` 的定义**（`:1272`）：一轮 = 一次推理 + 它产生的**所有**工具调用都拿到结果（`get_unfinished_tool_calls` 为空）。推理刚产出工具调用、或 Acting 停泊在确认上，都还不算一轮。

### case Reason ning(hint, tool_choice)（`:1170`）

顺序很重要：

```
made_progress = True; final_msg = None
if hint: state.append_context(name, [hint])   # 系统提醒以 HintBlock 进上下文
await self.compress_context()                  # ① 压缩在推理之前
async for evt in self._inject_runtime_state(): yield evt   # ② 注入时间/任务/用量
async for evt in self._reasoning(tool_choice): ...
```

`_reasoning` 的返回流里，`Msg` 是**候选最终消息**——存进 `final_msg` 但**不 yield**（`:1191`），要不要结束由 `_next_action` 决定。若收到 `ModelCallEndEvent` 且 `finished_reason == INTERRUPTED`，置 `interrupted`，循环后 `raise asyncio.CancelledError()` 走统一取消清理。

### case Acting(tool_calls)（`:1204`）

```python
for batch in await self._batch_tool_calls(tool_calls):
    evt_generator = _execute_sequential_tool_calls(...) 或 _execute_concurrent_tool_calls(...)
    async for evt in evt_generator:
        yield evt
        # RequireUserConfirmEvent / RequireExternalExecutionEvent → break_execution_for_hitl
        # ToolResultEndEvent 且 INTERRUPTED                    → break_execution_for_interruption
    if break_for_interruption: raise asyncio.CancelledError()
    if break_for_hitl: break      # 跳出 batch 循环 → 回主循环
```

**批处理规则 `_batch_tool_calls`（`:2088`）**：逐个看 `tool.is_concurrency_safe`（未注册/不可用的工具当作并发，因为不会产生副作用）：

- `None` 或 `is_concurrency_safe` → 归入 concurrent 批
- 否则 → 归入 sequential 批
- 同类型**相邻**的合并，类型一变就开新批

效果：`Read/Grep/Glob` 这类只读工具天然合成一批并发跑，`Write/Edit/Bash` 这类排它工具各自成批串行跑，且保持模型给出的相对顺序。批的边界完全由工具声明决定，不靠人工编排。

### 异常与清理（`:1278`–`:1295`）

```python
except asyncio.CancelledError:
    end_event = ReplyEndEvent(finished_reason=INTERRUPTED)
    if self.react_config.interruption_raise_cancelled_error: raise
finally:
    if end_event is not None:
        if interrupted_end:
            async for _ in self._close_unfinished_tool_calls(): yield _   # 补 INTERRUPTED 结果
        yield end_event
        if interrupted_end:
            yield AssistantMsg(... finished_reason=INTERRUPTED)           # Msg 放最后：它终止流
```

`_close_unfinished_tool_calls`（`:962`）给尾部 assistant 消息里没有结果的每个工具调用补一条 `<system-reminder>The tool call has been interrupted by the user.</system-reminder>` + `ToolResultState.INTERRUPTED`。**目的是状态自洽**：上下文里每个 tool_call 都有配对结果，下次输入才能被正常处理。

## 3. `_reasoning_impl`（`:1690`）— 一次模型调用

```
yield ModelCallStartEvent
kwargs = await self._prepare_model_input()      # messages + tools
res = await self._call_model(tool_choice=..., **kwargs)
```

兼容两种返回（`:1737`）：async generator（流式，逐 chunk 转事件，`chunk.is_last` 那个存为 `completed_response`）或裸 `ChatResponse`。

- `block_ids` 字典跟踪活跃块，流末补齐所有 `*EndEvent`（Text / Thinking / ToolCall / Data）——**保证 Start/End 成对**，前端不用自己收尾。
- `completed_response is None` → `RuntimeError`，明确说是流中途断了（网络/超时/model bug）。
- 然后 `ModelCallEndEvent` 带 usage，`_save_to_context()` 把内容写回上下文。
- **thinking-only 响应不算最终答案**（`:1815`）：全是 `ThinkingBlock` 时继续跑循环，让模型下一轮产文本/工具调用。
- 有 tool call 或被打断 → 不 yield Msg；否则 yield `AssistantMsg` 作为**候选**最终消息。

## 4. `_next_action`（`:3492`）— 只读决策器，优先级从高到低

返回三个 dataclass 之一：`Acting(tool_calls)` / `Reasoning(hint, tool_choice)` / `Exit(exit_events, exit_msg)`。

| # | 条件 | 返回 |
|---|---|---|
| 1 | 尾部 assistant 消息里有**可执行**工具调用（state `ALLOWED`，或 `PENDING` 且无 awaiting） | `Acting(executable_tool_calls)` |
| 2 | 有 **awaiting** 工具调用（`ASKING` 确认中 / `SUBMITTED` 外部执行中无结果） | `Exit(exit_events=None, msg="I'm waiting for your permission…")` ← **停泊**，不是结束 |
| 3 | 要求结构化输出且已满足 | `Exit(COMPLETED, 带 structured_output 的 Msg)` |
| 4 | 要求结构化输出但未满足 | `Reasoning(hint=system-reminder 要求调用生成工具, tool_choice=该工具)`；超 `max_iters + structured_output_grace_iters` → `Exit(EXCEED_MAX_ITERS)`；到 `max_iters` 时把 tool_choice 改为强制 |
| 5 | 有文本最终消息 `final_msg` | `Exit(...)`，`cur_iter > max_iters` 记 `EXCEED_MAX_ITERS`，否则 `COMPLETED` |
| 6 | `cur_iter == max_iters`（且还没 final_msg） | `Reasoning(hint="总结并给最终答案，别再调工具", tool_choice=none)` ← **一次强制纯文本收尾** |
| 7 | `cur_iter >= max_iters`（强制收尾也没产出） | `Exit(EXCEED_MAX_ITERS)` |
| 8 | 默认 | `Reasoning()` |

**`max_iters` 的真实语义**：不是"最多跑 N 次推理"，而是"第 N 次进入时强制一次不许调工具的收尾调用"。所以正常流程下 `final_msg` 出现在 `cur_iter == max_iters + 1`，而 `_next_action` 里判断"超限"用的是 `>` 而不是 `>=`。

## 5. 一句话总结

`_reply_impl` = **一个只读决策器 + 一个纯副作用循环 + 一条单一事件流**。
所有状态收敛到 `self.state.context`（同一次回复累积进**一条** assistant 消息，`append_context` `:298` 负责），
所有对外输出收敛成 `AgentEvent | Msg`（`Msg` 只在最后出现，它终止流），
所有可扩展点收敛成 middleware 洋葱链（reply / reasoning / acting / model_call / permission / compress / system_prompt 七类）。

## 6. 建议动手验证

在 `_next_action` 开头 `logger.warning("next_action cur_iter=%d ...", self.state.cur_iter)` 打一行，
跑 `examples/console/main.py` 问一个需要两三次工具调用的任务，就能亲眼看到
`Reasoning → Acting → Reasoning → Acting → … → cur_iter == max_iters 的强制收尾 → Exit` 的完整节奏。
