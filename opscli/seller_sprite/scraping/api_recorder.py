"""卖家精灵接口响应记录器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class SellerSpriteApiRecorder:
    """记录 Playwright 捕获到的 JSON 响应。"""

    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}

    async def capture_json_response(self, response, *, section: str, url_keyword: str) -> None:
        """按 URL 关键词捕获 JSON 响应。

        Args:
            response: Playwright response 对象。
            section: 响应所属业务分区，例如 frequency 或 keyword_mining。
            url_keyword: URL 中用于匹配接口的关键词。
        """
        parsed_url = urlparse(response.url)
        if "sellersprite.com" not in parsed_url.netloc.lower() or url_keyword not in response.url:
            return
        try:
            payload = await response.json()
        except Exception:
            return
        if not self._matches_section_payload(section, payload):
            return
        self.responses[section] = {
            "url": response.url,
            "status": response.status,
            "payload": payload,
        }

    def _matches_section_payload(self, section: str, payload: Any) -> bool:
        """按响应结构识别目标接口，避免误收页面辅助接口。"""
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        if section in {"frequency", "reverse_frequency"}:
            return isinstance(data, list) and any(
                isinstance(item, dict) and "frequency" in item and "keyword" in item for item in data
            )
        if section == "keyword_mining":
            return isinstance(data, dict) and isinstance(data.get("items"), list)
        if section == "keyword_reverse":
            return isinstance(data, dict) and isinstance(data.get("items"), list) and "asin" in data
        if section == "reverse_monthly":
            return isinstance(data, dict) and "monthlyDto" in data and "variations" in data
        if section == "reverse_stats":
            return isinstance(data, dict) and "statDto" in data and "asin" in data
        return False

    def get_payload(self, section: str) -> dict[str, Any] | None:
        """读取指定分区的响应 payload。"""
        item = self.responses.get(section)
        if not item:
            return None
        payload = item.get("payload")
        return payload if isinstance(payload, dict) else None

    def save_all(self, target_dir: Path) -> dict[str, str]:
        """将已捕获响应写入目录，返回文件索引。"""
        target_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        for section, item in self.responses.items():
            path = target_dir / f"{section}.json"
            path.write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            files[f"{section}_response"] = str(path)
        return files
