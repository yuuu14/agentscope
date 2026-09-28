# AgentScope 2.0 章节

面向 hgt-2 迭代的源码学习材料。基线 `v2.0.8-77`（`a388212`），分支 `study/arch-and-examples`。

| 章 | 标题 | 内容 |
|---|---|---|
| 1 | [快速上手](01-quickstart.md) | 环境、最小 Agent、换端点（含跨内外网的代理控制）、观测事件流、踩坑清单 |
| 2 | [框架机制](02-framework-mechanisms.md) | 四层架构、六个抽象、三态主循环、事件系统、工具批处理、中间件、状态、HITL、`max_iters`、可替换性 |

## 配套材料（`study/` 根目录）

- `agentscope-study-map.md` —— 仓库测绘与阅读顺序
- `agentscope-reply-impl.md` —— `_reply_impl` 逐段精读
- `agentscope-hgt2-onboarding.md` —— 7 课时课程 + examples 全景对照
- `agentscope-agent-flow.html` —— Agent 执行流程图（源文件，可直接用浏览器打开）
- `smoke_internal.py` —— 打全事件流的冒烟脚本（内网端点）

## 尚未成章（计划）

- 第 3 章：接自有工具（`ToolBase` / `FunctionTool` / `Toolkit` + 权限声明）
- 第 4 章：服务化（`app/` 多租户、会话、存储）
- 第 5 章：IM 通道接入（`DingTalkChannel` 为模板）
- 第 6 章：RAG 与长期记忆
- 第 7 章：编排（Pipeline / A2A / agent team）
