"""卖家精灵验证码检测与 provider 预留。"""

from __future__ import annotations

from pathlib import Path


class SellerSpriteCaptchaProvider:
    """图形验证码识别 provider 协议预留。"""

    def solve_image(self, image_path: Path) -> str:
        """识别图形验证码。

        当前一期不自动识别验证码，后续接入超级鹰时实现该方法。
        """
        raise NotImplementedError("当前版本未启用自动验证码识别")


class SellerSpriteCaptchaDetector:
    """检测卖家精灵页面是否出现验证码。"""

    DEFAULT_SELECTORS = [
        "input[name*='captcha']",
        "img[src*='captcha']",
        ".captcha",
        "#captcha",
    ]

    async def detect(self, page) -> bool:
        """检查页面中是否存在常见验证码元素。"""
        for selector in self.DEFAULT_SELECTORS:
            try:
                handle = await page.query_selector(selector)
            except Exception:
                handle = None
            if handle is not None:
                return True
        return False
