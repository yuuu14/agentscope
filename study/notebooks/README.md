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

## 源文件是 `.py`（jupytext percent 格式）

`*.py` 是**可维护的源**，`*.ipynb` 由它生成：

```bash
uv run --project study jupytext --to notebook study/notebooks/01-quickstart.py
```

改课件请改 `.py`，再转 `.ipynb` —— 直接改 `.ipynb` 的 JSON 既难 diff 也容易冲突。

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
