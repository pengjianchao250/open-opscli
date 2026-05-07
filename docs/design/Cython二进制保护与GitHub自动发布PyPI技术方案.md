# Cython 源码保护 + GitHub Actions 自动发布 PyPI 完整技术方案

> 基于 opscli 项目的实际落地经验整理（v0.0.35），适用于任何需要保护 Python 源码并自动发布二进制包的项目。

---

## 一、整体架构

```
私有 GitLab（源码主仓库）
       │
       │ ./release.sh <version>
       ▼
私有 GitHub（构建触发源）
       │
       │ 推送 Tag v* → 触发 Actions
       ▼
GitHub Actions（三平台并行构建）
  ├── ubuntu-22.04   → Linux manylinux wheel（cp310~314）
  ├── windows-latest → Windows wheel（cp310~314）
  └── macos-latest   → macOS wheel（x86_64 + arm64 × cp310~314）
       │
       │ cibuildwheel 调用 Cython 编译 → .so / .pyd 二进制
       ▼
     PyPI（二进制 wheel，用户无法获取源码）
```

### 核心思路

1. **源码保护**：Cython 将 `.py` 编译为 `.so`（Linux/macOS）/ `.pyd`（Windows），wheel 中不包含可读源码
2. **双 Remote**：GitLab 作为主仓库（团队协作），GitHub 作为构建触发源（仅推送 Tag 时同步）
3. **全自动发布**：推送 Tag → Actions 自动构建所有平台 wheel → 发布 PyPI，无需人工干预

### 解决的问题

- **cp313/cp314 支持**：cp 新版本在 cibuildwheel 中被标记为 prerelease，需设置 `CIBW_PRERELEASE_PYTHONS: "1"`
- **Metadata-Version 2.4 兼容**：setuptools 82+ 生成 Metadata-Version 2.4，旧版 twine 不支持，改用直接 `pip install twine` 上传
- **ubuntu-latest runner 限制**：新注册 GitHub 账号或高峰期 runner 紧张时 ubuntu-latest 获取失败，改用 `ubuntu-22.04` + `macos-latest` 发布job
- **部分平台失败不阻塞发版**：允许个别平台 runner 获取失败，publish job 用 `--skip-existing` 补传

---

## 二、前置条件

| 项目 | 说明 |
|------|------|
| GitHub 公开仓库 | 用于触发 Actions（私有仓库在 runner 紧张时有问题，公开仓库无此限制） |
| GitHub Secret | 仓库 Settings → Secrets → `PIPY_OPEN_OPSCLI` = PyPI token |
| 本地 Git 配置 | 双 remote（GitLab origin + GitHub github） |

---

## 三、项目结构

```
open-opscli/
├── opscli/                          # Python 包（核心源码）
│   ├── __init__.py                  # 保留为 .py（包入口 + re-export）
│   ├── auth/
│   │   ├── __init__.py              # 保留为 .py
│   │   ├── cli.py                   # ⚠️ 不编译（Typer 依赖 inspect.signature）
│   │   └── core/
│   │       ├── device_flow.py       # → 编译为 .so/.pyd
│   │       └── token_manager.py     # → 编译为 .so/.pyd
│   ├── mcp/
│   │   ├── server.py               # ⚠️ 不编译（FastMCP 依赖类型注解）
│   │   └── tools/                  # ⚠️ 不编译（依赖类型注解反射）
│   └── skills/
│       ├── __init__.py              # 保留为 .py
│       └── templates/               # ⚠️ 不编译，原样打包
├── .github/workflows/
│   └── build-and-publish.yml        # CI/CD 配置
├── pyproject.toml                   # 项目元数据 + 构建系统
├── setup.py                         # Cython 编译配置（核心）
├── MANIFEST.in                      # sdist 内容控制
└── release.sh                       # 发版一键脚本
```

---

## 四、配置文件详解

### 4.1 `pyproject.toml`

```toml
[project]
name = "aukeys-opscli"
version = "0.0.35"
description = "Aukeys 运营 CLI 工具集"
readme = "README.md"
requires-python = ">=3.10"        # 最低支持版本

dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "cryptography>=38",
    "rich>=13",
    "keyring>=25",
    "fastmcp>=2.0",
]

[project.scripts]
opscli = "opscli.cli:app"
opscli-mcp = "opscli.mcp.server:run"

[build-system]
requires = ["setuptools>=68", "wheel", "cython>=3"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["opscli*"]
```

---

### 4.2 `setup.py` — Cython 编译核心配置

```python
import os
import re
import glob
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from Cython.Build import cythonize
from setuptools.extension import Extension

# 本地开发跳过编译：SKIP_CYTHON=1 pip install -e .
_SKIP_CYTHON = os.environ.get("SKIP_CYTHON", "").strip() in ("1", "true", "yes")

def _read_version():
    with open("pyproject.toml") as f:
        content = f.read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return m.group(1) if m else "0.0.0"

class BuildPyExcludeSource(build_py):
    """wheel 中排除业务 .py，仅保留 __init__ + 指定文件"""
    _KEEP_SOURCE = {"__init__", "cli", "server"}      # 不编译的文件
    _KEEP_SOURCE_DIRS = {"mcp/tools"}                # 不编译的目录

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            (pkg, mod, filepath)
            for pkg, mod, filepath in modules
            if mod in self._KEEP_SOURCE
            or any(d in filepath.replace(os.sep, "/") for d in self._KEEP_SOURCE_DIRS)
        ]

def get_extensions():
    """收集需要 Cython 编译的 .py"""
    if _SKIP_CYTHON:
        return []
    py_files = glob.glob("opscli/**/*.py", recursive=True)
    extensions = []
    for f in py_files:
        f_unix = f.replace(os.sep, "/")
        basename = os.path.basename(f)
        # 排除规则
        if basename == "__init__.py": continue
        if "opscli/skills/templates/" in f_unix: continue
        if basename == "cli.py": continue                     # Typer 依赖运行时反射
        if "opscli/mcp/server.py" in f_unix: continue          # FastMCP 依赖类型注解
        if "opscli/mcp/tools/" in f_unix: continue
        module_name = f_unix.replace("/", ".")[:-3]
        extensions.append(Extension(module_name, [f]))
    return cythonize(extensions, compiler_directives={"language_level": "3"}, nthreads=4)

setup(
    name="aukeys-opscli",
    version=_read_version(),
    ext_modules=get_extensions(),
    packages=find_packages(),
    package_data={"opscli": ["skills/templates/**/*", "skills/templates/**/**/*"]},
    cmdclass={} if _SKIP_CYTHON else {"build_py": BuildPyExcludeSource},
)
```

---

### 4.3 `.github/workflows/build-and-publish.yml`

```yaml
name: Build and Publish to PyPI
on:
  push:
    tags: ["v*"]
  workflow_dispatch:

jobs:
  build_wheels:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-22.04, windows-latest, macos-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: pypa/cibuildwheel@v2.21.3
        env:
          CIBW_BUILD: "cp310-* cp311-* cp312-* cp313-* cp314-*"
          CIBW_PRERELEASE_PYTHONS: "1"        # 支持 cp313/cp314
          CIBW_SKIP: "*-manylinux_i686 *-musllinux*"
          CIBW_ARCHS_MACOS: "x86_64 arm64"
          CIBW_BEFORE_BUILD: "pip install cython>=3 setuptools>=68 wheel"
          CIBW_TEST_COMMAND: "python -c 'import opscli; print(\"ok\")'"
      - uses: actions/upload-artifact@v4
        with:
          name: wheels-${{ matrix.os }}
          path: ./wheelhouse/*.whl
          retention-days: 7

  build_sdist:
    runs-on: ubuntu-22.04
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install build cython>=3 setuptools>=68
      - run: python -m build --sdist
      - uses: actions/upload-artifact@v4
        with:
          name: sdist
          path: dist/*.tar.gz
          retention-days: 7

  publish:
    needs: [build_wheels, build_sdist]
    # 允许部分平台失败，不阻塞发版
    if: ${{ !cancelled() && needs.build_wheels.result != 'cancelled' }}
    runs-on: macos-latest                    # 避免 ubuntu runner 紧张问题
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: "wheels-*"
          merge-multiple: true
          path: dist/
      - uses: actions/download-artifact@v4
        with:
          name: sdist
          path: dist/
        continue-on-error: true
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      # 直接用最新 twine 上传，避免 Metadata-Version 2.4 兼容问题
      - run: |
          pip install --quiet twine
          twine upload dist/* --username __token__ --password "$PYPI_TOKEN" --skip-existing
        env:
          PYPI_TOKEN: ${{ secrets.PIPY_OPEN_OPSCLI }}
```

---

### 4.4 `release.sh`

```bash
#!/bin/bash
set -e
VERSION=$1

if [ -z "$VERSION" ]; then echo "用法: ./release.sh 0.0.35"; exit 1; fi
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then echo "版本格式错误"; exit 1; fi

echo "🚀 开始发布 v$VERSION"

git pull origin master

python3 - "$VERSION" <<'PYEOF'
import re, sys
VERSION = sys.argv[1]
with open("pyproject.toml") as f: content = re.sub(r'^version = ".*"', f'version = "{VERSION}"', f.read(), flags=re.MULTILINE)
with open("pyproject.toml", "w") as f: f.write(content)
with open("opscli/version.py") as f: content = re.sub(r'^FALLBACK_VERSION = ".*"', f'FALLBACK_VERSION = "{VERSION}-dev"', f.read(), flags=re.MULTILINE)
with open("opscli/version.py", "w") as f: f.write(content)
print(f"version → {VERSION}")
PYEOF

git add pyproject.toml opscli/version.py
git commit -m "release: 发布 v$VERSION"
git tag "v$VERSION"

git push origin master && git push origin "v$VERSION"
git push github master && git push github "v$VERSION"

echo "✅ 完成！约 15~20 分钟后发布到 PyPI"
```

---

## 五、cibuildwheel 核心参数

| 环境变量 | 示例值 | 说明 |
|----------|--------|------|
| `CIBW_BUILD` | `"cp310-* cp311-* cp312-* cp313-* cp314-*"` | 构建的 Python 版本 |
| `CIBW_PRERELEASE_PYTHONS` | `"1"` | 支持 cp313/cp314 等新版本 |
| `CIBW_SKIP` | `"*-manylinux_i686 *-musllinux*"` | 跳过不兼容的构建 |
| `CIBW_ARCHS_MACOS` | `"x86_64 arm64"` | macOS 双架构 |
| `CIBW_BEFORE_BUILD` | `"pip install cython>=3..."` | 构建前安装依赖 |
| `CIBW_TEST_COMMAND` | `"python -c ..."` | wheel 构建后验证 |

---

## 六、常见问题排查

### Q1：ubuntu-latest runner 获取失败（"The job was not acquired by Runner"）

**原因**：新注册 GitHub 账号有 runner 限制，高峰期 runner 池紧张

**解决**：
1. 改用 `ubuntu-22.04` 替代 `ubuntu-latest`
2. publish job 改跑 `macos-latest`
3. 发布条件改为 `!= 'cancelled'`（允许部分平台失败）

### Q2：PyPI 发布失败（"Metadata is missing required fields: Name, Version"）

**原因**：setuptools 82+ 生成 Metadata-Version 2.4，旧版 twine 只支持到 2.3

**解决**：
```yaml
# 不使用 pypa/gh-action-pypi-publish，直接用最新版 twine
- run: pip install --quiet twine
- run: twine upload dist/* --username __token__ --password "$PYPI_TOKEN"
```

### Q3：cp313/cp314 构建被跳过

**原因**：cibuildwheel 将新版本 Python 标记为 prerelease

**解决**：
```yaml
CIBW_PRERELEASE_PYTHONS: "1"
```

### Q4：Secret 名称不一致

**原因**：仓库 Secret 名称 `PIPY_OPEN_OPSCLI` 与 workflow 中引用不一致

**解决**：确保 workflow 中 `secrets.PIPY_OPEN_OPSCLI` 与仓库 Settings → Secrets 中的名称完全一致

---

## 七、预期产物

```
aukeys_opscli-0.0.35-cp310-cp310-manylinux_x86_64.whl
aukeys_opscli-0.0.35-cp311-cp311-manylinux_x86_64.whl
aukeys_opscli-0.0.35-cp312-cp312-manylinux_x86_64.whl
aukeys_opscli-0.0.35-cp313-cp313-manylinux_x86_64.whl
aukeys_opscli-0.0.35-cp314-cp314-manylinux_x86_64.whl
aukeys_opscli-0.0.35-cp310-cp310-win_amd64.whl
aukeys_opscli-0.0.35-cp311-cp311-win_amd64.whl
aukeys_opscli-0.0.35-cp312-cp312-win_amd64.whl
aukeys_opscli-0.0.35-cp313-cp313-win_amd64.whl
aukeys_opscli-0.0.35-cp314-cp314-win_amd64.whl
aukeys_opscli-0.0.35-cp310-cp310-macosx_x86_64.whl
aukeys_opscli-0.0.35-cp311-cp311-macosx_x86_64.whl
aukeys_opscli-0.0.35-cp312-cp312-macosx_x86_64.whl
aukeys_opscli-0.0.35-cp313-cp313-macosx_x86_64.whl
aukeys_opscli-0.0.35-cp314-cp314-macosx_x86_64.whl
aukeys_opscli-0.0.35-cp310-cp310-macosx_arm64.whl
aukeys_opscli-0.0.35-cp311-cp311-macosx_arm64.whl
aukeys_opscli-0.0.35-cp312-cp312-macosx_arm64.whl
aukeys_opscli-0.0.35-cp313-cp313-macosx_arm64.whl
aukeys_opscli-0.0.35-cp314-cp314-macosx_arm64.whl
aukeys_opscli-0.0.35.tar.gz
```

---

## 八、编译边界说明

| 文件类型 | 处理方式 |
|----------|----------|
| `opscli/**/*.py`（非 `__init__`/cli.py/mcp/*） | Cython 编译 → `.so`/`.pyd` |
| `opscli/**/__init__.py` | 保留为 `.py`（包发现依赖） |
| `opscli/**/cli.py` | 保留为 `.py`（Typer 依赖 inspect.signature） |
| `opscli/mcp/server.py` | 保留为 `.py`（FastMCP 依赖类型注解） |
| `opscli/mcp/tools/*.py` | 保留为 `.py`（FastMCP 依赖类型注解） |
| `skills/templates/**/*.py` | 保留为 `.py`（独立脚本） |
| `skills/templates/**/*.*` | 保留（如 SKILL.md） |

---

## 九、发版流程

```bash
./release.sh 0.0.35
```

自动完成：
1. `git pull origin master`
2. 更新 `pyproject.toml` + `opscli/version.py`
3. `git commit -m "release: 发布 v0.0.35"`
4. `git tag v0.0.35` 并推送到 GitLab + GitHub
5. GitHub Actions 自动构建三平台 wheel
6. 自动发布到 PyPI

---

## 十、验证

```bash
pip index versions aukeys-opscli
pip install aukeys-opscli==0.0.35
opscli --version
```