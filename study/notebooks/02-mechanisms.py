# %% [markdown]
# # 第 2 章 · 框架机制
#
# 目标：用**可观测的现象**验证机制，而不是记结论。
#
# 三个可验证点：三态循环的轮次、事件不变量、工具批处理。

# %%
# notebook 用顶层 await（kernel 已有事件循环）。
import json
import sys
from pathlib import Path

# 复用 study/ 下的脚本（agent_with_wenshu 里有模型构造）
STUDY = Path.cwd().resolve()
if STUDY.name == "notebooks":
    STUDY = STUDY.parent
sys.path.insert(0, str(STUDY))

from agent_with_wenshu import build_agent  # noqa: E402  若导入失败见下一个 cell
print("study dir:", STUDY)

# %% [markdown]
# > 上面的 import 只是为了复用模型构造。若不想依赖脚本，可用第 1 章的 `build_agent` 写法。

# %%
from agentscope.message import UserMsg

# 给模型明确 pattern + 绝对 path（含糊的 prompt 会让它反复试探 —— 第 1 章踩坑）
_REPO = STUDY.parent
_Q = f"用 Glob 工具，pattern='**/*.py'，path='{_REPO}/src/agentscope/tool'，只回答一个数字"


async def count_rounds(question: str) -> dict:
    """数一次回复里经过几轮「推理 → 执行」。"""
    agent = build_agent()
    rounds = 0
    starts = ends = 0
    first = last = None
    pairs: dict[str, int] = {}
    async for evt in agent.reply_stream(UserMsg(name="user", content=question)):
        kind = type(evt).__name__
        first = first or kind
        last = kind
        if kind == "ModelCallStartEvent":
            rounds += 1
        if kind in ("TextBlockStartEvent", "ThinkingBlockStartEvent"):
            pairs[kind.split("Block")[0]] = pairs.get(kind.split("Block")[0], 0) + 1
        if kind == "ReplyStartEvent":
            starts += 1
        if kind == "ReplyEndEvent":
            ends += 1
    return {
        "轮次(ModelCallStart)": rounds,
        "首个事件": first,
        "末个事件": last,
        "ReplyStart": starts,
        "ReplyEnd": ends,
        "块起始": pairs,
    }


_rounds = await count_rounds(_Q)
print(json.dumps(_rounds, ensure_ascii=False, indent=2))

# %% [markdown]
# ## 事件不变量（可断言）
#
# 1. `ReplyStartEvent` 一定第一个，`ReplyEndEvent` 一定最后一个
# 2. 块级事件严格成对：`*Start` → `*Delta*` → `*End`
# 3. 工具调用/结果事件排在所属那轮的 `ModelCallStart…ModelCallEnd` 之内或之后

# %%
async def check_invariants(question: str) -> None:
    agent = build_agent()
    seen: list[str] = []
    open_blocks: set[str] = set()
    violations: list[str] = []

    async for evt in agent.reply_stream(UserMsg(name="user", content=question)):
        kind = type(evt).__name__
        seen.append(kind)

        if kind.endswith("BlockStartEvent"):
            open_blocks.add(getattr(evt, "block_id", kind))
        elif kind.endswith("BlockEndEvent"):
            open_blocks.discard(getattr(evt, "block_id", kind))

    if seen[0] != "ReplyStartEvent":
        violations.append(f"首个不是 ReplyStartEvent 而是 {seen[0]}")
    if seen[-1] != "ReplyEndEvent":
        violations.append(f"末个不是 ReplyEndEvent 而是 {seen[-1]}")
    if open_blocks:
        violations.append(f"未闭合的块: {open_blocks}")

    print("事件总数:", len(seen))
    print("不变量检查:", "✅ 全部满足" if not violations else f"❌ {violations}")


await check_invariants(_Q)

# %% [markdown]
# ## 小结
#
# - 主循环是三态机：`Reasoning` / `Acting` / `Exit`（且 `Exit` 有空事件=停泊 的第二种语义）。
# - **`is_concurrency_safe` 是正确性开关**，不是性能开关：它直接决定 `_batch_tool_calls` 的分批。
# - 事件总数不是常量，结构与成对性才是。
# - 中间件可以"吞掉 `ReplyEndEvent`"来让循环继续跑（第 2 章 §2.7）。
