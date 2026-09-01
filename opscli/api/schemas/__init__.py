"""REST 请求合同（Pydantic Schema），按业务域拆分：query / keepa。"""

from opscli.api.schemas.keepa import KeepaRunRequest
from opscli.api.schemas.query import (
    ChartRunRequest,
    QueryBuildRequest,
    QueryFlowOrderBy,
    QueryFlowRequest,
    QueryIntentMatchRequest,
    QueryPlanRequest,
    QueryRunRequest,
    QuerySimpleRequest,
    SimpleQuerySpec,
)

__all__ = [
    "ChartRunRequest",
    "KeepaRunRequest",
    "QueryBuildRequest",
    "QueryFlowOrderBy",
    "QueryFlowRequest",
    "QueryIntentMatchRequest",
    "QueryPlanRequest",
    "QueryRunRequest",
    "QuerySimpleRequest",
    "SimpleQuerySpec",
]
