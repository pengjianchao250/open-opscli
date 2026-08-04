"""Collector 采集结果沉淀模块。"""

from opscli.collector_mcp.storage.models import CollectionSubmission
from opscli.collector_mcp.storage.outbox import CollectionOutbox

__all__ = ["CollectionOutbox", "CollectionSubmission"]
