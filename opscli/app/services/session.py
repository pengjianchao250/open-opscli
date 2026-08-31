"""发布续订句柄的安全持久化。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import PublishSession
from opscli.config import CONFIG_DIR


class PublishSessionStore:
    """按 slug 原子读写 publish-session.json。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or CONFIG_DIR).expanduser().resolve()

    def path_for(self, slug: str) -> Path:
        """返回指定应用句柄路径。"""
        return self.base_dir / "apps" / slug / "publish-session.json"

    def save(self, session: PublishSession) -> None:
        """原子保存句柄，拒绝覆盖符号链接。"""
        path = self.path_for(session.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise AppProjectError("APP-SESSION-INVALID", "发布句柄不能是符号链接。")
        fd, temp_name = tempfile.mkstemp(prefix=".publish-session-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(session.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load(self, slug: str) -> PublishSession:
        """读取句柄；损坏时明确要求重新发布而不猜测 release id。"""
        path = self.path_for(slug)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PublishSession(
                release_id=int(data["release_id"]),
                last_seq=int(data["last_seq"]),
                slug=str(data["slug"]),
                commit_sha=str(data["commit_sha"]),
                started_at=str(data["started_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AppProjectError(
                "APP-SESSION-INVALID",
                f"无法读取发布续订句柄: {path}",
                fix_hint="删除损坏句柄后重新执行 publish；不要猜测 release id。",
            ) from exc

    def clear(self, slug: str) -> None:
        """删除终态发布句柄。"""
        path = self.path_for(slug)
        if path.exists() and not path.is_symlink():
            path.unlink()

