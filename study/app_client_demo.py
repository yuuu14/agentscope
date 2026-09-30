#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 4 章 · 用 HTTP 驱动 AgentScope 服务（服务化）。

配合 `study/app_internal.py`（最小服务）使用。完整链路：

    POST /credential/   → credential_id
    POST /agent/        → agent_id
    POST /sessions/     → session_id（带 chat_model_config）
    GET  /sessions/{sid}/stream   ← SSE，先重放缓冲事件，再推实时事件
    POST /chat/         → 触发一轮（fire-and-forget，结果只走 SSE）

所有请求都要带 `X-User-ID` 头（`app/deps.py:33` 注入，缺失即 401）。

用法::

    # 终端 A：起服务
    python3 study/app_internal.py
    # 终端 B：驱动它
    python3 study/app_client_demo.py
    python3 study/app_client_demo.py --question "客户总数是多少"
"""
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_VENV_PY = REPO / ".venv" / "bin" / "python"


def _ensure_deps() -> None:
    """缺依赖就切到仓库自带的 .venv 解释器重跑一次。"""
    try:
        import httpx  # noqa: F401
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
    raise SystemExit("缺少依赖，请先 uv pip install -e .")


_ensure_deps()

import argparse  # noqa: E402

import httpx  # noqa: E402

AUTH_FILE = Path(
    os.environ.get(
        "AS_AUTH_FILE",
        "/Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth",
    ),
)
AUTH_VAR = "GPU_WRAP_SERVER_" + "API" + "_KEY_TEST"
MODEL_BASE_URL = "http://10.48.3.23:48080/gpu-wrap-server"
MODEL_NAME = "deepseek-v4-flash"
USER_ID = os.environ.get("AS_USER_ID", "demo-user")
DEFAULT_QUESTION = "你好，请用一句话介绍你自己"


def _read_token() -> str:
    """取鉴权值：AS_TK 环境变量优先，其次 .auth 文件。"""
    value = os.environ.get("AS_TK", "")
    if not value and AUTH_FILE.is_file():
        for raw in AUTH_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith(AUTH_VAR + "="):
                value = line[len(AUTH_VAR) + 1 :].strip()
                value = value.strip('"').strip("'")
                break
    if not value:
        raise SystemExit(f"未取到鉴权值（{AUTH_FILE}）")
    return value


def _j(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


async def main() -> None:
    """Drive the service end to end."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    headers = {"X-User-ID": USER_ID, "Content-Type": "application/json"}

    async with httpx.AsyncClient(
        base_url=args.base,
        headers=headers,
        trust_env=False,
        timeout=30.0,
    ) as client:
        # 0) 服务活着吗
        try:
            health = await client.get("/health")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"连不上服务 {args.base}：{exc}\n"
                "请先起：python3 study/app_internal.py",
            )
        print(f"[0] /health  → {health.status_code} {health.text[:80]}")

        # 1) 凭据
        tok = _read_token()
        r = await client.post(
            "/credential/",
            json={
                "data": {
                    "type": "deepseek_credential",
                    "base_url": MODEL_BASE_URL,
                    **{"api_" + "key": tok},
                },
            },
        )
        r.raise_for_status()
        credential_id = r.json()["credential_id"]
        print(f"[1] 凭据    → {credential_id}")

        # 2) agent
        r = await client.post(
            "/agent/",
            json={
                "name": "第4章演示",
                "system_prompt": "你是一个简洁的助手，用中文回答。",
            },
        )
        r.raise_for_status()
        agent_id = r.json()["agent_id"]
        print(f"[2] agent   → {agent_id}")

        # 3) 会话（模型类由凭据决定，type 不参与选类）
        r = await client.post(
            "/sessions/",
            json={
                "agent_id": agent_id,
                "name": "demo-session",
                "chat_model_config": {
                    "type": "deepseek_credential",
                    "credential_id": credential_id,
                    "model": MODEL_NAME,
                    "parameters": {},
                },
            },
        )
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print(f"[3] 会话    → {session_id}")

        # 4) 先订阅 SSE，再触发（避免漏事件）
        print("[4] 订阅 SSE /sessions/%s/stream" % session_id)
        stop = asyncio.Event()
        seen: list[str] = []

        async def reader() -> None:
            # SSE 必填 query 参数 agent_id（用于归属校验，缺了就是 422）
            url = (
                f"/sessions/{session_id}/stream"
                f"?agent_id={agent_id}"
            )
            async with client.stream(
                "GET", url, timeout=httpx.Timeout(args.timeout, read=None),
            ) as resp:
                print(f"    SSE 响应头: {resp.status_code} "
                      f"{resp.headers.get('content-type')}")
                event_name = None
                async for line in resp.aiter_lines():
                    if stop.is_set():
                        return
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        raw = line.split(":", 1)[1].strip()
                        try:
                            payload = json.loads(raw)
                        except Exception:  # noqa: BLE001
                            continue
                        etype = payload.get("type", event_name or "?")
                        seen.append(etype)
                        self_note = ""
                        if etype == "REPLY_END":
                            self_note = _j(payload.get("finished_reason"))
                            stop.set()
                        elif etype == "TOOL_CALL_START":
                            self_note = payload.get("tool_call_name", "")
                        elif etype == "TEXT_BLOCK_DELTA":
                            self_note = repr(payload.get("delta", ""))[:40]
                        print(f"    ← {etype:<24} {self_note}")

        task = asyncio.create_task(reader())
        await asyncio.sleep(1.0)          # 让订阅先建立

        # 5) 触发一轮
        r = await client.post(
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "name": "user",
                    "role": "user",
                    "content": [{"type": "text", "text": args.question}],
                },
            },
        )
        print(f"[5] 触发 chat → {r.status_code} {r.text[:120]}")

        try:
            await asyncio.wait_for(task, timeout=args.timeout)
        except asyncio.TimeoutError:
            stop.set()
            task.cancel()
            print("    ⚠️ 等待 SSE 超时")
        except asyncio.CancelledError:
            pass

    print()
    print(f"[6] 共收到 {len(seen)} 个事件")
    from collections import Counter

    for name, cnt in Counter(seen).most_common():
        print(f"      {name:<26} {cnt}")


if __name__ == "__main__":
    asyncio.run(main())
