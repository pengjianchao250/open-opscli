"""Rufus 远程授权偏好存储服务。"""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR


class RemoteConsentStore:
    """读取和保存 Amazon Rufus 远程授权偏好。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        """初始化授权偏好存储目录。"""
        self.base_dir = Path(base_dir or (CONFIG_DIR / "amazon-rufus"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def status(self, country: str) -> dict:
        """读取指定国家站点的远程授权偏好摘要。"""
        normalized_country = country.strip().upper()
        path = self._path()
        if not path.exists():
            return self._empty_status(normalized_country, "unknown")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_status(normalized_country, "invalid")
        if not isinstance(payload, dict):
            return self._empty_status(normalized_country, "invalid")
        if str(payload.get("country") or "").strip().upper() != normalized_country:
            return self._empty_status(normalized_country, "unknown")
        allowed = payload.get("use_remote_authorization")
        if not isinstance(allowed, bool):
            return self._empty_status(normalized_country, "invalid")
        return {
            "country": normalized_country,
            "status": "allowed" if allowed else "denied",
            "use_remote_authorization": allowed,
            "updated_at": str(payload.get("updated_at") or ""),
            "source": str(payload.get("source") or ""),
        }

    def save(self, *, country: str, allowed: bool, source: str = "opscli") -> dict:
        """保存指定国家站点的远程授权偏好。"""
        normalized_country = country.strip().upper()
        payload = {
            "use_remote_authorization": bool(allowed),
            "country": normalized_country,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": source,
        }
        path = self._path()
        # 授权偏好不是登录态，但仍写成用户私有文件，避免被其他本机用户误读。
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return self.status(normalized_country)

    def _path(self) -> Path:
        """返回授权偏好文件路径。"""
        return self.base_dir / "remote-consent.json"

    def _empty_status(self, country: str, status: str) -> dict[str, Any]:
        """构造无敏感字段的空状态。"""
        return {
            "country": country,
            "status": status,
            "use_remote_authorization": None,
            "updated_at": None,
            "source": None,
        }
