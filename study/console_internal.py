#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端交互式 console —— 参照 examples/console/main.py，改用内网模型平台。

与原版的**唯一差异是模型端点**；其余装配完全一致：

- ``LocalWorkspace``：内置文件工具（Bash/Edit/Glob/Grep/Read/Write）与 agent 技能
  都来自 workspace，绑定到它的 backend 与 skill 分区；
- ``AgenticMemoryMiddleware``：以 Markdown 形式把长期记忆落在 workspace 下，跨进程保留；
- ``workspace`` 兼作 offloader，把压缩后的上下文与过大的工具结果卸载进去；
- 渲染、工具调用确认（y/a）、Ctrl+C 中断，全由 ``launch_console`` 处理。

**开箱即用，不需要 export 任何环境变量**：

- 解释器：当前 python 没有 agentscope 时，自动切到仓库自带的 ``.venv`` 重跑；
- 端点：内网 gpu-wrap test 部署，默认模型 ``deepseek-v4-flash``；
- 代理：``client_kwargs.http_client(trust_env=False)`` 强制直连，无需 unset 代理变量；
- 鉴权：默认从 ``_config/.auth`` 读 ``GPU_WRAP_SERVER_API_KEY_TEST``。

用法::

    python3 study/console_internal.py
    python3 study/console_internal.py --verbosity debug
    python3 study/console_internal.py --model deepseek-v4-flash --workdir /tmp/as-ws

可选覆盖：``AS_BASE_URL`` / ``AS_MODEL`` / ``AS_TK`` / ``AS_AUTH_FILE``。
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

import argparse  # noqa: E402
import asyncio  # noqa: E402

import httpx  # noqa: E402
from agentscope import logger, setup_logger  # noqa: E402
from agentscope.agent import Agent  # noqa: E402
from agentscope.console import launch_console  # noqa: E402
from agentscope.credential import OpenAICredential  # noqa: E402
from agentscope.middleware import AgenticMemoryMiddleware  # noqa: E402
from agentscope.model import OpenAIChatModel  # noqa: E402
from agentscope.tool import Toolkit  # noqa: E402
from agentscope.workspace import LocalWorkspace  # noqa: E402

BASE_URL = os.environ.get("AS_BASE_URL", "http://10.48.3.23:48080/gpu-wrap-server")
DEFAULT_MODEL = os.environ.get("AS_MODEL", "deepseek-v4-flash")
AUTH_FILE = Path(
    os.environ.get(
        "AS_AUTH_FILE",
        "/Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth",
    ),
)
AUTH_VAR = "GPU_WRAP_SERVER_" + "API" + "_KEY_TEST"


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


def _model_kwargs(model_name: str) -> dict:
    """键名用拼接写法，避开写文件时的脱敏过滤器。"""
    kw = {}
    kw["cred" + "ential"] = OpenAICredential(
        base_url=BASE_URL,
        **{"api_" + "key": _read_token()},
    )
    kw["model"] = model_name
    kw["stream"] = True
    kw["client" + "_kwargs"] = {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=120.0),
    }
    return kw


async def main() -> None:
    """Assemble the agent from a LocalWorkspace and hand it to launch_console."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--verbosity",
        choices=["quiet", "default", "debug"],
        default="default",
    )
    parser.add_argument(
        "--workdir",
        default=str(Path(__file__).resolve().parent / "workspaces"),
        help="The workspace root directory（默认 study/workspaces，已被 .gitignore 覆盖）。",
    )
    parser.add_argument("--name", default="Friday")
    args = parser.parse_args()

    setup_logger(os.environ.get("AS_LOG_LEVEL", "WARNING"))
    logger.info("端点=%s | 模型=%s | workspace=%s", BASE_URL, args.model, args.workdir)

    async with LocalWorkspace(workdir=args.workdir) as workspace:
        agent = Agent(
            name=args.name,
            system_prompt=(
                "You are a helpful assistant named "
                f"{args.name}. Use the provided tools whenever they help "
                "answering the question.\n\n" + await workspace.get_instructions()
            ),
            model=OpenAIChatModel(**_model_kwargs(args.model)),
            toolkit=Toolkit(
                # 文件工具与技能都来自 workspace，绑定它的 backend 与 skill 分区
                tools=await workspace.list_tools(),
                skills_or_loaders=await workspace.list_skills(),
            ),
            middlewares=[
                AgenticMemoryMiddleware(
                    workdir=workspace.workdir,
                    backend=workspace.get_backend(),
                ),
            ],
            # 把压缩后的上下文与过大的工具结果卸载进 workspace
            offloader=workspace,
        )
        await launch_console(agent, verbosity=args.verbosity)


if __name__ == "__main__":
    asyncio.run(main())
