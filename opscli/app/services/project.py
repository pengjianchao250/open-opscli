"""项目识别与 AppHub app.yaml 契约校验。"""

from __future__ import annotations

from pathlib import Path

import yaml

from opscli.app.domain.constants import APP_YAML_FILENAME, CODEX_SITE_MARKERS
from opscli.app.domain.exceptions import AppManifestError, AppProjectError, AppRuntimeUnsupportedError
from opscli.app.domain.models import AppManifest, AppProject
from opscli.app.services.schema import AppYamlSchemaValidator


class ProjectLoader:
    """从目标目录加载并验证 AppHub 项目。"""

    def __init__(self, validator: AppYamlSchemaValidator | None = None) -> None:
        self.validator = validator or AppYamlSchemaValidator()

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
                    "检测到 Node/static 站点，但 AppHub 当前仅支持 streamlit/fastapi/gradio。",
                    fix_hint="请先完成 AppHub Node/static runtime 扩展；不要自动伪造 app.yaml。",
                    detail={"markers": markers},
                )
            raise AppProjectError(
                "APP-001",
                f"未找到 {APP_YAML_FILENAME}: {manifest_path}",
                fix_hint="请先执行 opscli app init，或创建符合 AppHub 契约的 app.yaml。",
            )

        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise AppManifestError("YAML-INVALID", f"app.yaml 读取失败: {exc}") from exc
        if not isinstance(loaded, dict):
            raise AppManifestError("YAML-INVALID", "app.yaml 顶层必须是对象。")

        self.validator.validate(loaded)
        services = loaded.get("services") or {}
        opscli_block = loaded.get("opscli") or {}
        access = loaded.get("access") or {}
        manifest = AppManifest(
            api_version=str(loaded["apiVersion"]),
            name=str(loaded["name"]),
            runtime=str(loaded["runtime"]),
            python=str(loaded.get("python", "3.11")),
            entrypoint=str(loaded.get("entrypoint", "app.py")),
            raw=loaded,
            title=str(loaded.get("title", "")),
            description=str(loaded.get("description", "")),
            contact=loaded.get("contact"),
            sqlite_enabled=bool(services.get("sqlite", False)),
            auth_mode=str(opscli_block.get("auth_mode", "viewer")),
            datasets=tuple(str(item) for item in opscli_block.get("datasets", [])),
            visibility=str(access.get("visibility", "members")),
        )
        return AppProject(root=root, manifest_path=manifest_path, manifest=manifest)
