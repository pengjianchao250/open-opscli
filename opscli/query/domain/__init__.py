"""query 领域模型与异常。"""

from opscli.query.domain.exceptions import (
    BadRemoteJsonError,
    DatasetNotFoundError,
    InvalidPayloadError,
    QueryError,
    QueryMetadataNotReadyError,
    RemoteBusinessError,
    RemoteHttpError,
)
from opscli.query.domain.models import QueryMetadataResult

__all__ = [
    "QueryError",
    "InvalidPayloadError",
    "DatasetNotFoundError",
    "QueryMetadataNotReadyError",
    "RemoteHttpError",
    "RemoteBusinessError",
    "BadRemoteJsonError",
    "QueryMetadataResult",
]
