"""卖家精灵跨格式工作表数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SellerSpriteWorksheet:
    """保存一个可同时写入 XLSX 和 JSON 的格式化工作表。

    属性：
        name: 工作表名称。
        columns: 按 XLSX 顺序排列的表头，允许重复名称。
        rows: 与 ``columns`` 按下标对齐的二维数据。
        number_formats: 与 ``columns`` 对齐的 Excel 数字格式；``None`` 表示自动格式。
    """

    name: str
    columns: list[str]
    rows: list[list[Any]]
    number_formats: list[str | None]

    def __post_init__(self) -> None:
        """校验列、行和数字格式能够按下标安全对齐。"""
        if len(self.number_formats) != len(self.columns):
            raise ValueError("卖家精灵工作表 number_formats 必须与 columns 等长")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("卖家精灵工作表 rows 每行必须与 columns 等长")

    def to_dict(self) -> dict[str, Any]:
        """返回保持列顺序、重复表头和数字格式的 JSON 结构。"""
        return {
            "name": self.name,
            "columns": self.columns,
            "number_formats": self.number_formats,
            "row_count": len(self.rows),
            "rows": self.rows,
        }
