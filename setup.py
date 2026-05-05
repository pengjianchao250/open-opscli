"""Cython 编译配置。

负责将 opscli 包内所有业务 .py（排除 __init__.py 和 skills/templates 下的独立脚本）
编译为平台原生二进制扩展，同时从 wheel 中排除源码 .py，实现源码保护。
"""

import os
import glob
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from Cython.Build import cythonize
from setuptools.extension import Extension


class BuildPyExcludeSource(build_py):
    """自定义 build_py：只保留 __init__.py，其余 .py 由 Cython .so/.pyd 替代。

    这样 wheel 中不含可读源码，但包结构（__init__.py）仍然完整，
    满足铁律3（两种导入方式须同时可用）。
    """

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        # 只保留 __init__ 模块；其余 .py 已由 Cython 编译为 .so/.pyd
        return [
            (pkg, mod, filepath)
            for pkg, mod, filepath in modules
            if mod == "__init__"
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
