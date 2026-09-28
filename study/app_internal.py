#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小可用的 AgentScope 服务 —— 作为 examples/web_ui 的后端。

对照 examples/agent_service/main.py，把重依赖全部换成轻量本地实现：

| 原版 | 本脚本 |
| --- | --- |
| `RedisStorage` | `AsyncSQLAlchemyStorage("sqlite+aiosqlite:///…")`（`create_tables=True` 自动建表，**不需要 alembic**） |
| `CollectionPerKbManager` + `QdrantStore` | 不启用知识库 |
| `GitHubMCPHub` / `ClawSkillHub` | 不启用 |
| DingTalk / Discord / Feishu 通道 | 不启用（`enable_channel_worker=False`） |
| `default_mcps`（playwright / amap） | 留空 |
| 索引 worker / 调度器 | 关闭 |
| subagent 模板 | 从简 |

**开箱即用**：解释器缺依赖时自动切到仓库 `.venv`。

启动后怎么用：

1. 打开前端（vite dev，默认 5173），在 `/setup` 页把服务地址填成
   `http://127.0.0.1:8000`；
2. 到 Credential 页新建一条 **OpenAI 兼容**凭据：
   - base_url：`http://10.48.3.23:48080/gpu-wrap-server`
   - 密钥：见 `/Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth`
     里的 `GPU_WRAP_SERVER_API_KEY_TEST`（本脚本**不会打印密钥**）
3. 建 agent / 会话，选模型 `deepseek-v4-flash`，即可在 Chat 页对话。

用法::

    python3 study/app_internal.py                 # 0.0.0.0:8000
    python3 study/app_internal.py --port 9000
    python3 study/app_internal.py --db /tmp/as.db --workdir /tmp/as-ws

可选环境变量：``AS_HOST`` / ``AS_PORT``。
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_VENV_PY = REPO / ".venv" / "bin" / "python"


def _ensure_deps() -> None:
    """缺依赖就切到仓库自带的 .venv 解释器重跑一次。"""
    try:
        import agentscope.app  # noqa: F401
        import fastapi  # noqa: F401
        import sqlalchemy  # noqa: F401
        import aiosqlite  # noqa: F401
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
        "缺少 app 层依赖。请在仓库根目录执行：\n"
        "  HTTPS_PROXY=http://127.0.0.1:7892 uv pip install -e "
        '".[service,storage-sql]" aiosqlite',
    )


_ensure_deps()

import argparse  # noqa: E402

import uvicorn  # noqa: E402
from fastapi.middleware import Middleware  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from agentscope.app import create_app  # noqa: E402
from agentscope.app.message_bus import InMemoryMessageBus  # noqa: E402
from agentscope.app.storage import AsyncSQLAlchemyStorage  # noqa: E402
from agentscope.app.workspace_manager import LocalWorkspaceManager  # noqa: E402

STUDY_DIR = Path(__file__).resolve().parent
DEFAULT_DB = STUDY_DIR / "workspaces" / "app.db"
DEFAULT_WORKDIR = STUDY_DIR / "workspaces" / "agents"


def build_app(db_path: Path, workdir: Path):
    """Assemble the minimal service."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    storage = AsyncSQLAlchemyStorage(
        f"sqlite+aiosqlite:///{db_path}",
        create_tables=True,   # 自动建表，免 alembic 迁移
        auto_migrate=False,
    )

    return create_app(
        storage=storage,
        message_bus=InMemoryMessageBus(),
        workspace_manager=LocalWorkspaceManager(
            basedir=str(workdir),
            default_mcps=[],          # 原版会拉 playwright / amap
        ),
        knowledge_base_manager=None,  # 关掉知识库（原本要 Qdrant）
        mcp_hubs=None,
        skill_hubs=None,
        enable_index_worker=False,
        enable_channel_worker=False,
        enable_scheduler=False,
        # 前端跑在另一个端口，必须放开 CORS
        extra_middlewares=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
        channels=None,
        title="AgentScope (study minimal)",
    )


def main() -> None:
    """Start the service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("AS_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AS_PORT", "8000")),
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    args = parser.parse_args()

    app = build_app(Path(args.db), Path(args.workdir))

    print("=" * 68)
    print(f"AgentScope 最小服务  →  http://{args.host}:{args.port}")
    print(f"  OpenAPI 文档       →  http://{args.host}:{args.port}/docs")
    print(f"  SQLite             →  {args.db}")
    print(f"  agent workspace    →  {args.workdir}")
    print("-" * 68)
    print("前端 Setup 页请填这个服务地址；凭据页用 OpenAI 兼容 + 内网 base_url。")
    print("=" * 68)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
