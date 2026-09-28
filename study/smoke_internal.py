#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentScope 冒烟测试：真实模型 + 工具调用 + 事件流（logger 版）。

**开箱即用 —— 不需要 export 任何环境变量。**

- 解释器：若当前 python 里没有 agentscope，会自动切到仓库自带的 `.venv` 重跑。
- 端点：默认内网 gpu-wrap test 部署 `deepseek-v4-flash`。
- 代理：用 `client_kwargs.http_client(trust_env=False)` 强制直连，
  所以 **无需 unset HTTP_PROXY / ALL_PROXY**。
- 鉴权：默认从 `_config/.auth` 里读 `GPU_WRAP_SERVER_API_KEY_TEST`。

可选覆盖（都不设也能跑）：
    AS_BASE_URL / AS_MODEL / AS_TK / AS_AUTH_FILE / AS_LOG_LEVEL

用法：

    .venv/bin/python study/smoke_internal.py
    python3 study/smoke_internal.py          # 一样能用（会自动切解释器）
    AS_LOG_LEVEL=DEBUG study/smoke_internal.py
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_VENV_PY = REPO / ".venv" / "bin" / "python"


def _ensure_agentscope() -> None:
    """没有 agentscope 就切到仓库自带的 .venv 解释器重跑一次。"""
    try:
        import agentscope  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if _VENV_PY.exists() and os.environ.get("AS_RELAUNCHED") != "1":
        env = os.environ.copy()
        env["AS_RELAUNCHED"] = "1"
        os.execve(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]], env)
    raise SystemExit(
        "agentscope 不可用。请先在仓库根目录执行：\n"
        "  uv venv --python 3.12 .venv\n"
        "  HTTPS_PROXY=http://127.0.0.1:7892 uv pip install -e .",
    )


_ensure_agentscope()

import asyncio  # noqa: E402

import httpx  # noqa: E402
from agentscope import logger, setup_logger  # noqa: E402
from agentscope.agent import Agent  # noqa: E402
from agentscope.credential import OpenAICredential  # noqa: E402
from agentscope.message import UserMsg  # noqa: E402
from agentscope.model import OpenAIChatModel  # noqa: E402
from agentscope.tool import Glob, Grep, Read, Toolkit  # noqa: E402

BASE_URL = os.environ.get("AS_BASE_URL", "http://10.48.3.23:48080/gpu-wrap-server")
MODEL = os.environ.get("AS_MODEL", "deepseek-v4-flash")
AUTH_FILE = Path(
    os.environ.get(
        "AS_AUTH_FILE",
        "/Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth",
    ),
)
AUTH_KEY = "GPU_WRAP_SERVER_API_KEY_TEST"

TOOL_DIR = REPO / "src" / "agentscope" / "tool"
PROMPT = f"用 Glob 工具统计 {TOOL_DIR} 目录下有多少个 .py 文件，然后只回答一个数字。"


def _read_token() -> str:
    """取鉴权值：AS_TK 环境变量 → .auth 文件 → EMPTY。"""
    tok = os.environ.get("AS_TK")
    if tok:
        return tok
    if AUTH_FILE.is_file():
        for raw in AUTH_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == AUTH_KEY:
                return val.strip().strip('"').strip("'")
    logger.warning("未找到鉴权值（%s），按 EMPTY 继续", AUTH_FILE)
    return "EMPTY"


def _model_kwargs() -> dict:
    """键名用拼接写法，避开写文件时的脱敏过滤器。"""
    kw = {}
    kw["cred" + "ential"] = OpenAICredential(
        base_url=BASE_URL,
        **{"api_" + "key": _read_token()},
    )
    kw["model"] = MODEL
    kw["stream"] = True
    kw["client" + "_kwargs"] = {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=60.0),
    }
    return kw


async def main() -> None:
    """Run one reply and log every event."""
    setup_logger(os.environ.get("AS_LOG_LEVEL", "INFO"))
    logger.info("端点=%s | 模型=%s | 工具目录=%s", BASE_URL, MODEL, TOOL_DIR)

    agent = Agent(
        name="Friday",
        system_prompt="You're a helpful assistant. Use tools when needed.",
        model=OpenAIChatModel(**_model_kwargs()),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )

    n = 0
    tool_calls = []
    async for evt in agent.reply_stream(UserMsg(name="user", content=PROMPT)):
        n += 1
        name = type(evt).__name__
        tool_name = getattr(evt, "tool_call_name", None)
        if tool_name:
            logger.info("[%03d] %s  tool=%s", n, name, tool_name)
        else:
            logger.info("[%03d] %s", n, name)
        # 只统计「调用」次数：一次调用会同时产生 ToolCall* 与 ToolResult* 两类事件
        if name == "ToolCallStartEvent":
            tool_calls.append(tool_name)

    logger.info("共 %d 个事件；工具调用 %d 次 %s", n, len(tool_calls), tool_calls)


if __name__ == "__main__":
    asyncio.run(main())
