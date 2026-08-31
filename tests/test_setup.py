"""验证本地 editable 安装的构建策略。"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType


def _fake_build_modules(monkeypatch, captured: dict) -> None:
    """注入最小构建模块，避免测试依赖真实编译器。"""
    cython_module = ModuleType("Cython")
    cython_build_module = ModuleType("Cython.Build")
    cython_build_module.cythonize = lambda extensions, **kwargs: extensions
    cython_module.Build = cython_build_module

    setuptools_module = ModuleType("setuptools")
    setuptools_module.setup = lambda **kwargs: captured.update(kwargs)
    setuptools_module.find_packages = lambda: []
    setuptools_command_module = ModuleType("setuptools.command")
    setuptools_build_py_module = ModuleType("setuptools.command.build_py")
    setuptools_sdist_module = ModuleType("setuptools.command.sdist")
    setuptools_extension_module = ModuleType("setuptools.extension")
    setuptools_build_py_module.build_py = type("build_py", (), {})
    setuptools_sdist_module.sdist = type("sdist", (), {})
    setuptools_extension_module.Extension = lambda name, sources: (name, sources)

    monkeypatch.setitem(sys.modules, "Cython", cython_module)
    monkeypatch.setitem(sys.modules, "Cython.Build", cython_build_module)
    monkeypatch.setitem(sys.modules, "setuptools", setuptools_module)
    monkeypatch.setitem(sys.modules, "setuptools.command", setuptools_command_module)
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", setuptools_build_py_module)
    monkeypatch.setitem(sys.modules, "setuptools.command.sdist", setuptools_sdist_module)
    monkeypatch.setitem(sys.modules, "setuptools.extension", setuptools_extension_module)


def test_editable_build_skips_cython_without_environment_override(monkeypatch) -> None:
    """editable 构建应自动跳过 Cython，避免依赖本机 C 编译器。"""
    captured: dict = {}

    _fake_build_modules(monkeypatch, captured)
    monkeypatch.delenv("SKIP_CYTHON", raising=False)
    monkeypatch.setattr(sys, "argv", ["setup.py", "editable_wheel"])

    runpy.run_path(str(Path(__file__).parents[1] / "setup.py"), run_name="__main__")

    assert captured["ext_modules"] == []


def test_production_extension_discovery_uses_c_fallback_and_keeps_exclusions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """生产构建应同时支持源码树 .py 与 sdist .c，且共享排除规则。"""
    captured: dict = {}
    _fake_build_modules(monkeypatch, captured)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    package = tmp_path / "opscli" / "collector_monitor"
    package.mkdir(parents=True)
    for name in ("app.py", "app.c", "ui.c", "cli.py", "cli.c", "server.py", "server.c"):
        (package / name).write_text("", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SKIP_CYTHON", raising=False)
    monkeypatch.setattr(sys, "argv", ["setup.py", "bdist_wheel"])
    runpy.run_path(str(Path(__file__).parents[1] / "setup.py"), run_name="__main__")

    extensions = {name: sources for name, sources in captured["ext_modules"]}
    assert extensions == {
        "opscli.collector_monitor.app": ["opscli/collector_monitor/app.py"],
        "opscli.collector_monitor.ui": ["opscli/collector_monitor/ui.c"],
    }


def test_sdist_manifest_keeps_all_runtime_reflection_sources() -> None:
    """sdist 必须保留 setup 排除编译、依赖运行时反射的纯 Python 模块。"""
    manifest = (Path(__file__).parents[1] / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-include opscli cli.py *_cli.py" in manifest
    assert "recursive-include opscli/collector_mcp *.py" in manifest
    assert "recursive-include opscli/mcp/tools *.py" in manifest
    for path in (
        "opscli/mcp/app_factory.py",
        "opscli/mcp/instrumentation.py",
        "opscli/mcp/server.py",
        "opscli/collector_monitor/server.py",
        "opscli/seller_sprite/mcp_bundle.py",
    ):
        assert f"include {path}" in manifest
