#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 3 章 · 接自有工具：把 hgt-2 的问数能力封成 AgentScope 工具。

设计取舍（为什么不直接包 WenshuAgent，见 chapters/03-custom-tool.md）：

- **包 cbb API，不包 pipeline**：`WenshuAgent.run()` 的 docstring 明说
  「单次调用 cbb /query（cbb 内部完成 split + 并行执行 + 聚合）」，所以重活不在
  hgt-2 侧。包 pipeline 会把 hgt-2 的 `AgentRequest`/事件总线/`LLMEngine`/
  `SUMMARIZATION_LLM_CONFIG` 一起拖进来，形成「agentscope → hgt-2 → cbb」三明治。
- **上下文运行时解析**：`scope` → scene ref → 平台配置接口 →
  `agent_id` / `selected_data_model_ids`。不写死，平台改了模型清单自动跟随。
- **不传 `llm_config` / `embed_config`**：cbb 层面实测为选填（422 只报 user_id/user_name）。
- **`environment-url` 必须给裸基址**：cbb 自己会拼
  `/msService/public/hgt-data-connector/algorithm/query`。拼满会导致路径重复 → 401。
- **不做总结**：把「取数」和「成文」分开，总结交给外层 agent（它本来就有模型）。

实测（test 环境）：
    scope=business_operations → agent_id=9 / 76 个数据模型 → cbb 200（15s）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
_VENV_PY = REPO / ".venv" / "bin" / "python"


def _ensure_deps() -> None:
    """缺依赖就切到仓库自带的 .venv 解释器重跑一次。"""
    try:
        import agentscope  # noqa: F401
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
    raise SystemExit("缺少依赖，请先在仓库根目录 uv pip install -e .")


_ensure_deps()

import httpx  # noqa: E402

from agentscope.message import TextBlock, ToolResultState  # noqa: E402
from agentscope.permission import (  # noqa: E402
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import ToolBase, ToolChunk  # noqa: E402

# ==========================================================================
# 环境常量（按需求先用固定值）
# ==========================================================================
BACKEND_ENV_BASE_URL = "https://ubddev.supcon.com:8080"
BACKEND_ENV = "RELEASE_STATE"
STAFF_CODE = "0120250028"
USER_ID = 1093202093071280
USER_NAME = "xiaoyu2"

# 平台配置接口：scope → agent_id / selected_data_model_ids
CFG_URL = (
    BACKEND_ENV_BASE_URL
    + "/msService/public/hgt-chatadmin/algo/queryAgentConfig"
)
# cbb text-to-metrics（test 环境）
CBB_URL = "http://10.48.2.201:10006/text-to-metrics/query"

# 业务域 → 平台场景码（实测：Operations→9，Customer_Assistant→3）
SCOPE_TO_SCENE = {
    "business_operations": "Operations",
    "customer": "Customer_Assistant",
}

_CTX_CACHE: dict[str, dict[str, Any]] = {}


async def _load_scope(scope: str) -> dict[str, Any]:
    """查平台配置，解析该业务域的 agent_id 与数据模型清单（带缓存）。"""
    if scope in _CTX_CACHE:
        return _CTX_CACHE[scope]

    scene = SCOPE_TO_SCENE[scope]
    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        resp = await client.post(
            CFG_URL,
            json={
                "staff_code": STAFF_CODE,
                "backend_env": BACKEND_ENV,
                "scene_agent_config_refs": [scene],
            },
            headers={
                "Content-Type": "application/json",
                "X-UserId": str(USER_ID),
                "X-UserName": USER_NAME,
            },
        )
        resp.raise_for_status()
        body = resp.json()

    agent_ctx = (body.get("data") or {}).get("tool_context", {})
    wa = ((agent_ctx.get(scene) or {}).get("wenshu_agent")) or {}
    if not wa.get("agent_id"):
        raise ValueError(
            f"平台配置里没有 {scene}.wenshu_agent（scope={scope}）",
        )

    ctx = {
        "agent_id": wa["agent_id"],
        "selected_data_model_ids": wa["selected_data_model_ids"],
        "system_prompt": wa.get("disassembly_system_prompt"),
        "user_prompt": wa.get("disassembly_user_prompt"),
    }
    _CTX_CACHE[scope] = ctx
    return ctx


def _format_response(body: dict[str, Any]) -> str:
    """把 cbb 响应整理成模型可读的文本。"""
    if body.get("code") not in (200, None):
        return f"问数失败：{body.get('message') or body.get('detail')}"

    results = body.get("results") or []
    if not results:
        return "问数未返回任何结果。"

    lines: list[str] = []
    for i, item in enumerate(results, 1):
        lines.append(f"[{i}] 子问题：{item.get('question')}")
        if item.get("metric_ql_repr"):
            lines.append(f"    口径：{item['metric_ql_repr']}")
        if item.get("error"):
            lines.append(f"    错误：{item['error']}")
            continue
        data = item.get("data")
        if not data:
            lines.append("    数据：空（该口径下没有命中数据）")
        else:
            lines.append(
                "    数据：" + json.dumps(data, ensure_ascii=False)[:1500],
            )
    return "\n".join(lines)


class WenshuQueryTool(ToolBase):
    """按业务域问数的工具（封装 cbb text-to-metrics）。"""

    name: str = "wenshu_query"
    """The tool name presented to the agent."""

    description: str = """按业务域查询经营/客户数据，返回可读的指标结果。

适用：涉及具体数值、统计口径、趋势、排名、同比环比等需要真实数据的问题。
不适用：纯概念解释、闲聊、需要联网检索的问题。

scope 选择：
- business_operations：经营分析域（营业额、销售额、回款、利润、成本费用、预算执行等）
- customer：客户域（客户画像、销售机会、丢标明细、竞争对手配置、客户历史事故等）
"""
    """The description presented to the agent."""

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "自然语言的问数问题，例如 '2026年每个月的销售额'",
            },
            "scope": {
                "type": "string",
                "enum": sorted(SCOPE_TO_SCENE.keys()),
                "description": "业务域：business_operations（经营）或 customer（客户）",
            },
        },
        "required": ["query", "scope"],
    }
    """The input schema of the tool."""

    is_mcp: bool = False
    is_read_only: bool = True
    is_concurrency_safe: bool = True
    is_external_tool: bool = False
    is_state_injected: bool = False

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        """只读问数，永远允许。"""
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="wenshu_query 是只读查询，允许调用。",
        )

    async def call(self, query: str, scope: str) -> ToolChunk:
        """查询指定业务域的数据。

        Args:
            query (`str`): 自然语言问数问题。
            scope (`str`): 业务域，见 input_schema 的 enum。

        Returns:
            `ToolChunk`: 结果文本。
        """
        if scope not in SCOPE_TO_SCENE:
            return ToolChunk(
                content=[
                    TextBlock(
                        text=f"不支持的 scope：{scope}，可选 "
                        f"{sorted(SCOPE_TO_SCENE)}",
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        try:
            ctx = await _load_scope(scope)
        except Exception as exc:  # noqa: BLE001
            return ToolChunk(
                content=[TextBlock(text=f"读取平台配置失败：{exc}")],
                state=ToolResultState.ERROR,
            )

        payload = {
            "query": query,
            "user_id": USER_ID,
            "user_name": USER_NAME,
            "agent_id": ctx["agent_id"],
            "query_mode": (
                "edit" if BACKEND_ENV == "EDITORIAL_STATE" else "publish"
            ),
            "staff_code": STAFF_CODE,
            "selected_data_model_ids": ctx["selected_data_model_ids"],
            "split_question_system_prompt": ctx["system_prompt"],
            "split_question_user_prompt": ctx["user_prompt"],
        }

        try:
            async with httpx.AsyncClient(
                trust_env=False,
                timeout=180.0,
            ) as client:
                resp = await client.post(
                    CBB_URL,
                    json=payload,
                    headers={
                        "content-type": "application/json",
                        # 裸基址：cbb 自己拼 connector 路径
                        "environment-url": BACKEND_ENV_BASE_URL,
                    },
                )
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ToolChunk(
                content=[TextBlock(text=f"调用问数服务失败：{exc}")],
                state=ToolResultState.ERROR,
            )

        return ToolChunk(content=[TextBlock(text=_format_response(body))])


async def _demo() -> None:
    """本地直调一次工具（不经模型），验证链路。"""
    tool = WenshuQueryTool()
    for scope, q in (
        ("business_operations", "2026年每个月的销售收入"),
        ("customer", "客户总数是多少"),
    ):
        print("=" * 70)
        print(f"scope={scope}  query={q}")
        chunk = await tool.call(query=q, scope=scope)
        for blk in chunk.content:
            print(blk.text[:900])


if __name__ == "__main__":
    asyncio.run(_demo())
