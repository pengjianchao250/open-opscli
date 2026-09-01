"""消费 AppHub 导出的 app.yaml JSON Schema。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from opscli.app.domain.exceptions import AppManifestError, AppRuntimeUnsupportedError


@lru_cache(maxsize=1)
def load_appyaml_schema() -> dict[str, Any]:
    """加载随包分发的 AppHub 生成契约。"""
    resource = files("opscli.app.contracts").joinpath("appyaml.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


class AppYamlSchemaValidator:
    """JSON Schema 基础校验加 AppHub 导出扩展约束。"""

    def __init__(self, schema: dict[str, Any] | None = None) -> None:
        self.schema = schema or load_appyaml_schema()
        self.validator = Draft202012Validator(self.schema)

    def validate(self, data: dict[str, Any]) -> None:
        """校验 manifest，错误码与 AppHub 契约保持一致。"""
        access = data.get("access") or {}
        visibility = access.get("visibility") if isinstance(access, dict) else None
        if visibility == "team":
            raise AppManifestError(
                "APPYAML-VISIBILITY",
                "`team` 档已删除。",
                fix_hint="改用 members，或在完成审批后使用 company。",
            )

        errors = sorted(self.validator.iter_errors(data), key=lambda item: list(item.absolute_path))
        if errors:
            details = []
            for item in errors:
                path = ".".join(str(part) for part in item.absolute_path) or "app.yaml"
                details.append({"path": path, "message": item.message})
            rendered = "；".join(f"{item['path']}: {item['message']}" for item in details)
            raise AppManifestError(
                "YAML-INVALID",
                f"app.yaml 校验失败：{rendered}",
                fix_hint="按字段错误逐条修正 app.yaml 后重试。",
                detail={"violations": details},
            )

        slug = str(data.get("name") or "")
        if not re.fullmatch(str(self.schema["x-slug-pattern"]), slug):
            raise AppManifestError(
                "YAML-INVALID",
                "name 须为 3-64 位小写字母/数字/中划线，字母开头、字母数字结尾。",
            )
        reserved = set(self.schema["x-reserved-slugs"])
        if slug in reserved:
            raise AppManifestError(
                "SLUG-RESERVED",
                f"slug {slug!r} 命中平台保留字。",
                fix_hint=f"请更换 name；保留字：{', '.join(sorted(reserved))}",
            )

        runtime = str(data.get("runtime") or "")
        runtimes_mvp = tuple(self.schema["x-runtimes-mvp"])
        if runtime not in runtimes_mvp:
            phase2 = set(self.schema["x-runtimes-phase2"])
            message = f"runtime {runtime!r} 二期开放" if runtime in phase2 else f"未知 runtime {runtime!r}"
            raise AppRuntimeUnsupportedError(
                "APP-RUNTIME-UNSUPPORTED",
                f"{message}；MVP 支持：{', '.join(runtimes_mvp)}。",
            )

        python_version = str(data.get("python", "3.11"))
        if python_version not in {"3.11", "3.12"}:
            raise AppManifestError("YAML-INVALID", "python 仅支持 3.11 / 3.12。")

        opscli_block = data.get("opscli") or {}
        datasets = opscli_block.get("datasets") or [] if isinstance(opscli_block, dict) else []
        dataset_pattern = re.compile(str(self.schema["x-dataset-alias-pattern"]))
        invalid = [value for value in datasets if not isinstance(value, str) or not dataset_pattern.fullmatch(value)]
        if invalid:
            raise AppManifestError(
                "YAML-INVALID",
                f"datasets 须使用 ds_ 前缀的 dataset_alias，收到：{invalid!r}",
            )
        if len(datasets) != len(set(datasets)):
            raise AppManifestError("YAML-INVALID", "datasets 存在重复声明。")
