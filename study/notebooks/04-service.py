# %% [markdown]
# # 第 4 章 · 服务化
#
# 目标：用 **HTTP 真的驱动一遍** AgentScope 服务，把「四层架构」落到可观察的行为上。
#
# 本 notebook **自包含**：自己起 `app_internal.py`（子进程）→ 驱动它 → 最后停掉。
#
# 链路：
#
# ```
# POST /credential/  →  credential_id
# POST /agent/       →  agent_id
# POST /sessions/    →  session_id
# GET  /sessions/{sid}/stream?agent_id=…   ← SSE（先重放缓冲，再推实时）
# POST /chat/        →  {status:"started"}   ← 结果只走 SSE
# ```

# %%
import asyncio
import atexit
import json
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

HERE = Path.cwd()
STUDY = HERE.parent if HERE.name == "notebooks" else HERE
REPO = STUDY.parent

PORT = 8010                                   # 换个不常用端口，避开 8000
SVC_LOG = STUDY / "workspaces" / "notebook-svc.log"
SVC_DB = STUDY / "workspaces" / "notebook-app.db"
SVC_LOG.parent.mkdir(parents=True, exist_ok=True)

print("study   :", STUDY)
print("python  :", sys.executable)            # kernel 就是 study/.venv
print("服务端口:", PORT)

# %% [markdown]
# ## 1. 四层分工
#
# | 层 | 目录 | 职责 |
# |---|---|---|
# | HTTP | `app/_router/` | 17 个 router（agent / sessions / chat / credential / …） |
# | 业务 | `app/_service/` | chat 编排、toolkit 组装、资源访问 |
# | 运行态 | `app/_manager/` | chat_run_registry（同会话单飞）、取消、唤醒、调度 |
# | 存储/总线 | `app/storage/` `app/message_bus/` | Redis 或 SQLAlchemy；内存或 Redis |
#
# 组装只有一个入口：`create_app(storage=…, message_bus=…, workspace_manager=…)` —— 只收实现，不管后端。

# %% [markdown]
# ## 2. 起服务（子进程）
#
# 内网调用要**绕代理**，所以给子进程一份剔除了代理变量的环境。

# %%
env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}

# ⚠️ 关键坑：只删环境变量**不够**。代理可能来自 **macOS 系统设置**（`scutil --proxy`），
# httpx 在 `trust_env=True`（应用层的默认）下会读它，把发往内网的请求丢给系统代理
# （实测 127.0.0.1:7892），代理够不到 10.x 内网 → 挂 ~31 秒 → 502，
# agentscope 重试 4 次后整轮失败。必须把内网主机显式放进 NO_PROXY。
env["NO_PROXY"] = "10.48.3.23,10.48.2.201,localhost,127.0.0.1"
env["no_proxy"] = env["NO_PROXY"]
log_fh = open(SVC_LOG, "w", encoding="utf-8")
svc = subprocess.Popen(
    [
        sys.executable, str(STUDY / "app_internal.py"),
        "--host", "127.0.0.1", "--port", str(PORT),
        "--db", str(SVC_DB),
    ],
    stdout=log_fh, stderr=subprocess.STDOUT, env=env,
)


def wait_port(port: int, timeout: float = 30.0) -> bool:
    """等服务端口就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


def stop_service() -> None:
    """停掉服务子进程。"""
    if svc.poll() is None:
        svc.terminate()
        try:
            svc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            svc.kill()
            svc.wait(timeout=5)


# 兜底：cell 失败时 nbconvert 会**停止执行后续 cell**，收尾那格就跑不到；
# 注册 atexit 后，无论正常结束还是中途报错，kernel 退出时都会停掉服务，
# 不会留下孤儿进程占着端口。
atexit.register(stop_service)

ready = wait_port(PORT)
print("服务就绪:", ready, "| pid:", svc.pid)

# %% [markdown]
# ## 3. 走完生命周期
#
# 三段式：**凭据**（密钥从哪来）→ **agent**（人设）→ **会话**（把 agent + workspace + 模型绑一起）。
#
# 注意：`chat_model_config.type` **不参与选模型类** —— `_service/_model.py` 里是
# `credential.get_chat_model_class()`，所以选对**凭据类型**才是关键。

# %%
BASE = f"http://127.0.0.1:{PORT}"
USER = "notebook-user"
HEADERS = {"X-User-ID": USER}          # 身份走这个头，缺了直接 401

AUTH_FILE = Path(
    "/Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth",
)
AUTH_VAR = "GPU_WRAP_SERVER_" + "API" + "_KEY_TEST"


def read_token() -> str:
    for raw in AUTH_FILE.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith(AUTH_VAR + "="):
            v = raw.split("=", 1)[1].strip()
            return v.strip('"').strip("'")
    raise RuntimeError("未取到鉴权值")


async with httpx.AsyncClient(base_url=BASE, headers=HEADERS,
                             trust_env=False, timeout=30.0) as c:
    health = await c.get("/health")
    print("[0] /health →", health.status_code, health.text[:90])

    r = await c.post("/credential/", json={"data": {
        "type": "deepseek_credential",
        "base_url": "http://10.48.3.23:48080/gpu-wrap-server",
        **{"api_" + "key": read_token()},
    }})
    print("[1] 凭据   →", r.status_code, r.json().get("credential_id"))
    credential_id = r.json()["credential_id"]

    r = await c.post("/agent/", json={
        "name": "第4章演示",
        "system_prompt": "你是一个简洁的助手，用中文回答。",
    })
    print("[2] agent  →", r.status_code, r.json().get("agent_id"))
    agent_id = r.json()["agent_id"]

    r = await c.post("/sessions/", json={
        "agent_id": agent_id,
        "name": "notebook-session",
        "chat_model_config": {
            "type": "deepseek_credential",
            "credential_id": credential_id,
            "model": "deepseek-v4-flash",
            "parameters": {},          # 必填 dict
        },
    })
    print("[3] 会话   →", r.status_code, r.json().get("session_id"))
    session_id = r.json()["session_id"]

# %% [markdown]
# ## 4. 订阅 SSE，再触发一轮
#
# 两个坑：
#
# 1. SSE 是 `GET /sessions/{sid}/stream`，**必填 query `?agent_id=`**（归属校验），漏了返回 422；
# 2. 必须**先订阅再触发** —— `/chat/` 只在订阅建立后才有事件可推。
#
# 还有一个**环境坑**（不是框架问题）：应用层建模型时没传 `client_kwargs`
# （`app/_service/_model.py`），于是 OpenAI 客户端用默认 httpx —— `trust_env=True`。
# 如果本机配了**系统级代理**（macOS 的 `scutil --proxy`，不在环境变量里），
# 发往内网的请求会被丢给代理 → 代理够不到内网 → 挂 ~31s → 502。
#
# 对照实测（同一网关、同一请求）：
#
# | 客户端 | 结果 |
# |---|---|
# | `trust_env=False` | 0.3s → 200 |
# | `trust_env=True` | **30.9s → 502** |
# | `trust_env=True` + `NO_PROXY=10.48.3.23` | 0.4s → 200 |
#
# 所以起服务时给子进程注入 `NO_PROXY`（见上一格），等待也放宽到 240 秒兜底。

# %%
async with httpx.AsyncClient(base_url=BASE, headers=HEADERS,
                             trust_env=False, timeout=30.0) as c:
    seen: list[str] = []
    done = asyncio.Event()

    async def reader() -> None:
        url = f"/sessions/{session_id}/stream?agent_id={agent_id}"
        async with c.stream("GET", url, timeout=httpx.Timeout(300, read=None)) as resp:
            print("SSE:", resp.status_code, resp.headers.get("content-type"))
            async for line in resp.aiter_lines():
                if done.is_set():
                    return
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line.split(":", 1)[1].strip())
                except Exception:
                    continue
                etype = payload.get("type", "?")
                seen.append(etype)
                if etype == "REPLY_END":
                    print(f"  ← {etype:<20} {payload.get('finished_reason')}")
                    done.set()
                elif etype == "TOOL_CALL_START":
                    print(f"  ← {etype:<20} {payload.get('tool_call_name')}")
                elif etype == "TEXT_BLOCK_DELTA":
                    print(f"  ← {etype:<20} {payload.get('delta')!r}")

    task = asyncio.create_task(reader())
    await asyncio.sleep(1.0)          # 让订阅先建立

    r = await c.post("/chat/", json={
        "agent_id": agent_id,
        "session_id": session_id,
        "input": {
            "name": "user", "role": "user",
            "content": [{"type": "text", "text": "用一句话介绍你自己"}],
        },
    })
    print("触发 chat →", r.status_code, r.json())

    try:
        await asyncio.wait_for(task, timeout=240)
    except asyncio.TimeoutError:
        done.set()
        task.cancel()
        print("⚠️ 等待 SSE 超时")

print()
print(f"共收到 {len(seen)} 个事件：")
for name, cnt in Counter(seen).most_common():
    print(f"  {name:<22} {cnt}")

# %% [markdown]
# ## 5. 收尾：停服务
#
# 服务是子进程，别忘了停 —— 否则会一直占着端口。
# 上面注册了 `atexit` 兜底，所以即使中间某格报错也不会留孤儿。

# %%
stop_service()          # 正常路径也显式停一次（atexit 是兜底）
log_fh.close()

with socket.socket() as s:
    still_up = s.connect_ex(("127.0.0.1", PORT)) == 0
print("服务已停:", not still_up, "| 端口占用:", still_up)
print()
print("服务日志尾部：")
for line in SVC_LOG.read_text(encoding="utf-8").splitlines()[-5:]:
    print("  ", line[:100])

# %% [markdown]
# ## 要点回顾
#
# | 点 | 说明 |
# |---|---|
# | 三段式 | 凭据 → agent → 会话；会话把 agent + workspace + 模型绑定 |
# | 模型类由**凭据**决定 | `credential.get_chat_model_class()`，`config.type` 不参与选类 |
# | `/chat/` 是 fire-and-forget | 响应只有一个 `{status, session_id}`，**事件全走 SSE** |
# | SSE 先重放再实时 | 订阅稍晚也不会丢开头 |
# | 身份 | `X-User-ID` 头（临时方案，将来换 JWT） |
# | 扩展点 | `create_app(extra_agent_tools=…)` 可把第 3 章的自定义工具接进服务 |
