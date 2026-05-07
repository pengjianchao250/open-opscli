"""Amazon Rufus 异常定义。"""

from __future__ import annotations


class RufusError(Exception):
    """Rufus 模块基础异常。"""

    code = "RUFUS_ERROR"

    def to_dict(self) -> dict:
        """转换为稳定 JSON 错误结构。"""
        return {"code": self.code, "message": str(self)}


class ChromeCdpUnavailableError(RufusError):
    """Chrome CDP 不可用。"""

    code = "CHROME_CDP_UNAVAILABLE"


class SeedRequestNotCapturedError(RufusError):
    """未捕获 Rufus seed request。"""

    code = "SEED_REQUEST_NOT_CAPTURED"


class QuestionBankNotReadyError(RufusError):
    """题库尚未安装或升级。"""

    code = "QUESTION_BANK_NOT_READY"


class RufusReplayError(RufusError):
    """Rufus 重放失败。"""

    code = "RUFUS_REPLAY_ERROR"


class UnsupportedMarketplaceError(RufusError):
    """不支持的国家站点。"""

    code = "UNSUPPORTED_MARKETPLACE"
