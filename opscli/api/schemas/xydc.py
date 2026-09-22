"""西柚 REST API 的稳定请求合同。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opscli.xiyou.contracts import XydcOperation


class XydcRunRequest(BaseModel):
    """执行一个西柚操作；身份和供应商密钥由服务端管理。"""

    model_config = ConfigDict(extra="forbid")

    operation: XydcOperation = Field(description="操作名，见 /api/v1/xydc/scenarios")
    payload: dict[str, Any] = Field(
        description="供应商业务 JSON；字段使用原始名称，例如 country、searchTerms",
        examples=[{"country": "US", "searchTerms": ["bed frame"]}],
    )
