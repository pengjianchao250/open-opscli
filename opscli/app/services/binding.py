"""站点本地绑定文件读写。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.app.domain.constants import BINDING_RELATIVE_PATH
from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding


class BindingStore:
    def prepare_root(self, path: str | Path) -> Path:
        root = Path(path).expanduser().resolve()
        if root.exists() and not root.is_dir():
            raise AppProjectError("APP-PATH-INVALID", f"绑定路径不是目录：{root}")
        return root

    def save(self, path: str | Path, binding: SiteBinding) -> Path:
        root = self.prepare_root(path)
        root.mkdir(parents=True, exist_ok=True)
        target = root / BINDING_RELATIVE_PATH
        if target.exists():
            current = self.load(root)
            is_v1_migration = (
                current.schema_version == 1
                and binding.schema_version == 2
                and current.slug == binding.slug
            )
            if current.app_id != binding.app_id and not is_v1_migration:
                raise AppProjectError(
                    "APP-ALREADY-BOUND",
                    f"目录已绑定其他站点：{current.site_name} ({current.app_id})",
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(binding.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(target)
        return target

    def load(self, path: str | Path) -> SiteBinding:
        root = self.prepare_root(path)
        target = root / BINDING_RELATIVE_PATH
        if not target.is_file():
            raise AppProjectError(
                "APP-NOT-BOUND",
                f"未找到站点绑定文件：{target}",
                fix_hint="请先执行 opscli app create。",
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppProjectError("APP-BINDING-INVALID", f"站点绑定文件读取失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise AppProjectError("APP-BINDING-INVALID", "站点绑定文件顶层必须是 JSON 对象。")
        return SiteBinding.from_dict(payload)

    def is_bound(self, path: str | Path) -> bool:
        root = self.prepare_root(path)
        return (root / BINDING_RELATIVE_PATH).is_file()

    def has_source_files(self, path: str | Path) -> bool:
        root = self.prepare_root(path)
        if not root.exists():
            return False
        return any(item.name not in {".git", ".opscli"} for item in root.iterdir())
