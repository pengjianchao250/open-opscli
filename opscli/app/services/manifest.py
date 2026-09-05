"""仓库根目录 app.yaml 的身份读取与原子同步。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding, slugify_site_name

_IDENTITY_LINE_RE = re.compile(r"^(?P<key>name|title)\s*:[^\r\n]*$")
_API_VERSION_LINE_RE = re.compile(r"^apiVersion\s*:[^\r\n]*$")


class AppManifestStore:
    def load(
        self,
        path: str | Path,
        *,
        required: bool = False,
    ) -> dict[str, Any] | None:
        root = Path(path).expanduser().resolve()
        target = root / "app.yaml"
        if not target.is_file():
            if required:
                raise AppProjectError(
                    "APP-MANIFEST-NOT-FOUND",
                    f"未找到 AppHub 应用声明：{target}",
                    fix_hint="请确认项目根目录包含模板提供的 app.yaml。",
                )
            return None
        try:
            content = target.read_text(encoding="utf-8")
            _validate_identity_lines(content)
            payload = yaml.safe_load(content)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                f"读取 app.yaml 失败：{exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                "app.yaml 顶层必须是 YAML 对象。",
            )
        for key in ("name", "title"):
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                raise AppProjectError(
                    "APP-MANIFEST-INVALID",
                    f"app.yaml.{key} 必须是字符串。",
                )
        return payload

    def discover_identity(self, path: str | Path) -> tuple[str | None, str]:
        root = Path(path).expanduser().resolve()
        payload = self.load(root)
        if payload is None:
            return root.name or None, slugify_site_name(root.name)
        name = _optional_text(payload.get("name"))
        title = _optional_text(payload.get("title"))
        app_name = title or name or root.name
        return app_name, slugify_site_name(name or root.name)

    def sync_identity(
        self,
        path: str | Path,
        binding: SiteBinding,
        *,
        required: bool = False,
    ) -> bool:
        root = Path(path).expanduser().resolve()
        target = root / "app.yaml"
        payload = self.load(root, required=required)
        if payload is None:
            return False
        if payload.get("name") == binding.slug and payload.get("title") == binding.app_name:
            return False

        try:
            original = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                f"读取 app.yaml 失败：{exc}",
            ) from exc
        updated = _replace_identity(
            original,
            name=binding.slug,
            title=binding.app_name,
        )
        temporary = target.with_suffix(".yaml.tmp")
        try:
            temporary.write_text(updated, encoding="utf-8", newline="")
            temporary.replace(target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                f"写入 app.yaml 失败：{exc}",
            ) from exc
        return True


def _replace_identity(content: str, *, name: str, title: str) -> str:
    newline = "\r\n" if "\r\n" in content else "\n"
    had_trailing_newline = content.endswith(("\n", "\r"))
    lines = content.splitlines()
    replacements = {"name": name, "title": title}
    seen: dict[str, int] = {"name": 0, "title": 0}

    for index, line in enumerate(lines):
        if line != line.lstrip():
            continue
        match = _IDENTITY_LINE_RE.fullmatch(line)
        if match is None:
            continue
        key = match.group("key")
        seen[key] += 1
        if seen[key] > 1:
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                f"app.yaml 包含重复的顶层字段：{key}",
            )
        lines[index] = f"{key}: {_yaml_string(replacements[key])}"

    missing = [key for key in ("name", "title") if seen[key] == 0]
    if missing:
        insert_at = 0
        for index, line in enumerate(lines):
            if line == line.lstrip() and _API_VERSION_LINE_RE.fullmatch(line):
                insert_at = index + 1
                break
        lines[insert_at:insert_at] = [
            f"{key}: {_yaml_string(replacements[key])}" for key in missing
        ]

    result = newline.join(lines)
    if had_trailing_newline or not result:
        result += newline
    return result


def _validate_identity_lines(content: str) -> None:
    seen: dict[str, int] = {"name": 0, "title": 0}
    for line in content.splitlines():
        if line != line.lstrip():
            continue
        match = _IDENTITY_LINE_RE.fullmatch(line)
        if match is None:
            continue
        key = match.group("key")
        seen[key] += 1
        if seen[key] > 1:
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                f"app.yaml 包含重复的顶层字段：{key}",
            )


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
