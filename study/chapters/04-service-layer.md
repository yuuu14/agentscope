# 第 4 章 · 服务化

> 目标：看懂 `agentscope.app` 的分层，并把 agent 变成**多租户 HTTP 服务**；最后真的用 HTTP 驱动一遍。
> 配套：`study/app_internal.py`（最小服务）+ `study/app_client_demo.py`（HTTP 驱动脚本）。

## 4.1 单机 Agent 缺什么

第 1–3 章都是 `await agent.reply(msg)` —— 进程内、单用户、结果丢了就没了。要上服务，缺四件事：

| 缺什么 | 服务层的答案 |
|---|---|
| 多用户 / 多会话隔离 | 所有存储按 `user_id` 分区；会话绑 `(user, agent, workspace)` |
| 状态持久 | 可插拔 `StorageBase`（Redis / SQLAlchemy） |
| 长任务 + 前端实时看 | `POST /chat/` fire-and-forget + `GET /sessions/{id}/stream` SSE |
| 人工确认跨请求续传 | `UserConfirmResultEvent` 走同一入口，由调度器续跑停泊的会话 |

## 4.2 四层分工

```
app/_router/         ← HTTP 层：17 个 router（agent / sessions / chat / credential /
                        knowledge_base / mcp / skill / channel / schedule …）
app/_service/        ← 业务层：chat 编排、toolkit 组装、资源访问(access)、索引 worker
app/_manager/        ← 运行态：chat_run_registry(同会话单飞)、取消、唤醒、调度
app/storage/ + app/message_bus/   ← 可插拔后端：Redis 或 SQLAlchemy；总线内存或 Redis
```

组装入口只有一个：

```python
create_app(storage=..., message_bus=..., workspace_manager=..., **可选)
```

`create_app` 只收**具体实现**（依赖注入），不关心你用 Redis 还是 SQLite —— 这就是第 2 章
「可替换性」在服务层的体现。

生命周期：`_lifespan.py:58` 用 `enter_async_context(storage)` 统一开合，所以调用方不需要
自己 `await storage.__aenter__()`。

## 4.3 最小可跑的服务

`study/app_internal.py` 与原版 `examples/agent_service/main.py` 的取舍：

| 原版 | 最小版 |
|---|---|
| `RedisStorage` | `AsyncSQLAlchemyStorage("sqlite+aiosqlite:///…")`，`create_tables=True` 自动建表 |
| `CollectionPerKbManager` + Qdrant | 关掉知识库 |
| `GitHubMCPHub` / `ClawSkillHub` | 关掉 |
| DingTalk / Discord / Feishu | `enable_channel_worker=False` |
| 索引 worker / 调度器 | `enable_index_worker=False` / `enable_scheduler=False` |
| — | 加 CORS（前端跨端口必需） |

## 4.4 一次对话的生命周期（实测）

```
POST /credential/  {data:{type, base_url, api_key}}        → credential_id
POST /agent/       {name, system_prompt, …}                → agent_id
POST /sessions/    {agent_id, chat_model_config, …}        → session_id
GET  /sessions/{sid}/stream?agent_id=…     ← SSE（先重放缓冲，再推实时）
POST /chat/        {agent_id, session_id, input}           → {status:"started"}
```

四个要点：

1. **三段式**：凭据（密钥从哪来）→ agent（人设/配置）→ 会话（把 agent + workspace + 模型绑一起）。
2. **模型类由凭据决定**：`_service/_model.py` 里是 `credential.get_chat_model_class()`，
   `ChatModelConfig.type` **不参与选类**；随后还会用匹配的模型卡回填 `context_size` 与
   `input_types`。所以选 `deepseek_credential` 才是关键（见第 3 章 / README 的 Web UI 坑）。
3. **`/chat/` 是 fire-and-forget**：响应体只有一个 `{status, session_id}`，
   **事件全部走 SSE**。别指望在 POST 响应里拿到回答。
4. **SSE 会先重放**：订阅时会先把当前 run 的缓冲事件吐一遍，再接实时流 —— 所以订阅稍晚
   也不会丢开头。

身份：`app/deps.py:33` 的 `get_current_user_id` 从 **`X-User-ID`** 头取，缺失直接 401
（注释写明是临时方案，将来换 JWT）。

## 4.5 实测输出（14 个事件）

```
[0] /health  → 200 {"status":"ok","version":"2.0.8","components":{"storage":"ok","message_bus":"ok"…}}
[1] 凭据    → 71561406267c4377988ae4fd9f57bd2c
[2] agent   → f2fb8330c5b74c9f911b618e24afcb26
[3] 会话    → d4a073e8d8b2409291d11bb927e97426
[4] 订阅 SSE → 200 text/event-stream; charset=utf-8
[5] 触发 chat → 200 {"status":"started",…}
    ← REPLY_START / HINT_BLOCK / MODEL_CALL_START / TEXT_BLOCK_START
    ← TEXT_BLOCK_DELTA '你好' … '任务。'（7 片）
    ← TEXT_BLOCK_END / MODEL_CALL_END / REPLY_END "completed"
[6] 共收到 14 个事件
```

对照第 1 章的事件不变量：`REPLY_START` 在首、`REPLY_END` 在尾、块级事件成对 —— 服务层
只是把同一条事件流换了条传输通道（SSE），**协议没变**。而且服务端把事件名转成了大写下划线
（`TEXT_BLOCK_DELTA`），前端按这个开关渲染。

## 4.6 三个坑

| # | 现象 | 原因 / 解法 |
|---|---|---|
| 1 | `GET /sessions/{id}/stream` 返回 **422**（JSON，不是事件流） | 它是**必填 query** `?agent_id=`（用于归属校验），漏了就是校验失败 |
| 2 | `POST /sessions/` 建会话 422 | `chat_model_config.parameters` 是**必填 dict**，给 `{}` |
| 3 | 服务起了但一直没事件 | `/chat/` 只在**订阅建立之后**产生事件；先订阅再触发（脚本里 `await asyncio.sleep(1.0)` 就是这个作用） |

## 4.7 与单机 Agent 的关系

**同一份内核**。服务层没换 Agent，只是在外面套了三件事：**会话（隔离）、持久化（存储）、推送（SSE）**。
所以第 2 章的主循环、第 3 章的工具，在服务里原样生效。

想把第 3 章的自定义工具接进服务，用 `create_app(extra_agent_tools=…)` —— 这是服务层的
工具扩展点，不用改 router。

## 4.8 代码

| 文件 | 作用 |
|---|---|
| `study/app_internal.py` | 最小服务（SQLite + 内存总线，无 Redis/Qdrant/IM） |
| `study/app_client_demo.py` | 用 HTTP 走完：凭据 → agent → 会话 → SSE → chat |

```bash
# 终端 A
python3 study/app_internal.py
# 终端 B
python3 study/app_client_demo.py
python3 study/app_client_demo.py --question "2026年每个月的销售收入是多少？"
```

上一章：[第 3 章 · 接自有工具](03-custom-tool.md)
