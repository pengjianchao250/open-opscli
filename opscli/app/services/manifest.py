"""仓库根目录 app.yaml 的身份读取与原子同步。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding, validate_app_id

_IDENTITY_LINE_RE = re.compile(r"^(?P<key>app_id|name|title)\s*:[^\r\n]*$")
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
        for key in ("app_id", "name", "title"):
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                raise AppProjectError(
                    "APP-MANIFEST-INVALID",
                    f"app.yaml.{key} 必须是字符串。",
                )
        app_id = payload.get("app_id")
        if app_id is not None:
            validate_app_id(app_id, code="APP-MANIFEST-INVALID")
        return payload

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
        if (
            payload.get("app_id") == binding.app_id
            and payload.get("title") == binding.app_name
            and "name" not in payload
        ):
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
            app_id=binding.app_id,
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

    def validate_identity(
        self,
        path: str | Path,
        binding: SiteBinding,
        *,
        required: bool = True,
    ) -> None:
        payload = self.load(path, required=required)
        if payload is None:
            return
        if "name" in payload:
            raise AppProjectError(
                "APP-MANIFEST-LEGACY-NAME",
                "app.yaml 已不再支持顶层 name 字段。",
                fix_hint="执行 opscli app init 完成 app_id 身份迁移，或删除顶层 name。",
            )
        app_id = _optional_text(payload.get("app_id"))
        if app_id is None:
            raise AppProjectError(
                "APP-IDENTITY-MISMATCH",
                "app.yaml 缺少顶层 app_id。",
                fix_hint="执行 opscli app init 写入当前绑定的五位 app_id。",
            )
        if app_id != binding.app_id:
            raise AppProjectError(
                "APP-IDENTITY-MISMATCH",
                "app.yaml.app_id 与当前目录绑定的应用不一致。",
                fix_hint="核对项目目录和 .opscli/app.json；不要把一个应用的源码推送到另一应用。",
            )


def _replace_identity(content: str, *, app_id: str, title: str) -> str:
    newline = "\r\n" if "\r\n" in content else "\n"
    had_trailing_newline = content.endswith(("\n", "\r"))
    lines = content.splitlines()
    replacements = {"app_id": app_id, "title": title}
    seen: dict[str, int] = {"app_id": 0, "name": 0, "title": 0}
    retained_lines: list[str] = []

    for line in lines:
        if line != line.lstrip():
            retained_lines.append(line)
            continue
        match = _IDENTITY_LINE_RE.fullmatch(line)
        if match is None:
            retained_lines.append(line)
            continue
        key = match.group("key")
        seen[key] += 1
        if seen[key] > 1:
            raise AppProjectError(
                "APP-MANIFEST-INVALID",
                f"app.yaml 包含重复的顶层字段：{key}",
            )
        if key == "name":
            continue
        retained_lines.append(f"{key}: {_yaml_string(replacements[key])}")

    lines = retained_lines
    missing = [key for key in ("app_id", "title") if seen[key] == 0]
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
    seen: dict[str, int] = {"app_id": 0, "name": 0, "title": 0}
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
