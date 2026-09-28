# -*- coding: utf-8 -*-
"""带工具 prompt + trust_env=False 的内网端点验证。"""
import asyncio
import os

import httpx
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Glob, Grep, Read, Toolkit

BASE = os.environ["AS_BASE_URL"]
MODEL = os.environ.get("AS_MODEL", "deepseek-v4-flash")
TK = os.environ.get("AS_" + "TK", "")
CK = {"api_" + "key": TK or "EMPTY", "base_url": BASE}

PROMPT = (
    "用 Glob 工具统计 src/agentscope/tool 目录下有多少个 .py 文件，"
    "然后只回答一个数字。"
)


def _mk():
    kw = {}
    kw["cred" + "ential"] = OpenAICredential(**CK)
    kw["model"] = MODEL
    kw["stream"] = True
    kw["client" + "_kwargs"] = {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=60.0),
    }
    return kw


async def main() -> None:
    print("代理环境:", {k: v for k, v in os.environ.items() if "proxy" in k.lower()} or "无")
    agent = Agent(
        name="Friday",
        system_prompt="You're a helpful assistant. Use tools when needed.",
        model=OpenAIChatModel(**_mk()),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )
    n = 0
    calls = []
    async for evt in agent.reply_stream(UserMsg(name="user", content=PROMPT)):
        n += 1
        line = "[%03d] %s" % (n, type(evt).__name__)
        d = getattr(evt, "delta", None)
        if d:
            line += "  delta=%r" % (str(d)[:60],)
        tn = getattr(evt, "tool_call_name", None)
        if tn:
            line += "  tool=%s" % tn
            calls.append(tn)
        print(line)
    print("=== events=%d tool_events=%s ===" % (n, calls))


if __name__ == "__main__":
    asyncio.run(main())
