"""MCP 宿主共享的采集结果沉淀模块。"""

from opscli.shared.collection_storage.models import CollectionSubmission
from opscli.shared.collection_storage.runtime import (
    CollectionStorageRuntime,
    build_collection_storage_runtime,
    collection_storage_lifespan,
)

__all__ = [
    "CollectionStorageRuntime",
    "CollectionSubmission",
    "build_collection_storage_runtime",
    "collection_storage_lifespan",
]
