"""卖家精灵页面归档工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SellerSpriteArchiver:
    """保存截图、HTML、Markdown 和 JSON 文件。"""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    async def archive_page(self, page, *, section: str) -> dict[str, str]:
        """归档当前页面状态。

        Args:
            page: Playwright page 对象。
            section: 归档分区名称。
        """
        section_dir = self.root_dir / section
        section_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = section_dir / "screenshot.png"
        html_path = section_dir / "page.html"
        markdown_path = section_dir / "page.md"

        await page.screenshot(path=str(screenshot_path), full_page=True)
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        markdown_path.write_text(self.html_to_markdown(html), encoding="utf-8")

        return {
            f"{section}_screenshot": str(screenshot_path),
            f"{section}_html": str(html_path),
            f"{section}_markdown": str(markdown_path),
        }

    async def archive_locator(self, locator, *, section: str) -> dict[str, str]:
        """归档指定页面元素。"""
        section_dir = self.root_dir / section
        section_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = section_dir / "screenshot.png"
        html_path = section_dir / "page.html"
        markdown_path = section_dir / "page.md"

        await locator.wait_for(state="visible", timeout=10000)
        await locator.screenshot(path=str(screenshot_path))
        html = await locator.evaluate("element => element.outerHTML")
        html_path.write_text(html, encoding="utf-8")
        markdown_path.write_text(self.html_to_markdown(html), encoding="utf-8")

        return {
            f"{section}_screenshot": str(screenshot_path),
            f"{section}_html": str(html_path),
            f"{section}_markdown": str(markdown_path),
        }

    def html_to_markdown(self, html: str) -> str:
        """将 HTML 转为 Markdown。"""
        from bs4 import BeautifulSoup
        from markdownify import markdownify

        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "svg", "noscript", "meta", "link"]):
            node.decompose()
        for node in soup.find_all(True):
            if node.attrs is None:
                continue
            style = (node.get("style") or "").replace(" ", "").lower()
            if node.has_attr("hidden") or node.get("aria-hidden") == "true":
                node.decompose()
            elif "display:none" in style or "visibility:hidden" in style:
                node.decompose()
        for node in soup.select("img[src^='data:'], source[src^='data:']"):
            node.decompose()

        return markdownify(
            str(soup.body or soup),
            heading_style="ATX",
            bullets="-",
            wrap=False,
            table_infer_header=True,
        )

    def save_json(self, *, section: str, filename: str, payload: dict[str, Any]) -> str:
        """保存 JSON 文件并返回路径。"""
        section_dir = self.root_dir / section
        section_dir.mkdir(parents=True, exist_ok=True)
        path = section_dir / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)
