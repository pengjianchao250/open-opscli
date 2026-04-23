"""amazon exceptions 兼容导出。"""

from opscli.amazon.domain.exceptions import (
    AmazonError,
    BadRemoteJsonError,
    InvalidAsinError,
    RemoteBusinessError,
    RemoteHttpError,
    ScraperDependencyError,
    SubmissionConfigError,
)

__all__ = [
    "AmazonError",
    "InvalidAsinError",
    "ScraperDependencyError",
    "SubmissionConfigError",
    "RemoteHttpError",
    "RemoteBusinessError",
    "BadRemoteJsonError",
]
