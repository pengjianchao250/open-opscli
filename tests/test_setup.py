"""验证本地 editable 安装的构建策略。"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType


def test_editable_build_skips_cython_without_environment_override(monkeypatch) -> None:
    """editable 构建应自动跳过 Cython，避免依赖本机 C 编译器。"""
    captured: dict = {}

    # 构造最小构建模块，避免测试依赖隔离环境中的 setuptools 和 Cython。
    cython_module = ModuleType("Cython")
    cython_build_module = ModuleType("Cython.Build")
    cython_build_module.cythonize = lambda extensions, **kwargs: ["compiled"]
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

    monkeypatch.delenv("SKIP_CYTHON", raising=False)
    monkeypatch.setattr(sys, "argv", ["setup.py", "editable_wheel"])
    monkeypatch.setitem(sys.modules, "Cython", cython_module)
    monkeypatch.setitem(sys.modules, "Cython.Build", cython_build_module)
    monkeypatch.setitem(sys.modules, "setuptools", setuptools_module)
    monkeypatch.setitem(sys.modules, "setuptools.command", setuptools_command_module)
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", setuptools_build_py_module)
    monkeypatch.setitem(sys.modules, "setuptools.command.sdist", setuptools_sdist_module)
    monkeypatch.setitem(sys.modules, "setuptools.extension", setuptools_extension_module)

    runpy.run_path(str(Path(__file__).parents[1] / "setup.py"), run_name="__main__")

    assert captured["ext_modules"] == []
