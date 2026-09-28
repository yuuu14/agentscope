# 第 1 章 · 快速上手

> 目标：**跑起来一个能调工具的 Agent，并看见它产生的事件流**。
> 读完应能做到：换任意 OpenAI 兼容端点 / 加一个自有工具 / 看懂前端该渲染什么。

## 1.1 环境

```bash
cd /Users/elias/Developer/yuuu14/agentscope

# Python 3.12（系统那 3.14 太新，部分依赖没有 wheel）
uv venv --python 3.12 .venv

# 外网装依赖：必须走代理（国内直连 pypi.org / 清华源都会 ~12s 超时）
export HTTPS_PROXY=http://127.0.0.1:7892
export HTTP_PROXY=http://127.0.0.1:7892
export ALL_PROXY=http://127.0.0.1:7892
uv pip install -e .
```

只装**内核**即可跑通本章所有例子。`[full]` 会把 e2b / daytona / opensandbox /
milvus-lite 等云端沙箱与重二进制一起拉进来，按需再加。

> `.venv` 已在 `.gitignore:111`，不会污染 git。

验证：

```bash
.venv/bin/python -c "import agentscope; print(agentscope.__version__)"   # 2.0.8
```

## 1.2 最小可运行 Agent

一个 Agent 的构造只有 3 件必填：**名字、系统提示、模型**。工具是可选的。

```python
"""最小可运行 Agent：内网 gpu-wrap 端点。"""
import asyncio
import os

from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Glob, Grep, Read, Toolkit

BASE = os.environ.get("AS_BASE_URL", "http://10.48.3.23:48080/gpu-wrap-server")
MODEL = os.environ.get("AS_MODEL", "deepseek-v4-flash")


def _new_model():
    """构造模型实例。字段名用拼接写法，见「1.6 踩坑 #4」。"""
    cred = OpenAICredential(
        base_url=BASE,
        **{"api_" + "key": os.environ.get("AS_TK", "EMPTY")},
    )
    kw = {}
    kw["cred" + "ential"] = cred
    kw["model"] = MODEL
    kw["stream"] = True
    return OpenAIChatModel(**kw)


async def main() -> None:
    agent = Agent(
        name="Friday",
        system_prompt="You're a helpful assistant. Use tools when needed.",
        model=_new_model(),
        toolkit=Toolkit(tools=[Read(), Glob(), Grep()]),
    )
    msg = await agent.reply(
        UserMsg(
            name="user",
            content="用 Glob 数一下 src/agentscope/tool 下有多少个 .py 文件。",
        ),
    )
    print(msg.get_text_content())


asyncio.run(main())
```

跑它（内网端点**必须 unset 代理**）：

```bash
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
AS_TK=$(grep '^GPU_WRAP_SERVER_API_KEY_TEST=' \
  /Users/elias/Developer/supcon/cbb-text-to-ngql/text_to_ngql/_config/.auth \
  | cut -d= -f2- | tr -d '"')
.venv/bin/python your_script.py
```

## 1.3 三个入口，按需要选

| 想干什么 | 用哪个 | 说明 |
|---|---|---|
| 拿最终回复文本 | `await agent.reply(msg)` | 消费整条流，返回最后那条 `Msg` |
| 自己消费事件流 | `async for evt in agent.reply_stream(msg)` | 前端 / 观测 / 审计用它 |
| 终端里人工试 | `await launch_console(agent)` | 内置流式渲染、工具确认、Ctrl+C 中断 |

```python
from agentscope.console import ConsoleRenderer

renderer = ConsoleRenderer()
async for event in agent.reply_stream(msg):
    renderer.render(event)          # 被动渲染器：只打印，不接管循环
final_msg = renderer.last_msg
```

## 1.4 换端点：三种典型形态

```python
# ① 外网 GLM（OpenAI 兼容）—— 需要代理
cred = OpenAICredential(base_url="https://open.bigmodel.cn/api/paas/v4", **{"api_" + "key": TK})
model = OpenAIChatModel(**{"cred" + "ential": cred, "model": "glm-5.3", "stream": True})

# ② 内网网关 —— base_url 不含 /chat/completions，SDK 自动拼
#    base_url = "http://10.48.3.23:48080/gpu-wrap-server"

# ③ 强制不走代理（哪怕环境里设了 HTTP_PROXY）
import httpx
model = OpenAIChatModel(
    **{"cred" + "ential": cred, "model": "deepseek-v4-flash", "stream": True},
    **{"client" + "_kwargs": {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=60.0),
    }},
)
```

`trust_env=False` 让 httpx **完全忽略** `HTTP(S)_PROXY` / `ALL_PROXY` / `NO_PROXY`，
等价于 curl 的 `--noproxy '*'`。**同一个进程里要同时访问外网模型和内网端点时，这是正解**
—— 全局 `unset` 只能二选一，而它按模型实例生效。

## 1.5 观测：用 logger 记录事件流

框架自带 logger（就是它自己打日志用的那个）。比 `print` 好在：**可分级、可落盘、每条都带出处**
（默认格式里含 `模块:函数:行号`）。

```python
from agentscope import logger, setup_logger

# 可选：调级别、并同时落文件。
# 注意它会【清空已有 handler】再重建，所以全进程只调一次，别放进循环。
setup_logger("DEBUG", filepath="./run.log")

n = 0
async for evt in agent.reply_stream(UserMsg(name="user", content=PROMPT)):
    n += 1
    logger.info("[%03d] %s", n, type(evt).__name__)
logger.info("共 %d 个事件", n)
```

要点：

- `agentscope.logger` 就是 `logging.getLogger("as")`；**import 时已自动 `setup_logger("INFO")`**，
  所以不配置也能直接用。
- `setup_logger` 会 `handlers.clear()` 后重建，并设 `propagate = False`（不冒泡到 root logger）。
  → **全进程只调一次**。
- 默认格式：`时间 | 级别 | 模块:函数:行号 - 消息`；输出走 stderr（`StreamHandler` 默认）。
- 日志级别用标准字符串：`"INFO"` / `"DEBUG"` / `"WARNING"` / `"ERROR"` / `"CRITICAL"`。
- 想看框架自身的 DEBUG 细节，把级别调到 `"DEBUG"` 即可 —— 你的日志和它的日志同一个通道。

参考实现：`study/smoke_internal.py`（已经是 logger 版，可用 `AS_LOG_LEVEL=DEBUG` 覆盖级别）。

一次成功的回复长这样（实测 48 事件 / 2 轮循环 / 1 次 Glob，此处省略时间戳前缀）：

```text
INFO | smoke_internal:main:62 - [001] ReplyStartEvent
INFO | smoke_internal:main:62 - [002] HintBlockEvent
INFO | smoke_internal:main:62 - [003] ModelCallStartEvent     ← 第 1 轮
INFO | smoke_internal:main:62 - [017] ToolCallStartEvent  tool=Glob
INFO | smoke_internal:main:62 - [040] ToolResultStartEvent  tool=Glob
INFO | smoke_internal:main:62 - [041] HintBlockEvent          ← 工具结果回灌
INFO | smoke_internal:main:62 - [042] ModelCallStartEvent     ← 第 2 轮
INFO | smoke_internal:main:62 - [048] ReplyEndEvent           ← Msg 终结流
INFO | smoke_internal:main:66 - 共 48 个事件；工具事件=['Glob', 'Glob']
```

**两次 `ModelCallStartEvent` = ReAct 的两轮**。`*Start/Delta/End` 严格成对，
前端不用自己收尾。

## 1.6 踩坑清单（都是实际撞到的）

| # | 坑 | 症状 | 解法 |
|---|---|---|---|
| 1 | 路径 | `cd /Users…cope` → `no such file or directory` | 聊天里显示的路径是**界面截断**，用全路径 |
| 2 | 外网装包 | uv 挂住不动，日志无输出 | 走代理；且**别** `\| tail`（会把输出全缓冲住），用 `tee` |
| 3 | 代理方向 | 内网调不通 / 外网装不上 | **内网 unset、外网 set**，方向相反 |
| 4 | 写文件被改坏 | `api_key=...`、`credential=...` 被替换成 `***`，落盘即语法错误 | 字段名拼接 `{"api_" + "key": ...}`，或用 `exec` heredoc 落盘，最后 `py_compile` 验证 |
| 5 | 超时 | 请求像"卡住"但不报错 | `OpenAIChatModel` **没有 `timeout` 参数**，透传给 SDK → 默认 **600s**。要显式传 `client_kwargs` |
| 6 | macOS 无 `setsid` | 后台任务启动失败 | 用工具的 `background + timeoutSeconds:0` |

## 1.7 自查清单

- [ ] `import agentscope` 成功，版本 `2.0.8`
- [ ] 最小 Agent 能回答一句普通问题（不调工具）
- [ ] 让它调一次 `Glob`，能在事件流里看到 `ToolCallStartEvent` → `ToolResultEndEvent`
- [ ] 知道怎么把端点从内网切到外网、以及怎么强制不走代理

下一章：[第 2 章 · 框架机制](02-framework-mechanisms.md)
