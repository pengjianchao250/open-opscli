"""opscli query 模块导出。"""

from opscli.query.services.manager import QueryManager
from opscli.query.transport.client import QueryClient

__all__ = ["QueryClient", "QueryManager"]
