"""通用工单异常体系。"""


class FeedTaskError(Exception):
    """工单模块基础异常。"""

    code = "FEEDTASK_ERROR"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class FeedTaskAuthError(FeedTaskError):
    """认证失败（未登录 polaris）。"""

    code = "FEEDTASK_AUTH_ERROR"


class FeedTaskParamsError(FeedTaskError):
    """参数错误（缺少必要字段）。"""

    code = "FEEDTASK_PARAMS_ERROR"


class RemoteHttpError(FeedTaskError):
    """HTTP 请求失败。"""

    code = "REMOTE_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "status_code": self.status_code}


class RemoteBusinessError(FeedTaskError):
    """业务逻辑错误（工单创建失败等）。"""

    code = "REMOTE_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        self.business_code = business_code
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "business_code": self.business_code,
        }


class BadRemoteJsonError(FeedTaskError):
    """远端返回非法 JSON。"""

    code = "BAD_REMOTE_JSON"
