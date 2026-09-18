"""AppHub Vue runtime-only 前端合同校验器测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "opscli"
    / "skills"
    / "templates"
    / "ops-app-build-spec"
    / "scripts"
    / "validate_frontend_contracts.py"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "apphub_frontend_contract_validator",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source(tmp_path: Path, relative: str, content: str) -> Path:
    path = tmp_path / "frontend" / "src" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_standard_vue_sfc_template_passes(tmp_path: Path) -> None:
    validator = _load_validator()
    _write_source(
        tmp_path,
        "views/DashboardView.vue",
        "<template><section>{{ title }}</section></template>\n<script setup>\nconst title = 'Dashboard'\n</script>\n",
    )

    assert validator.validate_project(tmp_path) == []


def test_component_string_template_is_rejected(tmp_path: Path) -> None:
    validator = _load_validator()
    _write_source(
        tmp_path,
        "views/DashboardView.vue",
        "<template><DataTable /></template>\n<script>\nexport default { components: { DataTable: { template: '<div>rows</div>' } } }\n</script>\n",
    )

    errors = validator.validate_project(tmp_path)

    assert any("禁止组件字符串 template" in error for error in errors)


def test_vue_compile_and_compile_import_are_rejected(tmp_path: Path) -> None:
    validator = _load_validator()
    _write_source(
        tmp_path,
        "components/runtime.ts",
        "import { compile } from 'vue'\nconst one = compile('<div />')\nconst two = Vue.compile('<span />')\n",
    )

    errors = validator.validate_project(tmp_path)

    assert any("禁止从 vue 导入 compile" in error for error in errors)
    assert any("禁止 Vue.compile" in error for error in errors)


def test_test_fixture_string_template_is_ignored(tmp_path: Path) -> None:
    """Vitest/Jest 测试替身可以使用字符串模板，不影响生产运行时。"""
    validator = _load_validator()
    _write_source(
        tmp_path,
        "layouts/AdminLayout.test.js",
        "const stub = { template: '<p>fixture</p>' }",
    )
    _write_source(
        tmp_path,
        "components/__tests__/Widget.spec.ts",
        "const stub = { template: '<p>fixture</p>' }",
    )

    assert validator.validate_project(tmp_path) == []


def test_missing_frontend_source_is_reported(tmp_path: Path) -> None:
    validator = _load_validator()

    errors = validator.validate_project(tmp_path)

    assert any("标准前端源码目录不存在" in error for error in errors)
