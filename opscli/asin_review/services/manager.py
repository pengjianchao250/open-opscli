"""asin_review 模块业务编排层。

负责参数校验、请求构造、远端调用和结果汇总。
"""

from __future__ import annotations

from opscli.asin_review.domain.exceptions import InvalidParamsError
from opscli.asin_review.domain.models import ReviewRequest, ReviewResult, validate_asin
from opscli.asin_review.transport.client import AsinReviewClient


class AsinReviewManager:
    """复盘业务编排层。

    职责：
    1. 校验输入参数（ASIN 格式、日期范围）
    2. 构造请求 payload
    3. 调用远端接口获取复盘数据
    4. 汇总结果
    """

    def __init__(
        self,
        auth_client=None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.client = AsinReviewClient(
            auth_client=auth_client,
            jwt=jwt,
            session_id=session_id,
        )

    def fetch(
        self,
        *,
        asin: str,
        start_date: str,
        end_date: str,
    ) -> ReviewResult:
        """拉取复盘数据。

        Args:
            asin: 单个 ASIN 字符串
            start_date: 开始日期，格式 YYYY-MM-DD
            end_date: 结束日期，格式 YYYY-MM-DD

        Returns:
            ReviewResult 包含 summary 和 daily_data
        """
        # 1. 参数校验
        _validate_date(start_date, "start_date")
        _validate_date(end_date, "end_date")
        if start_date > end_date:
            raise InvalidParamsError(
                f"开始日期 {start_date} 不能晚于结束日期 {end_date}"
            )

        normalized_asin = validate_asin(asin)

        # 2. 构造请求
        request = ReviewRequest(
            asins=(normalized_asin,),
            date_start=start_date,
            date_end=end_date,
        )

        payload = {
            "asin": normalized_asin,
            "start_date": start_date,
            "end_date": end_date,
        }

        # 3. 调用远端接口
        response = self.client.fetch_review(payload)

        # 4. 解析响应
        return _parse_response(request, response)


def _validate_date(value: str, name: str) -> None:
    """校验日期格式为 YYYY-MM-DD。"""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise InvalidParamsError(f"{name} 格式不合法：{value!r}（应为 YYYY-MM-DD）")


def _parse_response(request: ReviewRequest, response: dict) -> ReviewResult:
    """解析后端响应，构造 ReviewResult。

    后端实际返回结构：
    {
        "code": 200,
        "data": {
            "asin": "10043986503",
            "date_range": {"start_date": "...", "end_date": "..."},
            "summary": { "order_qty": 11, "price": 7598.56, ... },  // 汇总指标
            "daily_data": [ { "date_id": "...", "orders": 3, ... }, ... ]  // 按日明细
        }
    }
    """
    result = ReviewResult(request=request.to_dict())

    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        result.success = False
        result.errors.append("后端返回数据结构异常：缺少 data 字段或格式不正确")
        return result

    # 直接提取 summary 和 daily_data，透传后端结构
    summary = data.get("summary")
    daily_data = data.get("daily_data")

    if not isinstance(summary, dict):
        result.warnings.append("后端返回缺少 summary 汇总数据")

    if not isinstance(daily_data, list):
        result.warnings.append("后端返回缺少 daily_data 按日明细数据")

    # 将解析后的数据存入 result.data
    result.data = {
        "summary": summary,
        "daily_data": daily_data,
        "daily_rows": len(daily_data) if isinstance(daily_data, list) else 0,
    }
    if isinstance(daily_data, list) and daily_data:
        result.data["columns"] = list(daily_data[0].keys())

    result.success = True
    return result
