"""佰易产品信息业务编排层。"""

from __future__ import annotations

from opscli.baiyi.domain.exceptions import (
    BaiyiProductInfoBadJsonError,
    InvalidBaiyiCompanySkuError,
)
from opscli.baiyi.domain.models import (
    BaiyiProductInfoRequest,
    BaiyiProductInfoResult,
)
from opscli.baiyi.transport.client import BaiyiProductInfoClient


class BaiyiProductInfoManager:
    """佰易产品信息业务编排入口。"""

    def __init__(self, client: BaiyiProductInfoClient | None = None) -> None:
        """保存可注入客户端，测试时可避免访问真实网络和凭证。"""
        self.client = client or BaiyiProductInfoClient()

    def fetch(self, company_sku: str) -> BaiyiProductInfoResult:
        """校验公司 SKU，并返回保留后端原始字段的产品信息结果。"""
        normalized_sku = company_sku.strip()
        if not normalized_sku:
            raise InvalidBaiyiCompanySkuError("公司 SKU 不能为空")
        if len(normalized_sku) > 128:
            raise InvalidBaiyiCompanySkuError("公司 SKU 长度不能超过 128 个字符")

        request = BaiyiProductInfoRequest(company_sku=normalized_sku)
        response = self.client.fetch_product_info(request.to_dict())
        data = response.get("data")
        if not isinstance(data, dict):
            raise BaiyiProductInfoBadJsonError("远端 data 不是 JSON 对象")

        # 后端以空映射表达未找到；其他明细数组即使有数据也不能改变该语义。
        return BaiyiProductInfoResult(
            request=request.to_dict(),
            found=data.get("binding_sku_info") is not None,
            data=data,
        )
