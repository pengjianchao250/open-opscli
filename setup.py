"""Cython 编译配置。

负责将 opscli 包内所有业务 .py（排除 __init__.py 和 skills/templates 下的独立脚本）
编译为平台原生二进制扩展，同时从 wheel 中排除源码 .py，实现源码保护。
"""

import os
import re
import glob
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from Cython.Build import cythonize
from setuptools.extension import Extension


def _read_version():
    """从 pyproject.toml 读取版本号，保证 setup.py 与 pyproject.toml 单一来源同步。"""
    with open("pyproject.toml", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return m.group(1) if m else "0.0.0"


class BuildPyExcludeSource(build_py):
    """自定义 build_py：只保留 __init__.py，其余 .py 由 Cython .so/.pyd 替代。

    这样 wheel 中不含可读源码，但包结构（__init__.py）仍然完整，
    满足铁律3（两种导入方式须同时可用）。
    """

    # 不编译、需保留源码的文件名集合（Typer/FastMCP 依赖运行时反射）
    _KEEP_SOURCE = {"__init__", "cli", "server"}
    # 不编译、需保留源码的目录路径片段
    _KEEP_SOURCE_DIRS = {"mcp/tools"}

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        # 保留 __init__.py + 所有不参与 Cython 编译的纯 Python 文件
        # 其余 .py 已由 Cython 编译为 .so/.pyd，从 wheel 中排除源码
        return [
            (pkg, mod, filepath)
            for pkg, mod, filepath in modules
            if mod in self._KEEP_SOURCE
            or any(d in filepath.replace(os.sep, "/") for d in self._KEEP_SOURCE_DIRS)
        ]


def get_extensions():
    """收集所有需要 Cython 编译的 .py 文件。

    排除规则：
    - __init__.py：保留为纯 Python，保证包结构和双路径导入（铁律3）
    - skills/templates/**：Skill 独立脚本，面向用户安装后直接使用，不应编译
    """
    py_files = glob.glob("opscli/**/*.py", recursive=True)
    extensions = []

    for f in py_files:
        # 统一使用正斜杠便于跨平台路径判断
        f_unix = f.replace(os.sep, "/")

        # 排除 __init__.py（铁律3：保留包结构 + 两种导入方式）
        if os.path.basename(f) == "__init__.py":
            continue

        # 排除 skills/templates 下的独立脚本（安装后供用户直接运行，不作为模块导入）
        if "opscli/skills/templates/" in f_unix:
            continue

        # 排除所有 cli.py —— Typer 依赖 inspect.signature() 解析参数默认值，
        # Cython 编译后 cyfunction 丢失签名信息，导致 typer.Option() 无法被正确识别
        if os.path.basename(f) == "cli.py":
            continue

        # 排除 MCP server 和 tools —— FastMCP 用 Pydantic TypeAdapter 解析函数类型注解，
        # Cython 编译后 cyfunction 无法被 Pydantic 生成 schema，导致启动报错
        if "opscli/mcp/server.py" in f_unix or "opscli/mcp/tools/" in f_unix:
            continue

        # 路径转模块名：opscli/auth/cli.py → opscli.auth.cli
        module_name = f_unix.replace("/", ".")[:-3]
        extensions.append(Extension(module_name, [f]))

    return cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,   # 关闭边界检查，提升性能
            "wraparound": False,    # 关闭负索引包装，提升性能
        },
        nthreads=4,
    )


setup(
    name="aukeys-opscli",        # 与 pyproject.toml [project].name 一致
    version=_read_version(),     # 动态读取，保证单一来源
    ext_modules=get_extensions(),
    packages=find_packages(),
    package_data={
        # Skill 模板目录：SKILL.md / VERSION.json / references/*.md / scripts/*.py
        # 这些文件需原样打包进 wheel，供 skills install 命令使用
        "opscli": [
            "skills/templates/**/*",
            "skills/templates/**/**/*",
        ],
    },
    cmdclass={"build_py": BuildPyExcludeSource},
)
