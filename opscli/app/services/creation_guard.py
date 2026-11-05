"""阻止同一账号、环境和 slug 的创建请求被自动重发。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from opscli.app.domain.exceptions import AppProjectError
from opscli.config import CONFIG_DIR


class CreationGuard:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir if base_dir is not None else CONFIG_DIR / "app" / "creation-guard"

    def claim(
        self,
        scope: str,
        slug: str,
        root: Path,
        *,
        retry_create: bool = False,
    ) -> bool:
        """首次排他登记；人工重试只复用原目录的待核对记录。"""
        target = self._path(scope, slug)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scope": scope,
            "slug": slug,
            "root": str(root),
        }
        try:
            with target.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            existing = self._read(target)
            if existing != payload:
                raise AppProjectError(
                    "APP-CREATE-PENDING-ELSEWHERE",
                    "此账号和环境已有同名应用的创建结果待核对。",
                    fix_hint="请先核对原目标目录及 AppHub 登记结果，不能换目录重发创建请求。",
                    detail={"target_root": existing["root"]},
                ) from None
            if not retry_create:
                raise AppProjectError(
                    "APP-CREATE-RETRY-REQUIRES-USER",
                    "应用创建结果尚未核对，已阻止再次发送创建请求。",
                    fix_hint="先核对 AppHub；仅在用户明确要求重试后，于原目录使用 --retry-create。",
                ) from None
            return False
        return True

    def release(self, scope: str, slug: str, root: Path) -> None:
        target = self._path(scope, slug)
        if target.exists() and self._read(target)["root"] == str(root):
            target.unlink()

    def _path(self, scope: str, slug: str) -> Path:
        digest = hashlib.sha256(
            json.dumps([scope, slug], separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.base_dir / f"{digest}.json"

    @staticmethod
    def _read(target: Path) -> dict[str, str]:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise AppProjectError("APP-CREATE-GUARD-INVALID", "创建保护记录损坏，已阻止再次创建。") from exc
        if not isinstance(payload, dict) or not all(
            isinstance(payload.get(key), str) for key in ("scope", "slug", "root")
        ):
            raise AppProjectError("APP-CREATE-GUARD-INVALID", "创建保护记录无效，已阻止再次创建。")
        return payload
