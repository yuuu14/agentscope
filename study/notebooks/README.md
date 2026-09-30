# notebooks/ —— 课件

配套 `chapters/` 的可运行课件。**每章一个 notebook**，代码块都能直接跑。

## 环境

`study/` 是一个**独立 uv 项目**（`study/pyproject.toml`），通过 path 源复用仓库里的
`agentscope`，所以课件永远跟当前 checkout 同源。

```bash
uv sync --project study            # 建 study/.venv（已装 jupyterlab/ipykernel）
uv run --project study jupyter lab # 起 JupyterLab，选 kernel 时选 study/.venv
```

命令行跑某个课件：

```bash
uv run --project study jupyter execute study/notebooks/01-quickstart.ipynb
```

## 课件

| 文件 | 对应章节 | 可验证的东西 |
|---|---|---|
| `01-quickstart.ipynb` | 第 1 章 | 端点可达性、最小 Agent、事件流内容 |
| `02-mechanisms.ipynb` | 第 2 章 | 三态循环轮次、事件不变量断言 |
| `03-custom-tool.ipynb` | 第 3 章 | `WenshuQueryTool` 直调（真实数据） |
| `04-service.ipynb` | 第 4 章 | 起服务 → HTTP 驱动 → SSE 事件流（**自包含，含收尾停服务**） |

## 源文件是 `.py`（jupytext percent 格式）

`*.py` 是**可维护的源**，`*.ipynb` 由它生成：

```bash
uv run --project study jupytext --to notebook study/notebooks/01-quickstart.py
```

改课件请改 `.py`，再转 `.ipynb` —— 直接改 `.ipynb` 的 JSON 既难 diff 也容易冲突。

## 坑：代理可能来自**系统设置**，不只是环境变量

本机（macOS）配了系统级代理（`scutil --proxy`，127.0.0.1:7892）。httpx 在 `trust_env=True`
（默认）时会读它，把发往内网 `10.x` 的请求丢给代理 → 代理够不到内网 → 挂 ~31s → 502。

**只 `unset` 环境变量不够**（环境里本来就没有），必须显式绕过：

```bash
export NO_PROXY="10.48.3.23,10.48.2.201,localhost,127.0.0.1"
```

`build.sh` 已内置这一行；`04-service.ipynb` 起服务时也会把它注入子进程环境。

## 坑：notebook 里别用 `asyncio.run()`

Jupyter kernel **本来就有运行中的事件循环**（IPython autoawait），`asyncio.run(...)` 会报
`cannot be called from a running event loop`。课件里统一用**顶层 `await`** ——
这是 notebook 的惯用法，jupytext 与 nbclient 都支持。

（`study/` 下的**脚本**则相反：它们是普通 Python 进程，必须用 `asyncio.run(...)`。）

## 依赖：内网网关 + cbb

课件里的模型调用走**内网 gpu-wrap 网关**，03 还要连 **cbb text-to-metrics**。两者任一不可用时，
对应 cell 会失败（其余内容仍可阅读）。

实测遇到的失败形态：

- 网关故障 → `500 服务内部错误`，agentscope 会**自动重试 4 次（间隔 1s）**后才抛
  `InternalServerError`；
- 网关上游断开 → `503 upstream connect error or disconnect/reset before headers`。

**恢复后重跑即可**：

```bash
./build.sh 03        # 只重建 03；不带参数则全部
```

> 状态：01 / 02 已执行并嵌入输出；**03 的代码与脚本等价（脚本侧已验证跑通）**，
> 但构建当时网关不可用，故 03 未嵌入输出 —— 网关恢复后重跑 `./build.sh 03`。

## 注意

- 课件会调用**内网**模型端点与 cbb 取数服务；**外网不可用时相关 cell 会失败**，不影响其余内容阅读。
- 鉴权值从 `_config/.auth` 读取，**不写进课件**。
