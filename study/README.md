# study/ — AgentScope 2.0 上手笔记与验证脚本

本目录是**学习产物，非上游代码**。分支 `study/arch-and-examples`（基线 `a388212` = v2.0.8-77）。

## 笔记

| 文件 | 内容 |
|---|---|
| `agentscope-study-map.md` | 仓库架构测绘、四层积木、6 个核心抽象、阅读顺序 |
| `agentscope-reply-impl.md` | `Agent._reply_impl` ReAct 主循环逐段精读（决策/执行分离、批处理、max_iters 语义） |
| `agentscope-hgt2-onboarding.md` | 面向 hgt-2 的 7 课时课程 + 10 个 examples 与其所在层次对照 |

## 脚本

- `smoke_glm.py` —— 跑一次 `reply_stream` 并打印**全部 AgentEvent**（学事件系统的原始素材）。
  端点/模型由 `AS_BASE_URL` / `AS_MODEL` 控制。
- `console_openai.py` —— 通用 **OpenAI 兼容** console（把 `examples/console/main.py` 的 DashScope 换掉）。
  读 `AGENTSCOPE_TOKEN` / `AGENTSCOPE_BASE_URL` / `AGENTSCOPE_MODEL`。

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
