"""卖家精灵 browser-route 验证码 OCR provider。"""

from __future__ import annotations

import importlib
from typing import Protocol

from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


class CaptchaOcrProvider(Protocol):
    """图片验证码 OCR provider 协议。"""

    name: str

    def recognize(self, image_bytes: bytes) -> str:
        """识别图片验证码并返回文本。"""


class DdddOcrCaptchaProvider:
    """基于 ddddocr 的本地图片验证码识别 provider。"""

    name = "ddddocr"

    def __init__(self) -> None:
        self._client = self._create_client()

    def recognize(self, image_bytes: bytes) -> str:
        """调用 ddddocr 识别图片验证码。"""
        try:
            result = self._client.classification(image_bytes)
        except Exception as exc:
            raise SellerSpriteConfigError(f"卖家精灵机器人检测验证码 OCR 调用失败：{type(exc).__name__}") from exc
        return str(result or "").strip()

    def _create_client(self):
        try:
            module = importlib.import_module("ddddocr")
        except ImportError as exc:
            raise SellerSpriteConfigError(
                "已启用卖家精灵验证码 OCR，但未安装 ddddocr；请安装 seller-sprite extra 或执行 pip install ddddocr"
            ) from exc
        try:
            return module.DdddOcr(show_ad=False)
        except TypeError:
            return module.DdddOcr()


def create_captcha_ocr_provider() -> CaptchaOcrProvider:
    """创建默认图片验证码 OCR provider。"""
    return DdddOcrCaptchaProvider()
