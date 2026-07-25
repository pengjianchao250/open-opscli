"""Rufus 浏览器状态捕获与平台 Cookie 接口 content 存储服务。"""

from __future__ import annotations

import json
import shlex
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

from opscli.amazon_rufus.domain.models import SeedRequestRecord
from opscli.amazon_rufus.domain.exceptions import (
    InvalidRufusBrowserStateError,
    InvalidRufusCookieError,
    RufusRemoteBusinessError,
)
from opscli.config import CONFIG_DIR

DEFAULT_PLATFORM_COOKIE = "amazon"


class RufusBrowserStateStore:
    """保存 Amazon cookies、localStorage 与 Rufus 请求材料。"""

    def __init__(
        self,
        base_dir: Path | None = None,
        platform_cookie_client=None,
        platform: str = DEFAULT_PLATFORM_COOKIE,
    ) -> None:
        """初始化状态存储。

        Args:
            base_dir: 测试或显式本地 fallback 目录。
            platform_cookie_client: 提供线上平台 Cookie 接口 content 读写的 client。
        """
        self.base_dir = Path(base_dir or (CONFIG_DIR / "amazon-rufus"))
        self.platform_cookie_client = platform_cookie_client
        self.platform = platform.strip() or DEFAULT_PLATFORM_COOKIE
        if self.platform_cookie_client is None:
            self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        country: str,
        marketplace_origin: str,
        storage_state: dict,
        seed_request: SeedRequestRecord | None = None,
    ) -> Path:
        """保存指定国家站点的浏览器状态。"""
        self._validate_storage_state(storage_state)
        record = {
            "country": country.strip().upper(),
            "marketplace_origin": marketplace_origin.rstrip("/"),
            "captured_at": int(time.time() * 1000),
            "storage_state": storage_state,
        }
        if seed_request is not None:
            # streaming 请求材料只写入状态 content，不在 CLI/MCP 输出中展示。
            record.update(
                self._build_seed_record(
                    seed_request,
                    cookies=self._extract_cookies(seed_request, storage_state, marketplace_origin),
                )
            )
        path = self._state_path(country)
        if self.platform_cookie_client is not None:
            remote_content = str(record.get("curl") or "").strip()
            self.platform_cookie_client.save_platform_cookie(
                platform=self.platform,
                country=record["country"],
                content=remote_content or json.dumps(record, ensure_ascii=False),
            )
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return path

    def load(self, country: str) -> dict | None:
        """读取指定国家站点的浏览器状态。"""
        if self.platform_cookie_client is not None:
            return self._load_remote(country)
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
        """清除指定国家站点的浏览器状态。"""
        if self.platform_cookie_client is not None:
            self._clear_remote(country)
            return True
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
        """生成显式本地 fallback 的国家维度状态文件路径。"""
        normalized = country.strip().upper() or "UNKNOWN"
        return self.base_dir / f"browser-state-{normalized}.json"

    def _load_remote(self, country: str) -> dict | None:
        """从平台 Cookie 接口 content 中读取远端 Rufus 状态。"""
        normalized_country = country.strip().upper()
        try:
            payload = self.platform_cookie_client.get_platform_cookie(platform=self.platform)
        except RufusRemoteBusinessError as exc:
            if exc.business_code == 404 or str(exc.business_code) == "404":
                return None
            raise
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        data_country = str(data.get("country") or "").strip().upper()
        if data_country and data_country != normalized_country:
            return None
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        normalized_content = content.strip()
        if normalized_content.lower().startswith("curl "):
            record = {
                "country": normalized_country,
                "version": 2,
                "curl": normalized_content,
            }
            self._validate_record(record)
            return record
        try:
            record = json.loads(normalized_content)
            if str(record.get("country") or "").strip().upper() != normalized_country:
                return None
            self._validate_record(record)
            return record
        except Exception as exc:
            raise InvalidRufusBrowserStateError("远端 Rufus 浏览器状态 content 格式无效") from exc

    def _clear_remote(self, country: str) -> None:
        """用空状态覆盖远端 content，避免继续复用旧登录态。"""
        normalized_country = country.strip().upper() or "UNKNOWN"
        record = {
            "country": normalized_country,
            "marketplace_origin": "",
            "captured_at": int(time.time() * 1000),
            "storage_state": {"cookies": [], "origins": []},
        }
        self.platform_cookie_client.save_platform_cookie(
            platform=self.platform,
            country=normalized_country,
            content=json.dumps(record, ensure_ascii=False),
        )

    def _validate_record(self, record: dict) -> None:
        """校验本地状态记录的基础结构。"""
        if not isinstance(record, dict):
            raise InvalidRufusBrowserStateError("本地 Rufus 浏览器状态必须是对象")
        storage_state = record.get("storage_state")
        if isinstance(storage_state, dict):
            self._validate_storage_state(storage_state)
            return
        if isinstance(record.get("curl"), str) and str(record.get("curl")).strip():
            return
        raise InvalidRufusBrowserStateError("本地 Rufus 浏览器状态缺少 storage_state 或 curl")

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
        return {
            "version": 2,
            "curl": self._build_curl_command(
                url=seed_request.request_url,
                headers=headers,
                cookies=cookies,
                payload_template=payload_template,
            ),
            "seed_request": {
                "request_url": seed_request.request_url,
                "page_url": seed_request.page_url,
                "tab_id": seed_request.tab_id,
                "asin": seed_request.asin.strip().upper(),
                "country": seed_request.country.strip().upper(),
                "captured_at": seed_request.captured_at,
            },
        }

    def _build_curl_command(
        self,
        *,
        url: str,
        headers: dict[str, str],
        cookies: str,
        payload_template: dict,
    ) -> str:
        """构造浏览器 Copy-as-cURL 风格的单行 cURL 命令。"""
        parts = ["curl", shlex.quote(str(url or "").strip())]
        for key, value in headers.items():
            parts.extend(["-H", shlex.quote(f"{key}: {value}")])
        if str(cookies or "").strip():
            parts.extend(["-H", shlex.quote(f"cookie: {str(cookies).strip()}")])
        payload = json.dumps(payload_template if isinstance(payload_template, dict) else {}, ensure_ascii=False, separators=(",", ":"))
        parts.extend(["--data-raw", shlex.quote(payload)])
        return " ".join(parts)

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """移除不应重复保存或输出的敏感请求头。"""
        blocked = {"cookie", "authorization", "proxy-authorization", "content-length"}
        return {str(k): str(v) for k, v in headers.items() if str(k).lower() not in blocked}

    def _extract_cookies(self, seed_request: SeedRequestRecord, storage_state: dict, marketplace_origin: str) -> str:
        """提取 cURL 命令 Cookie，优先使用捕获请求中的 Cookie header。"""
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
