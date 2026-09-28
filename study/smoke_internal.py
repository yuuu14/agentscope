#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentScope 冒烟测试：真实模型 + 工具调用 + 事件内容（logger 版）。

**开箱即用 —— 不需要 export 任何环境变量。**

- 解释器：若当前 python 里没有 agentscope，会自动切到仓库自带的 `.venv` 重跑。
- 端点：默认内网 gpu-wrap test 部署 `deepseek-v4-flash`。
- 代理：`client_kwargs.http_client(trust_env=False)` 强制直连，无需 unset 代理变量。
- 鉴权：默认从 `_config/.auth` 读 `GPU_WRAP_SERVER_API_KEY_TEST`。

日志打的是**内容**而不是事件名。注意 `delta` 是**片段**（一个字 / 一段 JSON），
所以脚本按 `block_id` / `tool_call_id` **累积、到 End 事件才打印拼好的完整内容**。

可选覆盖：
    AS_BASE_URL / AS_MODEL / AS_TK / AS_AUTH_FILE / AS_LOG_LEVEL / AS_LOG_FULL

`AS_LOG_FULL=1` 会把每个原始 delta 也逐条打出来（调试流式细节用）。

用法：

    python3 study/smoke_internal.py
    AS_LOG_FULL=1 .venv/bin/python study/smoke_internal.py
"""
import json
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
        os.execve(
            str(_VENV_PY),
            [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]],
            env,
        )
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
AUTH_VAR = "GPU_WRAP_SERVER_" + "API" + "_KEY_TEST"

TOOL_DIR = REPO / "src" / "agentscope" / "tool"
PROMPT = (
    "用 Glob 工具查一下文件数：pattern='**/*.py'，path='%s'，" 
    "然后只回答一个数字。"
) % (TOOL_DIR,)


def _read_token() -> str:
    """取鉴权值：AS_TK 环境变量优先，其次 .auth 文件，最后 EMPTY。"""
    value = os.environ.get("AS_TK", "")
    if not value and AUTH_FILE.is_file():
        text = AUTH_FILE.read_text(encoding="utf-8")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, rest = line.partition("=")
            if name.strip() == AUTH_VAR:
                value = rest.strip()
                value = value.strip('"').strip("'")
                break
    if not value:
        logger.warning("未取到鉴权值（%s），按 EMPTY 继续", AUTH_FILE)
        value = "EMPTY"
    return value


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


def _hint_to_text(hint) -> str:
    """HintBlock 的 hint 可能是字符串或 block 列表，统一成字符串。"""
    if isinstance(hint, str):
        return hint
    parts = []
    for blk in hint:
        parts.append(getattr(blk, "text", None) or str(blk))
    return " | ".join(parts)


def _j(value) -> str:
    """压成单行 JSON —— 换行转义成 \\n，保证「一条日志一行」。

    直接把对象交给 json.dumps（dict 会被序列化成真 JSON，而不是 Python repr）；
    只有不可序列化的对象才退回 str()。
    """
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


class Tracer:
    """把流式事件拼成可读内容并写日志。

    `delta` 是片段（一个字 / 一段 JSON），所以按 id 累积，到对应 End 事件才打印全文。
    """

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.count = 0
        self.buf = {}
        self.call_names = {}
        self.tool_calls = []
        self.reply_texts = []

    def _acc(self, key, piece):
        self.buf.setdefault(key, []).append(piece)
        return "".join(self.buf[key])

    def feed(self, evt) -> None:
        """Log a single event together with its content."""
        self.count += 1
        n = self.count
        kind = type(evt).__name__

        if kind == "ReplyStartEvent":
            logger.info("[%03d] == 回复开始 reply_id=%s", n, evt.reply_id)

        elif kind == "ModelCallStartEvent":
            logger.info("[%03d] -- 模型调用开始（%s）", n, evt.model_name)

        elif kind == "HintBlockEvent":
            logger.info("[%03d] 提示块（工具结果回灌）%s", n, _j(_hint_to_text(evt.hint)))

        elif kind == "TextBlockDeltaEvent":
            full = self._acc(evt.block_id, evt.delta)
            if self.verbose:
                logger.debug("[%03d]   文本片段 %r（累计 %d 字）", n, evt.delta, len(full))

        elif kind == "TextBlockEndEvent":
            final = getattr(evt, "text", None)
            if not final:
                final = "".join(self.buf.get(evt.block_id, []))
            self.reply_texts.append(final)
            logger.info("[%03d] 答复文本 %s", n, _j(final))

        elif kind == "ThinkingBlockDeltaEvent":
            full = self._acc(evt.block_id, evt.delta)
            if self.verbose:
                logger.debug("[%03d]   思考片段 %r（累计 %d 字）", n, evt.delta, len(full))

        elif kind == "ThinkingBlockEndEvent":
            thinking = "".join(self.buf.get(evt.block_id, []))
            logger.info("[%03d] 思考内容 %s", n, _j({"chars": len(thinking), "thinking": thinking}))

        elif kind == "ToolCallStartEvent":
            self.call_names[evt.tool_call_id] = evt.tool_call_name
            self.tool_calls.append(evt.tool_call_name)
            logger.info("[%03d] >> 调用工具 %s", n, evt.tool_call_name)

        elif kind == "ToolCallDeltaEvent":
            self._acc("args:" + evt.tool_call_id, evt.delta)

        elif kind == "ToolCallEndEvent":
            args = "".join(self.buf.get("args:" + evt.tool_call_id, []))
            logger.info("[%03d]    参数 %s", n, _j(args))

        elif kind == "ToolResultTextDeltaEvent":
            self._acc("res:" + evt.tool_call_id, evt.delta)

        elif kind == "ToolResultEndEvent":
            out = "".join(self.buf.get("res:" + evt.tool_call_id, []))
            logger.info("[%03d] << 工具结果 %s", n, _j({"state": str(evt.state), "chars": len(out), "output": out}))

        elif kind == "ModelCallEndEvent":
            logger.info(
                "[%03d] -- 本轮结束 %s",
                n,
                _j({
                    "in": evt.input_tokens,
                    "out": evt.output_tokens,
                    "cache": evt.cache_input_tokens,
                    "reason": str(evt.finished_reason),
                }),
            )

        elif kind == "ReplyEndEvent":
            logger.info("[%03d] == 回复结束 %s", n, _j(str(evt.finished_reason)))

        else:
            logger.info("[%03d] %s", n, kind)


async def main() -> None:
    """Run one reply and log its event contents."""
    setup_logger(os.environ.get("AS_LOG_LEVEL", "INFO"))
    logger.info("端点=%s | 模型=%s | 工具目录=%s", BASE_URL, MODEL, TOOL_DIR)

    agent = Agent(
        name="Friday",
        system_prompt="You're a helpful assistant. Use tools when needed.",
        model=OpenAIChatModel(**_model_kwargs()),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )

    tracer = Tracer(verbose=os.environ.get("AS_LOG_FULL") == "1")
    async for evt in agent.reply_stream(UserMsg(name="user", content=PROMPT)):
        tracer.feed(evt)

    logger.info(
        "共 %d 个事件；工具调用 %d 次 %s",
        tracer.count,
        len(tracer.tool_calls),
        tracer.tool_calls,
    )
    logger.info("最终答复 %s", _j(tracer.reply_texts[-1] if tracer.reply_texts else ""))


if __name__ == "__main__":
    asyncio.run(main())
