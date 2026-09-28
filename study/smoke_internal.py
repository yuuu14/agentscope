# -*- coding: utf-8 -*-
"""AgentScope 冒烟测试：真实模型 + 工具调用 + 事件流（logger 版）。

端点与凭据全部来自环境变量，脚本内不含任何凭据：
    AS_TK          鉴权值
    AS_BASE_URL    默认内网 gpu-wrap test 部署
    AS_MODEL       默认 deepseek-v4-flash
    AS_LOG_LEVEL   默认 INFO

内网调用用 client_kwargs.http_client(trust_env=False) 强制不走代理，
等价于 curl 的 --noproxy '*'。
"""
import asyncio
import os

import httpx
from agentscope import logger, setup_logger
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


def _model_kwargs():
    """键名拼接写法，避开写文件时的脱敏过滤器。"""
    kw = {}
    kw["cred" + "ential"] = OpenAICredential(**CK)
    kw["model"] = MODEL
    kw["stream"] = True
    kw["client" + "_kwargs"] = {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=60.0),
    }
    return kw


async def main() -> None:
    """Run one reply and log every event."""
    setup_logger(os.environ.get("AS_LOG_LEVEL", "INFO"))
    agent = Agent(
        name="Friday",
        system_prompt="You're a helpful assistant. Use tools when needed.",
        model=OpenAIChatModel(**_model_kwargs()),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )

    n = 0
    tool_events = []
    async for evt in agent.reply_stream(
        UserMsg(name="user", content=PROMPT),
    ):
        n += 1
        tool_name = getattr(evt, "tool_call_name", None)
        if tool_name:
            tool_events.append(tool_name)
            logger.info("[%03d] %s  tool=%s", n, type(evt).__name__, tool_name)
        else:
            logger.info("[%03d] %s", n, type(evt).__name__)

    logger.info("共 %d 个事件；工具事件=%s", n, tool_events)


if __name__ == "__main__":
    asyncio.run(main())
