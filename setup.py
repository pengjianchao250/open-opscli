"""Cython 编译配置。

负责将 opscli 包内所有业务 .py（排除 __init__.py 和 skills/templates 下的独立脚本）
编译为平台原生二进制扩展，同时从 wheel 中排除源码 .py，实现源码保护。
"""

import os
import re
import glob
import importlib.util
from pathlib import Path
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist
from Cython.Build import cythonize
from setuptools.extension import Extension

# 本地开发时设置 SKIP_CYTHON=1 跳过 Cython 编译，加速安装
# 用法：SKIP_CYTHON=1 pip install -e .
_SKIP_CYTHON = os.environ.get("SKIP_CYTHON", "").strip() in ("1", "true", "yes")
_REPO_ROOT = Path(__file__).resolve().parent
_PACKAGING_MODULE = _REPO_ROOT / "opscli" / "skills" / "packaging.py"


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
    _KEEP_SOURCE = {"__init__", "cli", "server", "report_skill_usage"}
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


def get_extensions():
    """收集所有需要 Cython 编译的 .py 文件。

    当环境变量 SKIP_CYTHON=1 时返回空列表，跳过编译（本地开发用）。
    生产构建（GitHub Actions）不设置此变量，正常编译。

    排除规则：
    - __init__.py：保留为纯 Python，保证包结构和双路径导入（铁律3）
    - skills/templates/**：Skill 独立脚本，面向用户安装后直接使用，不应编译
    - cli.py / *_cli.py：Typer 依赖运行时签名反射，Cython 编译后会破坏
    - mcp/server.py / mcp/tools/*.py：FastMCP 依赖类型注解反射
    """
    if _SKIP_CYTHON:
        return []
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

        # 排除所有 cli.py / *_cli.py —— Typer 依赖 inspect.signature() 解析参数默认值，
        # Cython 编译后 cyfunction 丢失签名信息，导致 typer.Option() 无法被正确识别。
        # marketplace_cli.py / publish_cli.py / sync_exclude_cli.py 等子命令文件同理，
        # 必须一并排除，否则 @app.command() 在模块初始化时抛出：
        #   TypeError: Expected str, got OptionInfo
        _basename = os.path.basename(f)
        if _basename == "cli.py" or _basename.endswith("_cli.py"):
            continue

        # 排除 MCP server 和 tools —— FastMCP 用 Pydantic TypeAdapter 解析函数类型注解，
        # Cython 编译后 cyfunction 无法被 Pydantic 生成 schema，导致启动报错
        if "opscli/mcp/server.py" in f_unix or "opscli/mcp/tools/" in f_unix:
            continue

        # 排除 skills/hooks/report_skill_usage.py —— 该文件是 hook 脚本，
        # 部署到用户 ~/.opscli/hooks/ 后由 Python 解释器直接执行（不是被 import 的模块）。
        # 必须保留 .py 源文件，否则 settings_injector.py 通过 pkg_files() 读不到该脚本。
        if f_unix == "opscli/skills/hooks/report_skill_usage.py":
            continue

        # 路径转模块名：opscli/auth/cli.py → opscli.auth.cli
        module_name = f_unix.replace("/", ".")[:-3]
        extensions.append(Extension(module_name, [f]))

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
