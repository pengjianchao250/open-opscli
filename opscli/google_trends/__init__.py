"""Google Trends 数据获取模块。"""

from opscli.google_trends.domain.models import (
    GoogleTrendsExportResult,
    GoogleTrendsScenarioRequest,
    GoogleTrendsScenarioResult,
)
from opscli.google_trends.services import GoogleTrendsApiManager

__all__ = [
    "GoogleTrendsApiManager",
    "GoogleTrendsExportResult",
    "GoogleTrendsScenarioRequest",
    "GoogleTrendsScenarioResult",
]
