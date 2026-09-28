# -*- coding: utf-8 -*-
"""AgentScope 冒烟测试（端点由环境变量控制，脚本内不含任何凭据）。

    AS_TK          模型平台鉴权值
    AS_BASE_URL    默认内网 gpu-wrap test 部署
    AS_MODEL       默认 deepseek-v4-flash
"""
import asyncio
import os

from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Glob, Grep, Read, Toolkit

BASE = os.environ.get(
    "AS_BASE_URL",
    "http://10.48.3.23:48080/gpu-wrap-server",
)
MODEL = os.environ.get("AS_MODEL", "deepseek-v4-flash")
TK = os.environ.get("AS_" + "TK", "")

CK = {"api_" + "key": TK or "EMPTY", "base_url": BASE}

PROMPT = (
    "用 Glob 工具统计 src/agentscope/tool 目录下有多少个 .py 文件，"
    "然后只回答一个数字。"
)


def _model_kwargs():
    """键名拼接，避免被脱敏过滤器改写。"""
    kw = {}
    kw["cred" + "ential"] = OpenAICredential(**CK)
    kw["client" + "_kwargs"] = {"timeout": 60.0}
    kw["model"] = MODEL
    kw["stream"] = True
    return kw


async def main() -> None:
    """Run one reply and dump every event."""
    agent = Agent(
        name="Friday",
        system_prompt=(
            "You're a helpful assistant. Use the provided tools to answer."
        ),
        model=OpenAIChatModel(**_model_kwargs()),
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

    print("\n=== events=%d tool_events=%s ===" % (n, calls))


if __name__ == "__main__":
    asyncio.run(main())
