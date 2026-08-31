"""第三方 API 凭据池异常。"""


class ApiCredentialError(Exception):
    """API 凭据池业务异常基类。"""


class ApiCredentialConfigError(ApiCredentialError):
    """API 凭据池部署配置错误。"""


class ApiCredentialUnavailableError(ApiCredentialError):
    """指定 Provider 当前没有可用账号。"""
