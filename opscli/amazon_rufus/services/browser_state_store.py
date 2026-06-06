"""Rufus 浏览器状态捕获与加密存储服务。"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

from opscli.amazon_rufus.domain.exceptions import (
    InvalidRufusBrowserStateError,
    InvalidRufusCookieError,
)
from opscli.auth.storage.crypto import Crypto
from opscli.config import CONFIG_DIR


class RufusBrowserStateStore:
    """保存 Amazon cookies 与 localStorage 的本地加密状态。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        """初始化状态存储目录。

        Args:
            base_dir: 测试或定制存储目录；默认写入 opscli 配置目录。
        """
        self.base_dir = Path(base_dir or (CONFIG_DIR / "amazon-rufus"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._crypto = Crypto(self.base_dir / ".browser-state-key")

    def save(self, *, country: str, marketplace_origin: str, storage_state: dict) -> Path:
        """加密保存指定国家站点的浏览器状态。"""
        self._validate_storage_state(storage_state)
        record = {
            "country": country.strip().upper(),
            "marketplace_origin": marketplace_origin.rstrip("/"),
            "captured_at": int(time.time() * 1000),
            "storage_state": storage_state,
        }
        path = self._state_path(country)
        path.write_bytes(self._crypto.encrypt(json.dumps(record, ensure_ascii=False)))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return path

    def load(self, country: str) -> dict | None:
        """读取指定国家站点的本地浏览器状态。"""
        path = self._state_path(country)
        if not path.exists():
            return None
        try:
            return json.loads(self._crypto.decrypt(path.read_bytes()))
        except Exception as exc:
            raise InvalidRufusBrowserStateError("本地 Rufus 浏览器状态无法解密或格式无效") from exc

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
        """生成国家维度的加密状态文件路径。"""
        normalized = country.strip().upper() or "UNKNOWN"
        return self.base_dir / f"browser-state-{normalized}.bin"

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
