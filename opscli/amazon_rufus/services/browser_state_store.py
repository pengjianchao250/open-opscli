"""Rufus 浏览器状态捕获与本地明文存储服务。"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

from opscli.amazon_rufus.domain.models import SeedRequestRecord
from opscli.amazon_rufus.domain.exceptions import (
    InvalidRufusBrowserStateError,
    InvalidRufusCookieError,
)
from opscli.config import CONFIG_DIR


class RufusBrowserStateStore:
    """保存 Amazon cookies 与 localStorage 的本地明文状态。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        """初始化状态存储目录。

        Args:
            base_dir: 测试或定制存储目录；默认写入 opscli 配置目录。
        """
        self.base_dir = Path(base_dir or (CONFIG_DIR / "amazon-rufus"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        country: str,
        marketplace_origin: str,
        storage_state: dict,
        seed_request: SeedRequestRecord | None = None,
    ) -> Path:
        """明文保存指定国家站点的浏览器状态。"""
        self._validate_storage_state(storage_state)
        record = {
            "country": country.strip().upper(),
            "marketplace_origin": marketplace_origin.rstrip("/"),
            "captured_at": int(time.time() * 1000),
            "storage_state": storage_state,
        }
        if seed_request is not None:
            # streaming 请求材料只写入本地状态，不在 CLI/MCP 输出中展示。
            record.update(
                self._build_seed_record(
                    seed_request,
                    cookies=self._extract_cookies(seed_request, storage_state, marketplace_origin),
                )
            )
        path = self._state_path(country)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return path

    def load(self, country: str) -> dict | None:
        """读取指定国家站点的本地浏览器状态。"""
        path = self._state_path(country)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            self._validate_record(record)
            return record
        except Exception as exc:
            raise InvalidRufusBrowserStateError("本地 Rufus 浏览器状态格式无效") from exc

    def delete(self, country: str) -> bool:
        """删除指定国家站点的本地浏览器状态。"""
        path = self._state_path(country)
        if not path.exists():
            return False
        path.unlink()
        return True

    def build_cookie_header(self, storage_state: dict, marketplace_origin: str) -> str:
        """从 storage_state 中提取目标站点可用的 Cookie header。"""
        self._validate_storage_state(storage_state)
        host = (urlsplit(marketplace_origin).hostname or "").lower()
        pairs: list[str] = []
        for item in storage_state.get("cookies", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "")
            domain = str(item.get("domain") or "").strip().lower()
            if not name or not self._domain_matches_host(domain, host):
                continue
            pairs.append(f"{name}={value}")
        if not pairs:
            raise InvalidRufusCookieError("storage_state 中未找到当前 Amazon 站点 Cookie")
        return "; ".join(pairs)

    def _state_path(self, country: str) -> Path:
        """生成国家维度的明文状态文件路径。"""
        normalized = country.strip().upper() or "UNKNOWN"
        return self.base_dir / f"browser-state-{normalized}.json"

    def _validate_record(self, record: dict) -> None:
        """校验本地状态记录的基础结构。"""
        if not isinstance(record, dict):
            raise InvalidRufusBrowserStateError("本地 Rufus 浏览器状态必须是对象")
        self._validate_storage_state(record.get("storage_state"))

    def _validate_storage_state(self, storage_state: dict) -> None:
        """校验 Playwright storage_state 基础结构。"""
        if not isinstance(storage_state, dict):
            raise InvalidRufusBrowserStateError("storage_state 必须是对象")
        if not isinstance(storage_state.get("cookies"), list):
            raise InvalidRufusBrowserStateError("storage_state.cookies 必须是数组")
        if not isinstance(storage_state.get("origins"), list):
            raise InvalidRufusBrowserStateError("storage_state.origins 必须是数组")

    def _domain_matches_host(self, domain: str, host: str) -> bool:
        """判断 Cookie domain 是否属于当前 Amazon 站点。"""
        normalized = domain.lstrip(".")
        return bool(normalized and host and (host == normalized or host.endswith("." + normalized)))

    def _build_seed_record(self, seed_request: SeedRequestRecord, *, cookies: str) -> dict:
        """构造脱敏的 streaming seed 保存结构。"""
        headers = self._sanitize_headers(seed_request.request_headers)
        payload_template = self._safe_json(seed_request.request_body)
        curl_data = {
            "url": seed_request.request_url,
            "headers": headers,
            "cookies": cookies,
            "payload_template": payload_template,
        }
        return {
            "curl_data": curl_data,
            "streaming_url": seed_request.request_url,
            "headers": headers,
            "payload_template": payload_template,
            "seed_request": {
                "request_url": seed_request.request_url,
                "page_url": seed_request.page_url,
                "tab_id": seed_request.tab_id,
                "asin": seed_request.asin.strip().upper(),
                "country": seed_request.country.strip().upper(),
                "captured_at": seed_request.captured_at,
            },
        }

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """移除不应重复保存或输出的敏感请求头。"""
        blocked = {"cookie", "authorization", "proxy-authorization", "content-length"}
        return {str(k): str(v) for k, v in headers.items() if str(k).lower() not in blocked}

    def _extract_cookies(self, seed_request: SeedRequestRecord, storage_state: dict, marketplace_origin: str) -> str:
        """提取 curl_data.cookies，优先使用捕获请求中的 Cookie header。"""
        for key, value in seed_request.request_headers.items():
            if str(key).lower() == "cookie" and str(value).strip():
                return str(value).strip()
        return self.build_cookie_header(storage_state, marketplace_origin)

    def _safe_json(self, value: str) -> dict:
        """安全解析 seed request body。"""
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
