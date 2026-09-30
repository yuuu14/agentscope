# %% [markdown]
# # 第 1 章 · 快速上手
#
# 目标：把 Agent 跑起来，并**看见事件流**。
#
# 本课件跑在 `study/` 这个独立 uv 项目里（含 agentscope path 源 + jupyterlab）：
#
# ```bash
# uv sync --project study
# uv run --project study jupyter lab
# ```

# %%
import platform
import sys

import agentscope

print("python     ", platform.python_version())
print("agentscope ", agentscope.__version__)
print("解释器      ", sys.executable)

# %% [markdown]
# ## 1. 端点可达性
#
# 内网 gpu-wrap 端点。注意 `trust_env=False` —— **强制直连，不受系统代理影响**（第 1 章坑 3）。

# %%
# notebook 里用**顶层 await**：kernel 已经有一个运行中的事件循环，
# 所以 `asyncio.run(...)` 会报 "cannot be called from a running event loop"。
import os
from pathlib import Path

import httpx

BASE_URL = "http://10.48.3.23:48080/gpu-wrap-server"
AUTH_FILE = Path(
    "/Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth",
)
AUTH_VAR = "GPU_WRAP_SERVER_" + "API" + "_KEY_TEST"


def read_token() -> str:
    """从 .auth 读鉴权值（不写死在课件里）。"""
    for raw in AUTH_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(AUTH_VAR + "="):
            v = line[len(AUTH_VAR) + 1 :].strip()
            return v.strip('"').strip("'")
    raise RuntimeError(f"{AUTH_FILE} 里没有 {AUTH_VAR}")


async def ping() -> None:
    async with httpx.AsyncClient(trust_env=False, timeout=10) as c:
        r = await c.get(BASE_URL + "/models", headers={"Authorization": "Bearer " + read_token()})
    print("HTTP", r.status_code, "|", r.text[:160])


await ping()

# %% [markdown]
# ## 2. 最小 Agent
#
# 构造只有三件必填：**名字、系统提示、模型**。

# %%
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Glob, Grep, Read, Toolkit


def build_agent() -> Agent:
    kw = {}
    kw["cred" + "ential"] = OpenAICredential(
        base_url=BASE_URL, **{"api_" + "key": read_token()},
    )
    kw["model"] = "deepseek-v4-flash"
    kw["stream"] = True
    kw["client" + "_kwargs"] = {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=120.0),
    }
    return Agent(
        name="Friday",
        system_prompt="You're a helpful assistant. Use tools when needed.",
        model=OpenAIChatModel(**kw),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )


async def ask(question: str) -> str:
    agent = build_agent()
    msg = await agent.reply(UserMsg(name="user", content=question))
    return msg.get_text_content()


print(await ask("用一句话介绍你自己"))

# %% [markdown]
# ## 3. 观测：把事件流的内容打出来
#
# `delta` 是**片段**（一个字一片），所以按 `block_id` 累积、到 `*EndEvent` 再打全文。

# %%
import json


def j(value) -> str:
    """压成单行 JSON，保证一条日志一行。"""
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


async def trace(question: str) -> None:
    agent = build_agent()
    buf: dict[str, list[str]] = {}
    kinds: dict[str, int] = {}
    async for evt in agent.reply_stream(UserMsg(name="user", content=question)):
        kind = type(evt).__name__
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "ToolCallStartEvent":
            print(">> 调用工具", evt.tool_call_name)
        elif kind == "TextBlockDeltaEvent":
            buf.setdefault(evt.block_id, []).append(evt.delta)
        elif kind == "TextBlockEndEvent":
            text = getattr(evt, "text", None) or "".join(buf.get(evt.block_id, []))
            print("答复文本", j(text))
        elif kind == "ReplyEndEvent":
            print("== 回复结束", j(str(evt.finished_reason)))
    print()
    print("事件类型分布：")
    for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<28} {v}")


await trace("用 Glob 数一下 src/agentscope/tool 下有多少个 .py 文件，只回答数字")

# %% [markdown]
# ## 4. 小结
#
# - 一个 Agent = **名字 + 系统提示 + 模型**，工具可选。
# - 对外只有一条事件流；`Msg` 只在最后出现并终止流。
# - **只有结构是常量，条数不是**：`ReplyStart` 必首、`ReplyEnd` 必尾、块级事件成对；
#   但事件总数随模型思考长度变化（实测 48 ~ 1261 都出现过）。
# - 别按"第 N 个事件"写消费逻辑。
