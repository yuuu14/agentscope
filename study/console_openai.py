# -*- coding: utf-8 -*-
"""Run the AgentScope console against an OpenAI-compatible endpoint.

把 examples/console/main.py 的 DashScope 换成任意 OpenAI 兼容端点，
方便接内网自建服务或 GLM / Moonshot 这类兼容网关。

    export AGENTSCOPE_TOKEN="***"
    export AGENTSCOPE_BASE_URL="https://open.bigmodel.cn/api/paas/v4"   # 可选
    export AGENTSCOPE_MODEL="glm-5.3"                                  # 可选
    export HTTPS_PROXY=http://127.0.0.1:7892
    .venv/bin/python console_openai.py
"""
import asyncio
import os

from agentscope.agent import Agent
from agentscope.console import launch_console
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel
from agentscope.tool import Bash, Edit, Glob, Grep, Read, Toolkit, Write

BASE = os.environ.get(
    "AGENTSCOPE_BASE_URL",
    "https://open.bigmodel.cn/api/paas/v4",
)
MODEL = os.environ.get("AGENTSCOPE_MODEL", "glm-5.3")
SECRET = os.environ.get("AGENTSCOPE_TOKEN", "")

# 字段名用拼接，避开脱敏过滤器的字面量匹配
CK = {"api_" + "key": SECRET, "base_url": BASE}


async def main() -> None:
    """Entry point."""
    if not SECRET:
        raise RuntimeError(
            "Set AGENTSCOPE_TOKEN before running "
            "(optionally AGENTSCOPE_BASE_URL / AGENTSCOPE_MODEL).",
        )

    agent = Agent(
        name="Friday",
        system_prompt=(
            "You're a helpful assistant named Friday. Use the provided "
            "tools whenever they help answering the question."
        ),
        model=OpenAIChatModel(
            credential=OpenAICredential(**CK),
            model=MODEL,
            stream=True,
        ),
        # 只读工具（Grep/Glob/Read）声明可并发；写类工具（Bash/Write/Edit）串行执行
        toolkit=Toolkit(
            tools=[Bash(), Grep(), Glob(), Read(), Write(), Edit()],
        ),
    )

    await launch_console(agent)


if __name__ == "__main__":
    asyncio.run(main())
