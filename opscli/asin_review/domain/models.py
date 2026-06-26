"""asin_review 模块数据模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ASIN 正则：字母数字组合，长度不限（运营系统支持标准 ASIN 和自定义 SKU）
_ASIN_PATTERN = re.compile(r"^[A-Z0-9]+$")


@dataclass(frozen=True)
class ReviewRequest:
    """复盘查询请求。

    Attributes:
        asins: 一个或多个 ASIN（已校验格式）
        date_start: 开始日期，格式 YYYY-MM-DD
        date_end: 结束日期，格式 YYYY-MM-DD
    """

    asins: tuple[str, ...]
    date_start: str
    date_end: str

    def to_dict(self) -> dict:
        return {
            "asins": list(self.asins),
            "date_range": {"start": self.date_start, "end": self.date_end},
        }


@dataclass
class DashboardResult:
    """单个仪表盘的查询结果。

    Attributes:
        key: 仪表盘标识
        status: 结果状态（ok / error / empty）
        dataset_alias: 数据集别名（来自后端）
        rows: 结果行数
        columns: 结果列名列表
        result: 查询结果数据（JSON 列表）
        error: 错误信息（仅 status 为 error 时有值）
    """

    key: str
    status: str = "ok"
    dataset_alias: str = ""
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    result: list[dict] | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "key": self.key,
            "status": self.status,
        }
        if self.dataset_alias:
            d["dataset_alias"] = self.dataset_alias
        if self.status == "error":
            d["error"] = self.error
        else:
            d["rows"] = self.rows
            d["columns"] = self.columns
            d["result"] = self.result
        return d


@dataclass
class ReviewResult:
    """完整的复盘查询结果。

    Attributes:
        success: 是否整体成功
        request: 原始请求快照
        data: 复盘数据（summary 汇总 + daily_data 按日明细 + daily_rows 行数 + columns 列名）
        warnings: 警告信息列表
        errors: 错误信息列表
    """

    success: bool = True
    request: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "request": self.request,
            "data": self.data,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def validate_asin(value: str) -> str:
    """校验并规范化单个 ASIN。

    Args:
        value: 原始输入

    Returns:
        大写后的 ASIN

    Raises:
        InvalidParamsError: 格式不合法
    """
    from opscli.asin_review.domain.exceptions import InvalidParamsError

    cleaned = value.strip().upper()
    if not _ASIN_PATTERN.match(cleaned):
        raise InvalidParamsError(f"ASIN 格式不合法：{value!r}（应为 10 位字母数字）")
    return cleaned


def parse_asin_list(raw: str) -> list[str]:
    """解析逗号分隔的 ASIN 列表。

    Args:
        raw: 逗号分隔的 ASIN 字符串

    Returns:
        校验后的 ASIN 列表

    Raises:
        InvalidParamsError: 输入为空或全部格式不合法
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise InvalidParamsError("ASIN 列表为空，请提供至少一个 ASIN")

    results: list[str] = []
    for p in parts:
        # 跳过无效条目，只收集合法的
        cleaned = p.strip().upper()
        if _ASIN_PATTERN.match(cleaned):
            results.append(cleaned)
        else:
            raise InvalidParamsError(f"ASIN 格式不合法：{p!r}（应为 10 位字母数字）")
    return results
