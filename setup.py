"""Cython 编译配置。

负责将 opscli 包内所有业务 .py（排除 __init__.py 和 skills/templates 下的独立脚本）
编译为平台原生二进制扩展，同时从 wheel 中排除源码 .py，实现源码保护。
"""

import os
import re
import glob
import importlib.util
import sys
from pathlib import Path
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist
from Cython.Build import cythonize
from setuptools.extension import Extension

# editable 安装属于本地开发流程，自动跳过 Cython；环境变量保留给其他开发命令。
_SKIP_CYTHON = (
    os.environ.get("SKIP_CYTHON", "").strip() in ("1", "true", "yes")
    or any(command in {"develop", "editable_wheel"} for command in sys.argv)
)
_REPO_ROOT = Path(__file__).resolve().parent
_PACKAGING_MODULE = _REPO_ROOT / "opscli" / "skills" / "packaging.py"
_KEEP_SOURCE_MODULE_NAMES = {
    "__init__",
    "app_factory",
    "cli",
    "instrumentation",
    "server",
    "report_skill_usage",
}
_KEEP_SOURCE_PATH_PARTS = {"mcp/tools", "collector_mcp", "seller_sprite/mcp_bundle"}


def _load_skill_packaging():
    """加载 Skill 发版准入工具，避免 setup 阶段触发 opscli 包导入链。"""
    spec = importlib.util.spec_from_file_location("_opscli_skill_packaging", _PACKAGING_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Skill 发版准入模块: {_PACKAGING_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_version():
    """从 pyproject.toml 读取版本号，保证 setup.py 与 pyproject.toml 单一来源同步。"""
    with open("pyproject.toml", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return m.group(1) if m else "0.0.0"


class BuildPyPruneSkillTemplates(build_py):
    """按 OPSCLI_SKILL_PROFILE 裁剪 wheel 中的 Skill 模板。"""

    def run(self):
        super().run()
        packaging = _load_skill_packaging()
        profile = packaging.current_profile()
        templates_dir = Path(self.build_lib) / "opscli" / "skills" / "templates"
        kept = packaging.prune_templates_dir(
            templates_dir,
            profile=profile,
            artifact="wheel",
            manifest_templates_dir=_REPO_ROOT / "opscli" / "skills" / "templates",
        )
        if profile not in {"dev", "internal"}:
            print(f"Skill templates profile={profile} artifact=wheel kept={','.join(kept)}")


class BuildPyExcludeSource(BuildPyPruneSkillTemplates):
    """自定义 build_py：只保留 __init__.py，其余 .py 由 Cython .so/.pyd 替代。

    这样 wheel 中不含可读源码，但包结构（__init__.py）仍然完整，
    满足铁律3（两种导入方式须同时可用）。
    """

    # 不编译、需保留源码的文件名集合（Typer/FastMCP 依赖运行时反射）
    # report_skill_usage 需保留 .py 源文件，因其作为 hook 脚本部署到用户目录
    _KEEP_SOURCE = _KEEP_SOURCE_MODULE_NAMES
    # 不编译、需保留源码的目录路径片段
    _KEEP_SOURCE_DIRS = _KEEP_SOURCE_PATH_PARTS

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        # 保留 __init__.py + 所有不参与 Cython 编译的纯 Python 文件
        # 其余 .py 已由 Cython 编译为 .so/.pyd，从 wheel 中排除源码
        return [
            (pkg, mod, filepath)
            for pkg, mod, filepath in modules
            if _keep_python_source(filepath)
        ]


class SdistPruneSkillTemplates(sdist):
    """按 OPSCLI_SKILL_PROFILE 裁剪 sdist 中的 Skill 模板。"""

    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        packaging = _load_skill_packaging()
        profile = packaging.current_profile()
        templates_dir = Path(base_dir) / "opscli" / "skills" / "templates"
        kept = packaging.prune_templates_dir(
            templates_dir,
            profile=profile,
            artifact="sdist",
            manifest_templates_dir=_REPO_ROOT / "opscli" / "skills" / "templates",
        )
        if profile not in {"dev", "internal"}:
            print(f"Skill templates profile={profile} artifact=sdist kept={','.join(kept)}")


def _keep_python_source(path: str) -> bool:
    """判断模块是否依赖运行时反射或作为独立脚本保留源码。"""
    normalized = path.replace(os.sep, "/")
    module_name = Path(normalized).stem
    return (
        module_name in _KEEP_SOURCE_MODULE_NAMES
        or module_name.endswith("_cli")
        or any(part in normalized for part in _KEEP_SOURCE_PATH_PARTS)
    )


def get_extensions():
    """收集源码树 .py 或生产 sdist .c 中需要注册的 Cython 扩展。"""
    if _SKIP_CYTHON:
        return []
    sources_by_module = {}
    # 同一模块同时有 .py/.c 时优先 .py；sdist 排除业务源码后自动回退到 .c。
    for suffix in ("c", "py"):
        for source in glob.glob(f"opscli/**/*.{suffix}", recursive=True):
            normalized = source.replace(os.sep, "/")
            logical_path = normalized.rsplit(".", 1)[0] + ".py"
            if (
                "opscli/skills/templates/" in logical_path
                or _keep_python_source(logical_path)
            ):
                continue
            module_name = logical_path[:-3].replace("/", ".")
            sources_by_module[module_name] = normalized

    extensions = [
        Extension(module_name, [source])
        for module_name, source in sorted(sources_by_module.items())
    ]
    return cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            # 不设置 boundscheck/wraparound，保留 Python 默认安全检查
            # 这两个指令曾导致 Segmentation Fault：关闭越界检查后，
            # list[越界索引] / list[-1] 不抛 IndexError 而是直接访问非法内存
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
            "mcp/references/**/*.md",
            "collector_monitor/wecom-webhook",
        ],
    },
    exclude_package_data={
        "opscli": [
            "skills/templates/.DS_Store",
            "skills/templates/**/.DS_Store",
            "skills/templates/**/*.pyc",
            "skills/templates/**/*.pyo",
            "skills/templates/**/__pycache__/*",
            "mcp/references/**/.DS_Store",
        ],
    },
    # 跳过 Cython 时仍保留 Skill 模板裁剪逻辑；正常发版同时排除业务源码。
    cmdclass={
        "build_py": BuildPyPruneSkillTemplates if _SKIP_CYTHON else BuildPyExcludeSource,
        "sdist": SdistPruneSkillTemplates,
    },
)
