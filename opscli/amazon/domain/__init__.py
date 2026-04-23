"""amazon 领域模型与异常。"""

from opscli.amazon.domain.exceptions import (
    AmazonError,
    BadRemoteJsonError,
    InvalidAsinError,
    RemoteBusinessError,
    RemoteHttpError,
    ScraperDependencyError,
    SubmissionConfigError,
)
from opscli.amazon.domain.models import AmazonCollectResult, AmazonProductSnapshot, AmazonSearchResult

__all__ = [
    "AmazonError",
    "InvalidAsinError",
    "ScraperDependencyError",
    "SubmissionConfigError",
    "RemoteHttpError",
    "RemoteBusinessError",
    "BadRemoteJsonError",
    "AmazonProductSnapshot",
    "AmazonSearchResult",
    "AmazonCollectResult",
]
