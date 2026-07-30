"""佰易产品信息查询数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaiyiProductInfoRequest:
    """保存规范化后的公司 SKU 请求快照。"""

    company_sku: str

    def to_dict(self) -> dict:
        """生成远端请求体和 CLI 请求快照。"""
        return {"company_sku": self.company_sku}


@dataclass
class BaiyiProductInfoResult:
    """面向 CLI 消费方的产品信息结果。"""

    request: dict
    found: bool
    data: dict
    success: bool = True

    def to_dict(self) -> dict:
        """按冻结顺序生成稳定成功信封。"""
        return {
            "success": self.success,
            "command": "baiyi product-info",
            "request": self.request,
            "found": self.found,
            "data": self.data,
            "error": None,
        }
