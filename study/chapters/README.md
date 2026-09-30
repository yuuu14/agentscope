# AgentScope 2.0 章节

面向 hgt-2 迭代的源码学习材料。基线 `v2.0.8-77`（`a388212`），分支 `study/arch-and-examples`。

| 章 | 标题 | 内容 |
|---|---|---|
| 1 | [快速上手](01-quickstart.md) | 环境、最小 Agent、换端点（含跨内外网的代理控制）、观测事件流、踩坑清单 |
| 2 | [框架机制](02-framework-mechanisms.md) | 四层架构、六个抽象、三态主循环、事件系统、工具批处理、中间件、状态、HITL、`max_iters`、可替换性 |
| 3 | [接自有工具](03-custom-tool.md) | 包 API vs 包 pipeline 的取舍、`ToolBase` 契约、scope→平台配置→cbb 全链路、三个实测坑 |
| 4 | [服务化](04-service-layer.md) | `app` 四层分工、凭据→agent→会话→SSE 生命周期、fire-and-forget 与事件重放、三个实测坑 |

## 配套材料（`study/` 根目录）

- `agentscope-study-map.md` —— 仓库测绘与阅读顺序
- `agentscope-reply-impl.md` —— `_reply_impl` 逐段精读
- `agentscope-hgt2-onboarding.md` —— 7 课时课程 + examples 全景对照
- `images/agentscope-agent-flow.html` —— Agent 执行流程图（矢量源；PNG 由 `render-flow.sh` 生成）
- `smoke_internal.py` —— 打全事件流的冒烟脚本（内网端点）
- `console_internal.py` —— 交互式终端 console（内网端点，开箱即用）
- `tools/wenshu_tool.py` / `agent_with_wenshu.py` —— 第 3 章的自有工具与其 agent 接入
- `app_client_demo.py` —— 第 4 章的 HTTP 驱动脚本（配合 `app_internal.py`）

## 尚未成章（计划）

- 第 5 章：IM 通道接入（`DingTalkChannel` 为模板）
- 第 6 章：RAG 与长期记忆
- 第 7 章：编排（Pipeline / A2A / agent team）
