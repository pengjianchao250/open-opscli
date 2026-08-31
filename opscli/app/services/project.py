"""项目识别与 app.yaml 同构校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from opscli.app.domain.constants import (
    APP_YAML_FILENAME,
    CODEX_SITE_MARKERS,
    DATASET_PATTERN,
    RESERVED_SLUGS,
    RUNTIMES_MVP,
    RUNTIMES_PHASE2,
    SLUG_PATTERN,
)
from opscli.app.domain.exceptions import (
    AppManifestError,
    AppProjectError,
    AppRuntimeUnsupportedError,
)
from opscli.app.domain.models import AppManifest, AppProject

_TOP_LEVEL_FIELDS = {
    "apiVersion",
    "name",
    "title",
    "description",
    "contact",
    "runtime",
    "python",
    "entrypoint",
    "resources",
    "services",
    "opscli",
    "llm",
    "access",
}
_NESTED_FIELDS = {
    "resources": {"cpu", "memory"},
    "services": {"sqlite"},
    "opscli": {"auth_mode", "datasets"},
    "llm": {"enabled"},
    "access": {"visibility"},
}


class ProjectLoader:
    """从目标目录加载并验证 AppHub 项目。"""

    def load(self, path: str | Path) -> AppProject:
        """加载项目；任何失败均发生在 Git 副作用之前。"""
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise AppProjectError("APP-001", f"项目目录不存在: {root}")

        manifest_path = root / APP_YAML_FILENAME
        if not manifest_path.is_file():
            markers = [marker for marker in CODEX_SITE_MARKERS if (root / marker).exists()]
            if markers:
                raise AppRuntimeUnsupportedError(
                    "APP-RUNTIME-UNSUPPORTED",
                    "检测到 Codex Node/static 站点，但 AppHub 当前仅支持 "
                    "streamlit/fastapi/gradio。",
                    fix_hint="请先完成 AppHub Node/static runtime 扩展；不要自动伪造 app.yaml。",
                    detail={"markers": markers},
                )
            raise AppProjectError(
                "APP-001",
                f"未找到 {APP_YAML_FILENAME}: {manifest_path}",
                fix_hint="请在应用根目录创建符合 AppHub 契约的 app.yaml。",
            )

        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise AppManifestError("YAML-INVALID", f"app.yaml 读取失败: {exc}") from exc
        if not isinstance(loaded, dict):
            raise AppManifestError("YAML-INVALID", "app.yaml 顶层必须是对象。")

        manifest = self._validate(loaded)
        return AppProject(root=root, manifest_path=manifest_path, manifest=manifest)

    def _validate(self, data: dict[str, Any]) -> AppManifest:
        unknown = sorted(set(data) - _TOP_LEVEL_FIELDS)
        if unknown:
            raise AppManifestError(
                "YAML-INVALID",
                f"app.yaml 包含未知字段: {', '.join(unknown)}",
            )
        for parent, allowed in _NESTED_FIELDS.items():
            block = data.get(parent, {})
            if block is None:
                block = {}
            if not isinstance(block, dict):
                raise AppManifestError("YAML-INVALID", f"{parent} 必须是对象。")
            nested_unknown = sorted(set(block) - allowed)
            if nested_unknown:
                raise AppManifestError(
                    "YAML-INVALID",
                    f"{parent} 包含未知字段: {', '.join(nested_unknown)}",
                )

        api_version = data.get("apiVersion")
        if api_version != "apps.aukeys/v1":
            raise AppManifestError("YAML-INVALID", "apiVersion 必须为 apps.aukeys/v1。")

        slug = data.get("name")
        if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
            raise AppManifestError(
                "YAML-INVALID",
                "name 须为 3-64 位小写字母/数字/中划线，字母开头、字母数字结尾。",
            )
        if slug in RESERVED_SLUGS:
            raise AppManifestError(
                "SLUG-RESERVED",
                f"slug {slug!r} 命中平台保留字。",
                fix_hint=f"请更换 name；保留字: {', '.join(sorted(RESERVED_SLUGS))}",
            )

        runtime = data.get("runtime")
        if runtime not in RUNTIMES_MVP:
            if runtime in RUNTIMES_PHASE2 or runtime in {"node", "vite", "react", "nextjs"}:
                detail = f"runtime {runtime!r} 尚未开放"
            else:
                detail = f"未知 runtime {runtime!r}"
            raise AppRuntimeUnsupportedError(
                "APP-RUNTIME-UNSUPPORTED",
                f"{detail}；AppHub 当前仅支持 {', '.join(RUNTIMES_MVP)}。",
                fix_hint="Node/static 站点需先完成 AppHub runtime 扩展。",
            )

        python_version = str(data.get("python", "3.11"))
        if python_version not in {"3.11", "3.12"}:
            raise AppManifestError("YAML-INVALID", "python 仅支持 3.11 / 3.12。")

        description = data.get("description", "")
        if not isinstance(description, str) or len(description) > 120:
            raise AppManifestError("YAML-INVALID", "description 最长 120 字符。")

        access = data.get("access") or {}
        visibility = access.get("visibility", "members")
        if visibility == "team":
            raise AppManifestError(
                "APPYAML-VISIBILITY",
                "access.visibility 的 team 档已删除。",
                fix_hint="改用 members，或使用需要审批的 company。",
            )
        if visibility not in {"members", "company"}:
            raise AppManifestError("YAML-INVALID", "access.visibility 仅支持 members/company。")

        opscli = data.get("opscli") or {}
        if opscli.get("auth_mode", "viewer") != "viewer":
            raise AppManifestError("YAML-INVALID", "opscli.auth_mode 当前仅支持 viewer。")
        datasets = opscli.get("datasets", [])
        if not isinstance(datasets, list) or any(not isinstance(item, str) for item in datasets):
            raise AppManifestError("YAML-INVALID", "opscli.datasets 必须是字符串数组。")
        if any(not DATASET_PATTERN.fullmatch(item) for item in datasets):
            raise AppManifestError("YAML-INVALID", "datasets 须使用 ds_ 前缀的 dataset_alias。")
        if len(datasets) != len(set(datasets)):
            raise AppManifestError("YAML-INVALID", "datasets 存在重复声明。")

        entrypoint = data.get("entrypoint", "app.py")
        if not isinstance(entrypoint, str) or not entrypoint.strip():
            raise AppManifestError("YAML-INVALID", "entrypoint 必须是非空字符串。")

        return AppManifest(
            api_version=api_version,
            name=slug,
            runtime=runtime,
            python=python_version,
            entrypoint=entrypoint,
            raw=data,
        )

