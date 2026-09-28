# study/ — AgentScope 2.0 上手笔记与验证脚本

本目录是**学习产物，非上游代码**。分支 `study/arch-and-examples`（基线 `a388212` = v2.0.8-77）。

## 笔记

| 文件 | 内容 |
|---|---|
| `agentscope-study-map.md` | 仓库架构测绘、四层积木、6 个核心抽象、阅读顺序 |
| `agentscope-reply-impl.md` | `Agent._reply_impl` ReAct 主循环逐段精读（决策/执行分离、批处理、max_iters 语义） |
| `agentscope-hgt2-onboarding.md` | 面向 hgt-2 的 7 课时课程 + 10 个 examples 与其所在层次对照 |

## 脚本

| 脚本 | 用途 |
|---|---|
| `console_internal.py` | **交互式终端 console**（参照 `examples/console/main.py`），改用内网模型；含 workspace 文件工具、技能、长期记忆、offloader |
| `smoke_internal.py` | 跑一次 `reply_stream`，把**事件内容**按单行 JSON 打日志（观测 / 学事件系统用） |
| `smoke_glm.py` | 同上，但默认外网 GLM 端点 |
| `console_openai.py` | 通用 OpenAI 兼容 console（token 需自行提供） |

全部**开箱即用**：不需要 export 环境变量 —— 鉴权默认从 `_config/.auth` 读、
`trust_env=False` 兜住代理、解释器会自动切到仓库自带 `.venv`。

## 图表

- `images/agentscope-agent-flow.html` —— Agent 执行流程图（矢量源）
- `images/agentscope-agent-flow.png` —— 由 `render-flow.sh` 生成，第 2 章引用

```bash
cd /Users/elias/Developer/yuuu14/agentscope
export HTTPS_PROXY=http://127.0.0.1:7892 HTTP_PROXY=http://127.0.0.1:7892 ALL_PROXY=http://127.0.0.1:7892
.venv/bin/python study/smoke_glm.py
```

## 环境（本机已就绪）

- `.venv`（Python 3.12）+ `uv pip install -e .`（内核）；`agentscope 2.0.8` 可 import。
- ⚠️ **外网装依赖必须走代理**：直连 pypi.org / 清华源均 ~12s 超时，裸装会卡死。
- ⚠️ **内网模型端点必须 unset 代理**（两者方向相反）。
- ⚠️ 用 `write` 工具写含 `api_key=` / `credential=` 的脚本会被**脱敏成 `***`** 导致语法错误；
  改用 heredoc 落盘，并 `py_compile` 验证。

## 已实证

真实模型 + 工具调用 + 事件流跑通：`glm-5.3` 一次回复 300 个事件，2 轮 ReAct，1 次 `Glob` 调用。
细节见 `memory/2026-09-28.md`（workspace 内）。

## Web UI（examples/web_ui）

仓库自带一套 Web UI（`examples/web_ui`，Vite + React 19 + Tailwind）。注意它的
`backend/` 只是 **16 行占位 stub**（仅 `/api/health`），真正的后端是 Python 的
`agentscope.app`。

本目录提供 **`app_internal.py`** —— 去掉 Redis / Qdrant / IM 通道的最小服务。

```bash
# 1) 装 app 层依赖（只需一次；外网 PyPI 要走代理）
HTTPS_PROXY=http://127.0.0.1:7892 uv pip install -e ".[service,storage-sql]" aiosqlite

# 2) 起后端（SQLite + 自动建表，无需 Redis / alembic）
python3 study/app_internal.py                 # → http://127.0.0.1:8000

# 3) 起前端（依赖装一次即可）
cd examples/web_ui
pnpm install --registry https://registry.npmmirror.com
pnpm --filter frontend exec vite --host 127.0.0.1 --port 5173

# 4) 浏览器打开 5173 → /setup 填服务地址 http://127.0.0.1:8000
#    → Credential 页新建凭据（类型见下，**不是 OpenAI**）→ 建会话开始聊天
```

凭据参数：

| 项 | 值 |
|---|---|
| **凭据类型** | **DeepSeek API**（`deepseek_credential`）← 关键 |
| base_url | `http://10.48.3.23:48080/gpu-wrap-server` |
| 模型 | `deepseek-v4-flash` |
| 密钥 | 见 `_config/.auth` 的 `GPU_WRAP_SERVER_API_KEY_TEST`（脚本不打印密钥） |

### ⚠️ 为什么不能用「OpenAI 兼容」凭据

UI 的「available models」不是从 base_url 动态拉的，而是按 **凭据类型 → 模型类 →
该类的 `_models/*.yaml`** 取：

- `openai_credential` → `OpenAIChatModel` → `model/_openai_chat/_models/`，
  里面只有 14 张 gpt / o 系列的卡 → **看不到 deepseek，也没法手填**；
- `deepseek_credential` → `DeepSeekChatModel` → `model/_deepseek/_models/`，
  **已经带了 `deepseek-v4-flash.yaml`**，且 `DeepSeekCredential.base_url` 可改
  （`_deepseek.py` 默认 `https://api.deepseek.com`，改为内网网关即可）。

模型类内部走 `openai.AsyncClient(base_url=self.credential.base_url, **client_kwargs)`
（`model/_deepseek/_model.py:132-135`），所以内网地址与 `trust_env=False` 都能带进去。

实测（`deepseek_credential` + 内网 base_url）：

```
可选模型: ['deepseek-flash', 'deepseek-v4-pro', 'deepseek-v4-flash',
           'deepseek-chat', 'deepseek-reasoner']
一次调用答复: 通了通了
```

实测：最小服务启动成功，67 条路由（`/credential`、`/chat`、`/agent`、`/health` …），
CORS 预检返回 `access-control-allow-origin: *`。
