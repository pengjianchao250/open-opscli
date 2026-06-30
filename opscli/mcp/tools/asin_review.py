"""asin_review 工具模块。

将 opscli asin-review 子模块的核心能力暴露为 MCP 工具：
- asin_review_fetch  — 拉取指定 ASIN 在日期范围内的复盘数据

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from .helpers import _err, _ok, _parse_json_arg


async def asin_review_fetch(
    asin: str,
    start_date: str,
    end_date: str,
    jwt: str | None = None,
    session_id: str | None = None,
) -> dict:
    """拉取指定 ASIN 在日期范围内的复盘数据。

    通过运营系统 asin-review 接口获取多维度业务数据（销量、广告、库存等），
    返回结构化结果供 AI Agent 消费生成复盘报告。

    Args:
        asin: Amazon ASIN，如 "10043986503"
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD
        jwt: 可选外部 JWT（MCP 无状态模式）
        session_id: 可选外部 session_id（MCP 无状态模式）

    Returns:
        成功: {"success": true, "data": {"request": {...}, "data": {...}, "warnings": [...], "errors": [...]}}
        失败: {"success": false, "error": {...}}
    """
    call_params = {"asin": asin, "start_date": start_date, "end_date": end_date}
    try:
        from .helpers import _get_auth_pair
        from opscli.asin_review.services.manager import AsinReviewManager

        # 获取认证凭证
        _, jwt_val = _get_auth_pair("ops", provided_session=session_id, provided_jwt=jwt)

        manager = AsinReviewManager(jwt=jwt_val, session_id=session_id)
        result = manager.fetch(
            asin=asin,
            start_date=start_date,
            end_date=end_date,
        )
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc, tool="asin_review_fetch", call_params=call_params)


# ── 工具注册 ──────────────────────────────────────────────

_ALL_TOOLS = [asin_review_fetch]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 asin_review_* 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
