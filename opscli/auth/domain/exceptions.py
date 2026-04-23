"""auth 异常定义。"""


class AuthError(Exception):
    """基础认证异常"""


class NotAuthenticatedError(AuthError):
    """未登录或 session 已失效"""


class SessionExpiredError(AuthError):
    """session_id 已过期"""


class TokenFetchError(AuthError):
    """从业务系统获取 JWT 失败"""


class SystemNotFoundError(AuthError):
    """系统别名未注册"""


class DeviceFlowError(AuthError):
    """Device Flow 授权流程异常"""


class DeviceFlowExpiredError(DeviceFlowError):
    """设备码已超时"""


class DeviceFlowDeniedError(DeviceFlowError):
    """用户拒绝授权"""
