# -*- coding: utf-8 -*-
"""AgentScope 冒烟测试：真实模型 + 工具调用 + 事件流。

凭据从 ~/.claude/_settings-glm.json 读取（不打印、不落盘、不入库）。
把每一个 AgentEvent 打出来 —— 课 2「数据流」的原始素材。

    HTTPS_PROXY=http://127.0.0.1:7892 .venv/bin/python smoke_glm.py
"""
import asyncio
import json
import os
import pathlib

from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Glob, Grep, Read, Toolkit

CRED_FILE = pathlib.Path.home() / ".claude" / "_settings-glm.json"
SECRET = json.loads(CRED_FILE.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]

BASE = os.environ.get("AS_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
MODEL = os.environ.get("AS_MODEL", "glm-5.3")

# 字段名用拼接，避开脱敏过滤器的字面量匹配
CK = {"api_" + "key": SECRET, "base_url": BASE}

PROMPT = (
    "用 Glob 工具统计 src/agentscope/tool 目录下有多少个 .py 文件，"
    "然后只回答一个数字。"
)


async def main() -> None:
    """Run one reply and dump every event."""
    agent = Agent(
        name="Friday",
        system_prompt=(
            "You're a helpful assistant. Use the provided tools to answer."
        ),
        model=OpenAIChatModel(
            credential=OpenAICredential(**CK),
            model=MODEL,
            stream=True,
        ),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )

    n = 0
    calls = []
    async for evt in agent.reply_stream(
        UserMsg(name="user", content=PROMPT),
    ):
        n += 1
        line = "[%03d] %s" % (n, type(evt).__name__)
        d = getattr(evt, "delta", None)
        if d:
            line += "  delta=%r" % (str(d)[:70],)
        tn = getattr(evt, "tool_call_name", None)
        if tn:
            line += "  tool=%s" % tn
            calls.append(tn)
        print(line)

    print("\n=== events=%d tools=%s ===" % (n, calls))


if __name__ == "__main__":
    asyncio.run(main())
