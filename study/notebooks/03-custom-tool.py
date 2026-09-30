# %% [markdown]
# # 第 3 章 · 接自有工具
#
# 目标：把 hgt-2 的问数能力接进 Agent，并对照 **tool vs skill**。
#
# 设计取舍详见 `chapters/03-custom-tool.md`：**包 cbb API，不包 pipeline**。

# %%
# notebook 用顶层 await（kernel 已有事件循环）。
import sys
from pathlib import Path

STUDY = Path.cwd().resolve()
if STUDY.name == "notebooks":
    STUDY = STUDY.parent
if str(STUDY) not in sys.path:
    sys.path.insert(0, str(STUDY))

from wenshu_tool import SCOPE_TO_SCENE, WenshuQueryTool  # noqa: E402

print("工具名 :", WenshuQueryTool.name)
print("只读   :", WenshuQueryTool.is_read_only, "| 可并发:", WenshuQueryTool.is_concurrency_safe)
print("scope  :", sorted(SCOPE_TO_SCENE))

# %% [markdown]
# ## 1. 直接调工具（不经模型）
#
# 链路：`scope` → scene ref → 平台配置 → `agent_id` + 数据模型 → cbb。

# %%
async def direct(scope: str, question: str) -> None:
    tool = WenshuQueryTool()
    chunk = await tool.call(query=question, scope=scope)
    print("=" * 70)
    print(f"scope={scope}  query={question}")
    for blk in chunk.content:
        print(blk.text[:700])


await direct("business_operations", "2026年每个月的销售收入")

# %%
await direct("customer", "客户总数是多少")

# %% [markdown]
# ## 2. 接进 Agent：让模型自己决定
#
# 观察两件事：**模型自己判断要调工具**、**自己选出 scope**。

# %%
from agent_with_wenshu import _model_kwargs  # noqa: E402  复用内网模型构造
from agentscope.agent import Agent  # noqa: E402
from agentscope.message import UserMsg  # noqa: E402
from agentscope.model import OpenAIChatModel  # noqa: E402
from agentscope.tool import Toolkit  # noqa: E402

SKILL_DIR = STUDY / "skills" / "wenshu-data-query"


async def run_agent(question: str, with_skill: bool = False) -> None:
    agent = Agent(
        name="Friday",
        system_prompt=(
            "你是企业数据助手。涉及具体数值的问题，必须调用 wenshu_query 取数后再回答，"
            "不要凭记忆编造数字。"
        ),
        model=OpenAIChatModel(**_model_kwargs()),
        toolkit=Toolkit(
            tools=[WenshuQueryTool()],
            skills_or_loaders=[str(SKILL_DIR)] if with_skill else None,
        ),
    )
    calls: list[tuple[str, str]] = []
    answer = ""
    async for evt in agent.reply_stream(UserMsg(name="user", content=question)):
        kind = type(evt).__name__
        if kind == "ToolCallStartEvent":
            calls.append((evt.tool_call_name, evt.tool_call_id))
        elif kind == "TextBlockEndEvent" and getattr(evt, "text", None):
            answer = evt.text

    print("技能:", "开" if with_skill else "关")
    print("工具调用序列:", [c[0] for c in calls])
    print("最终答复:", (answer or "")[:600])


await run_agent("2026年每个月的销售收入是多少？")

# %% [markdown]
# ## 3. 同一案例做成技能（对照）
#
# 技能**不可调用**，只讲"怎么问、怎么用结果"。挂上它之后，模型会**先读技能**，
# 再按规范改写查询（写死绝对时间区间、显式要求按月分组）。

# %%
await run_agent("2026年每个月的销售收入是多少？", with_skill=True)

# %% [markdown]
# ## 小结
#
# | | 工具 | 技能 |
# |---|---|---|
# | 本质 | 可调用的能力 | 不可调用的工艺/规范 |
# | 进上下文 | schema 常驻 | name/description/dir 摘要常驻，全文按需读 |
# | 影响 | 能做什么 | **怎么用** |
#
# 判断标准：**删掉这段内容，工具的"能做什么"会变吗？不会变 → 是技能。**
#
# 代价：挂技能会多一轮模型调用（第 3 章实测 86 → 152 事件）。
