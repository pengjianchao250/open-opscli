"""Amazon 模块对外导出。"""

from opscli.amazon.domain.models import AmazonCollectResult, AmazonProductSnapshot, AmazonSearchResult
from opscli.amazon.services.manager import AmazonManager
from opscli.amazon.transport.client import AmazonOpsClient

__all__ = [
    "AmazonManager",
    "AmazonOpsClient",
    "AmazonProductSnapshot",
    "AmazonSearchResult",
    "AmazonCollectResult",
]
