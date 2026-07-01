"""Scrape.do 领域异常。"""

from __future__ import annotations


class ScrapeDoError(Exception):
    """Scrape.do 模块基础异常。"""


class ScrapeDoConfigError(ScrapeDoError):
    """Scrape.do 配置或参数错误。"""


class ScrapeDoApiError(ScrapeDoError):
    """Scrape.do API 调用错误。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        response_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response_excerpt = response_excerpt
