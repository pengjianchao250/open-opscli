"""auth 领域异常。"""

from opscli.auth.domain.exceptions import (
    AuthError,
    DeviceFlowDeniedError,
    DeviceFlowError,
    DeviceFlowExpiredError,
    NotAuthenticatedError,
    SessionExpiredError,
    SystemNotFoundError,
    TokenFetchError,
)

__all__ = [
    "AuthError",
    "NotAuthenticatedError",
    "SessionExpiredError",
    "TokenFetchError",
    "SystemNotFoundError",
    "DeviceFlowError",
    "DeviceFlowExpiredError",
    "DeviceFlowDeniedError",
]
