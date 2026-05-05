# Cython 源码保护 + GitHub Actions 自动发布 PyPI 完整技术方案

> 基于 opscli 项目的实际落地经验整理，适用于任何需要保护 Python 源码并自动发布二进制包的项目。

---

## 一、整体架构

```
私有 GitLab（源码存储）
       │
       │ ./release.sh <version>（发版人手动执行）
       ▼
私有 GitHub（构建触发源）
       │
       │ 推送 Tag v* → 触发 Actions
       ▼
GitHub Actions（免费云构建，三平台并行）
  ├── ubuntu-latest  → Linux manylinux wheel（cp310/311/312/313）
  ├── windows-latest → Windows wheel（cp310/311/312/313）
  └── macos-latest   → macOS wheel（x86_64 + arm64 × cp310/311/312/313）
       │
       │ cibuildwheel 调用 Cython 编译 → .so / .pyd 二进制
       ▼
     PyPI（仅发布二进制 wheel，用户无法获取源码）
```

### 核心思路

1. **源码保护**：Cython 将 `.py` 编译为 `.so`（Linux/macOS）/ `.pyd`（Windows），wheel 中不包含可读源码
2. **双 Remote**：GitLab 作为主仓库（团队协作），GitHub 作为构建触发源（仅发版人推送）
3. **全自动发布**：推送 Tag → Actions 自动构建所有平台 wheel → 发布 PyPI，无需人工干预

---

## 二、前置条件

| 项目 | 说明 |
|------|------|
| GitHub 私有仓库 | 已创建，用于存放源码和触发 Actions |
| PyPI 账号 | 已在 pypi.org 注册，项目名已占用（或首次发布自动创建） |
| PyPI API Token | 在 pypi.org 生成，权限范围选 **Entire account** 或具体项目 |
| GitHub Secret | 仓库 Settings → Secrets → `PYPI_API_TOKEN` = 上面的 token |
| 本地 SSH Key | 已添加公钥到 GitHub（或使用 HTTPS + PAT 推送） |

---

## 三、项目结构

```
open-opscli/
├── opscli/                          # Python 包（核心源码）
│   ├── __init__.py                  # 保留为 .py（包入口 + re-export）
│   ├── auth/
│   │   ├── __init__.py              # 保留为 .py
│   │   ├── cli.py                   # → 编译为 .so/.pyd
│   │   └── core/
│   │       ├── device_flow.py       # → 编译为 .so/.pyd
│   │       └── token_manager.py     # → 编译为 .so/.pyd
│   └── skills/
│       ├── __init__.py              # 保留为 .py
│       └── templates/               # ⚠️ 不编译，原样打包
│           └── ops-auth/
│               ├── SKILL.md         # 原样打包
│               ├── data/VERSION.json
│               └── scripts/*.py     # 原样打包（独立脚本，用户直接运行）
├── .github/
│   └── workflows/
│       └── build-and-publish.yml    # CI/CD 配置
├── pyproject.toml                   # 项目元数据 + 构建系统声明
├── setup.py                         # Cython 编译配置（核心）
├── MANIFEST.in                      # sdist 内容控制
└── release.sh                       # 发版一键脚本
```

---

## 四、各配置文件详解

### 4.1 `pyproject.toml` — 项目元数据 + 构建系统

```toml
[project]
name = "aukeys-opscli"        # PyPI 包名，pip install aukeys-opscli
version = "0.0.32"            # 当前版本，由 release.sh 自动更新
description = "Aukeys 运营 CLI 工具集"
readme = "README.md"
requires-python = ">=3.10"    # 支持的最低 Python 版本，影响 CIBW_BUILD 范围

dependencies = [              # 运行时依赖（用户 pip install 时自动安装）
    "typer>=0.12",
    "httpx>=0.27",
    "cryptography>=38",
    "rich>=13",
    "keyring>=25",
    "fastmcp>=2.0",
]

[project.scripts]
opscli     = "opscli.cli:app"       # CLI 入口：opscli 命令
opscli-mcp = "opscli.mcp.server:run" # MCP 服务入口

[build-system]
# 关键：从 hatchling 切换为 setuptools + Cython
# hatchling 不支持 C 扩展编译，必须换 setuptools
requires = ["setuptools>=68", "wheel", "cython>=3"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
# 告诉 setuptools 从当前目录查找包，只包含 opscli 及其子包
# 不配置此项会导致 setuptools 找不到包或包含多余目录
where = ["."]
include = ["opscli*"]
```

**关键参数说明：**

| 参数 | 作用 |
|------|------|
| `build-system.requires` | 构建时依赖（仅 CI 环境需要，不影响用户安装） |
| `build-backend = "setuptools.build_meta"` | 现代 setuptools 后端，支持 `pyproject.toml` 驱动构建 |
| `tool.setuptools.packages.find` | 替代旧版 `setup.cfg` 中的 `find_packages()`，告知 setuptools 包的位置 |

---

### 4.2 `setup.py` — Cython 编译核心配置

```python
import os
import glob
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from Cython.Build import cythonize
from setuptools.extension import Extension


class BuildPyExcludeSource(build_py):
    """自定义 build_py 命令：从 wheel 中排除业务 .py 源码。

    默认情况下 setuptools 会把所有 .py 文件复制进 wheel，
    重写此方法使其只保留 __init__.py，其余由 Cython 编译的
    .so/.pyd 替代，实现 wheel 中无可读源码。
    """

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        # 只保留 __init__ 模块，其余 .py 已由 Cython 编译
        return [
            (pkg, mod, filepath)
            for pkg, mod, filepath in modules
            if mod == "__init__"
        ]


def get_extensions():
    """收集所有需要编译的 .py 文件，生成 Cython Extension 列表。"""
    py_files = glob.glob("opscli/**/*.py", recursive=True)
    extensions = []

    for f in py_files:
        f_unix = f.replace(os.sep, "/")  # 统一正斜杠，跨平台兼容

        # 排除规则1：__init__.py 保留为 .py
        # 原因：Python 包发现依赖 __init__.py；编译后无法被 import 机制识别为包
        if os.path.basename(f) == "__init__.py":
            continue

        # 排除规则2：skills/templates/ 下的独立脚本不编译
        # 原因：这些脚本安装到用户目录后由用户直接执行，不作为 Python 模块导入
        if "opscli/skills/templates/" in f_unix:
            continue

        # 路径转模块名：opscli/auth/cli.py → opscli.auth.cli
        module_name = f_unix.replace("/", ".")[:-3]
        extensions.append(Extension(module_name, [f]))

    return cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",   # 使用 Python 3 语法解析
            "boundscheck": False,    # 关闭列表/数组边界检查（提升性能，生产安全）
            "wraparound": False,     # 关闭负索引自动包装（提升性能）
        },
        nthreads=4,                  # 并行编译线程数（加速多文件编译）
    )


setup(
    ext_modules=get_extensions(),   # 注册 Cython 扩展
    packages=find_packages(),        # 自动发现所有子包
    package_data={
        # skills/templates 下的非 Python 文件需原样打包进 wheel
        # 包括：SKILL.md、VERSION.json、references/*.md、scripts/*.py（独立脚本）
        "opscli": [
            "skills/templates/**/*",
            "skills/templates/**/**/*",
        ],
    },
    cmdclass={"build_py": BuildPyExcludeSource},  # 注入自定义构建命令
)
```

**`cythonize` 编译选项说明：**

| 参数 | 值 | 说明 |
|------|----|------|
| `language_level` | `"3"` | 按 Python 3 语法解析源文件，必须设置 |
| `boundscheck` | `False` | 关闭列表/数组访问越界检查，生产环境可关闭 |
| `wraparound` | `False` | 关闭 `a[-1]` 负索引自动转正，不使用负索引时可关闭 |
| `nthreads` | `4` | 并行编译 `.pyx` 文件数，加速大项目编译 |

**`BuildPyExcludeSource` 工作原理：**

```
默认 setuptools 行为：
  wheel 内容 = __init__.py + cli.py + token_manager.py + .so/.pyd

重写后行为：
  wheel 内容 = __init__.py + .so/.pyd
  （业务 .py 被过滤，用户只能看到 __init__.py 和二进制文件）
```

---

### 4.3 `MANIFEST.in` — sdist 内容控制

```
# sdist 内容控制：只包含构建所需最少文件，不含可读业务源码
include pyproject.toml    # 构建系统配置（必须）
include setup.py          # Cython 编译配置（必须）
include README.md         # 项目说明

# 保留所有 __init__.py（从 sdist 重新编译时 Cython 需要包结构）
recursive-include opscli __init__.py

# Skill 模板数据原样保留（非编译对象，用户安装后直接使用）
recursive-include opscli/skills/templates *

# 明确排除业务 .py 源码
recursive-exclude opscli *.py
# 上面的 exclude 会把 __init__.py 也排除，再次 include 恢复
recursive-include opscli __init__.py
```

**MANIFEST.in 规则优先级说明：**

`MANIFEST.in` 按从上到下顺序处理，**后面的规则可以覆盖前面的规则**。
因此 `recursive-exclude *.py` 之后再 `recursive-include __init__.py` 是有效的。

| 指令 | 说明 |
|------|------|
| `include <file>` | 包含根目录下的指定文件 |
| `recursive-include <dir> <pattern>` | 递归包含目录下匹配 pattern 的文件 |
| `recursive-exclude <dir> <pattern>` | 递归排除目录下匹配 pattern 的文件 |

---

### 4.4 `.github/workflows/build-and-publish.yml` — CI/CD 流水线

```yaml
name: Build and Publish to PyPI

on:
  push:
    tags:
      - "v*"          # 触发条件：推送以 v 开头的 Tag，如 v0.0.32
  workflow_dispatch:  # 允许在 GitHub 页面手动触发（调试用）

jobs:
  build_wheels:
    name: Build wheels on ${{ matrix.os }}
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false   # 一个平台构建失败不取消其他平台（确保最大覆盖）
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]  # 三平台并行

    steps:
      - uses: actions/checkout@v4       # 拉取源码

      - uses: actions/setup-python@v5   # 安装 Python（cibuildwheel 宿主环境用）
        with:
          python-version: "3.11"

      - name: Build wheels (cibuildwheel)
        uses: pypa/cibuildwheel@v2.19.0  # 核心：多 Python 版本 wheel 构建工具
        env:
          # 构建目标：CPython 3.10/3.11/3.12/3.13，与 requires-python>=3.10 对齐
          # cp = CPython，* 匹配所有平台后缀（manylinux/win_amd64/macosx 等）
          CIBW_BUILD: "cp310-* cp311-* cp312-* cp313-*"

          # 跳过规则（Linux 专用）
          # *-manylinux_i686：32 位 Linux，现代服务器基本不用
          # *-musllinux*：Alpine Linux（musl libc），与 glibc wheel 不兼容
          CIBW_SKIP: "*-manylinux_i686 *-musllinux*"

          # macOS 同时编译两种 CPU 架构
          # x86_64：Intel Mac（老款）
          # arm64：Apple Silicon M1/M2/M3
          CIBW_ARCHS_MACOS: "x86_64 arm64"

          # 每个 wheel 构建环境内、编译前执行
          # 安装 Cython 和 setuptools（setup.py 的运行依赖）
          CIBW_BEFORE_BUILD: "pip install cython>=3 setuptools>=68 wheel"

          # wheel 构建完成后的冒烟测试：验证包能正常导入
          CIBW_TEST_COMMAND: >
            python -c "import opscli; from opscli import AuthClient; print('import ok')"

      - uses: actions/upload-artifact@v4
        with:
          name: wheels-${{ matrix.os }}   # 每个平台单独存储，防止文件名冲突
          path: ./wheelhouse/*.whl         # cibuildwheel 默认输出到 wheelhouse/
          retention-days: 7               # 7 天后自动清理（减少存储占用）

  build_sdist:
    name: Build source distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install build cython>=3 setuptools>=68
      - run: python -m build --sdist     # 只构建 sdist，不构建 wheel（wheel 由上面的 job 负责）
      - uses: actions/upload-artifact@v4
        with:
          name: sdist
          path: dist/*.tar.gz
          retention-days: 7

  publish:
    name: Publish to PyPI
    needs: [build_wheels, build_sdist]   # 依赖两个构建 job 全部成功才执行
    runs-on: ubuntu-latest

    steps:
      - name: Download all wheel artifacts
        uses: actions/download-artifact@v4
        with:
          pattern: "wheels-*"      # 匹配三个平台的 artifact
          merge-multiple: true     # 合并到同一目录（dist/）
          path: dist/

      - name: Download sdist artifact
        uses: actions/download-artifact@v4
        with:
          name: sdist
          path: dist/

      - run: ls -lh dist/          # 打印所有产物，便于排查问题

      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          # 读取 GitHub Secret PYPI_API_TOKEN
          # 配置路径：仓库 Settings → Secrets and variables → Actions → New repository secret
          password: ${{ secrets.PYPI_API_TOKEN }}
```

**cibuildwheel 核心参数说明：**

| 环境变量 | 示例值 | 说明 |
|----------|--------|------|
| `CIBW_BUILD` | `"cp310-* cp311-* cp312-* cp313-*"` | 构建哪些 Python 版本的 wheel，`cp` = CPython |
| `CIBW_SKIP` | `"*-manylinux_i686 *-musllinux*"` | 跳过哪些构建目标（节省时间） |
| `CIBW_ARCHS_MACOS` | `"x86_64 arm64"` | macOS 同时产出两种架构的 wheel |
| `CIBW_BEFORE_BUILD` | `"pip install cython>=3 ..."` | 每次 wheel 构建前在构建容器内执行 |
| `CIBW_TEST_COMMAND` | `"python -c ..."` | wheel 构建后的验证命令，失败则整个构建失败 |

**预期产物（每次发版约 16~20 个文件）：**

```
aukeys_opscli-0.0.32-cp310-cp310-manylinux_x86_64.whl
aukeys_opscli-0.0.32-cp311-cp311-manylinux_x86_64.whl
aukeys_opscli-0.0.32-cp312-cp312-manylinux_x86_64.whl
aukeys_opscli-0.0.32-cp313-cp313-manylinux_x86_64.whl
aukeys_opscli-0.0.32-cp310-cp310-win_amd64.whl
aukeys_opscli-0.0.32-cp311-cp311-win_amd64.whl
aukeys_opscli-0.0.32-cp312-cp312-win_amd64.whl
aukeys_opscli-0.0.32-cp313-cp313-win_amd64.whl
aukeys_opscli-0.0.32-cp310-cp310-macosx_x86_64.whl
aukeys_opscli-0.0.32-cp311-cp311-macosx_x86_64.whl
aukeys_opscli-0.0.32-cp312-cp312-macosx_arm64.whl
aukeys_opscli-0.0.32-cp313-cp313-macosx_arm64.whl
... （共约 16~20 个 wheel）
aukeys_opscli-0.0.32.tar.gz   （sdist 兜底）
```

---

### 4.5 `release.sh` — 发版脚本（支持两种模式）

脚本支持 `--no-tag` 可选参数，满足"只同步代码、不触发发版"的场景。

**两种模式对比：**

| 模式 | 命令 | 行为 |
|------|------|------|
| 完整发版 | `./release.sh 0.0.33` | 更新版本 → commit → 打 tag → 双端推送 → 触发 Actions → 发布 PyPI |
| 仅同步代码 | `./release.sh 0.0.33 --no-tag` | 更新版本 → commit → 双端推送，**不打 tag，Actions 不触发** |

**适用场景：**
- `--no-tag`：基础设施改动（CI 配置、文档、脚本）只需同步代码，无需发版；
  或发版前先同步代码让团队 review，确认后再单独打 tag 触发发版。

```bash
#!/bin/bash
# 使用方式：
#   ./release.sh 0.0.33              完整发版：打 Tag + 触发 Actions 发布 PyPI
#   ./release.sh 0.0.33 --no-tag    仅同步：提交 + 推送，不打 Tag，不触发 Actions
set -e

VERSION=$1
NO_TAG=false

# ── 参数解析：支持 --no-tag 放在任意位置 ─────────────────
for arg in "$@"; do
  case "$arg" in
    --no-tag) NO_TAG=true ;;
  esac
done

# ── 参数校验 ──────────────────────────────────────────────
# 格式校验：必须是 x.y.z 三段式
if [ -z "$VERSION" ] || [[ "$VERSION" == --* ]]; then
  echo "用法："
  echo "  ./release.sh <version>           完整发版（打 Tag + 触发 PyPI 发布）"
  echo "  ./release.sh <version> --no-tag  仅同步代码（不打 Tag，不触发 Actions）"
  exit 1
fi

if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "❌ 版本号格式错误，应为 x.y.z"
  exit 1
fi

# 防重复：仅完整发版模式检查 tag 是否已存在
# --no-tag 模式可重复执行同一版本（用于多次推送基础设施改动）
if [ "$NO_TAG" = false ] && git rev-parse "v$VERSION" >/dev/null 2>&1; then
  echo "❌ Tag v$VERSION 已存在，请检查版本号"
  exit 1
fi

# 分支检查：只允许在 master 分支操作
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "master" ]; then
  echo "❌ 请切换到 master 分支再执行"
  exit 1
fi

# ── 第一步：拉取最新代码（包含所有同事的提交）────────────
git pull origin master

# ── 第二步：更新版本号 ────────────────────────────────────
# 用 Python 而非 sed，原因：
# - macOS sed -i 与 Linux 语法不同（macOS 需要 sed -i ''），Python 跨平台一致
# 用 argv[1] 传入版本号而非 heredoc 变量展开，原因：
# - <<'PYEOF'（单引号）阻止 shell 变量展开，$VERSION 不会被替换
# - 必须通过 sys.argv[1] 从 shell 接收版本号
python3 - "$VERSION" <<'PYEOF'
import re, sys
VERSION = sys.argv[1]

with open("pyproject.toml", "r") as f:
    content = f.read()
content = re.sub(r'^version = ".*"', f'version = "{VERSION}"', content, flags=re.MULTILINE)
with open("pyproject.toml", "w") as f:
    f.write(content)

with open("opscli/version.py", "r") as f:
    content = f.read()
content = re.sub(r'^FALLBACK_VERSION = ".*"', f'FALLBACK_VERSION = "{VERSION}-dev"', content, flags=re.MULTILINE)
with open("opscli/version.py", "w") as f:
    f.write(content)
PYEOF

# commit message 按模式区分，便于 git log 区分发版提交和同步提交
if [ "$NO_TAG" = true ]; then
  git add pyproject.toml opscli/version.py
  git commit -m "chore: 同步版本号至 v$VERSION（不发版）"
else
  git add pyproject.toml opscli/version.py
  git commit -m "release: 发布 v$VERSION"
fi

# ── 第三步：推送到 GitLab + GitHub ────────────────────────
git push origin master    # GitLab：保持主仓库同步
git push github master    # GitHub：同步代码

if [ "$NO_TAG" = true ]; then
  # --no-tag 模式：只推代码，不推 tag，Actions 不触发
  echo "✅ 同步完成！代码已推送到 GitLab 和 GitHub（未触发 Actions）"
else
  # 完整发版：打 tag 并推送，触发 Actions → 发布 PyPI
  git tag "v$VERSION" -m "Release v$VERSION"
  git push origin "v$VERSION"   # GitLab：同步 tag
  git push github "v$VERSION"   # GitHub：推送 tag → 触发 Actions

  echo "✅ 发版完成！GitHub Actions 开始构建，约 15~20 分钟后发布到 PyPI"
  echo "   构建进度：https://github.com/pengjianchao250/open-opscli/actions"
fi
```

**`--no-tag` 设计要点：**

| 细节 | 说明 |
|------|------|
| 参数位置灵活 | `for arg in "$@"` 遍历所有参数，`--no-tag` 可放第二位或更后 |
| tag 重复检查跳过 | `--no-tag` 时不检查 tag 是否存在，允许同版本号多次推送 |
| commit message 区分 | 完整发版用 `release:`，同步用 `chore:`，git log 一眼可辨 |
| Actions 触发原理 | workflow 的 `on.push.tags: v*` 只响应 tag push，不推 tag 则不触发 |

---

## 五、一次性配置步骤（首次接入时操作）

### 5.1 本地 Git 配置（发版人执行一次）

```bash
# 添加 GitHub 为第二个 remote（发版人执行一次）
git remote add github git@github.com:<username>/<repo>.git

# 若遇到 SSH URL 被全局重写为 HTTPS 的问题，检查并删除全局规则
git config --global --list | grep insteadOf
# 若存在 url.https://github.com/.insteadof=git@github.com: 则删除：
git config --global --unset url.https://github.com/.insteadOf

# 修复 SSH 私钥权限（权限过宽 GitHub 会拒绝）
chmod 600 ~/.ssh/id_rsa

# 验证 SSH 连通性
ssh -T git@github.com
# 预期输出：Hi <username>! You've successfully authenticated...
```

### 5.2 GitHub Secret 配置

```
GitHub 仓库页面 → Settings → Secrets and variables → Actions
→ New repository secret

Name:  PYPI_API_TOKEN
Value: pypi-xxxx...（从 pypi.org 生成的 token）
```

**PyPI Token 生成步骤：**
1. 登录 pypi.org → Account settings → API tokens
2. Add API token → Token name 填写用途（如 `github-actions`）
3. Scope 选 `Entire account`（首次发布前项目不存在，只能选全账号）
4. 复制 token（只显示一次）

### 5.3 PyPI Token 权限要求

| 场景 | Token Scope |
|------|------------|
| 首次发布（项目不存在） | Entire account |
| 项目已存在后 | 具体项目（更安全） |

---

## 六、常规发版流程（日常操作）

### 6.1 完整发版（正式上线）

```bash
# 确保在 master 分支
git checkout master

# 一条命令完成全部发版操作
./release.sh 0.0.33
```

脚本内部自动完成：
1. `git pull origin master`（拉取所有人最新提交）
2. 更新 `pyproject.toml version` + `opscli/version.py FALLBACK_VERSION`
3. `git commit -m "release: 发布 v0.0.33"`
4. `git tag v0.0.33`
5. `git push origin master + v0.0.33`（GitLab）
6. `git push github master + v0.0.33`（GitHub → 触发 Actions → 发布 PyPI）

**Actions 构建进度查看：**
```
https://github.com/<username>/<repo>/actions
```

**Actions 完成后验证：**
```bash
pip install aukeys-opscli==0.0.33
opscli --version
```

### 6.2 仅同步代码（不触发发版）

适用场景：CI 配置调整、文档更新、基础设施改动，只需双端同步，无需发版。

```bash
./release.sh 0.0.33 --no-tag
```

脚本内部自动完成：
1. `git pull origin master`
2. 更新版本号文件
3. `git commit -m "chore: 同步版本号至 v0.0.33（不发版）"`
4. `git push origin master`（GitLab）
5. `git push github master`（GitHub，**不推 tag，Actions 不触发**）

### 6.3 两种模式决策参考

```
改动类型？
  ├── 业务功能 / Bug 修复 → ./release.sh <version>        （完整发版）
  ├── CI/CD 配置调整      → ./release.sh <version> --no-tag（验证后再发版）
  ├── 文档 / 脚本更新     → ./release.sh <version> --no-tag
  └── 先同步给团队 review → ./release.sh <version> --no-tag → review 通过后打 tag
```

---

## 七、编译边界说明

| 文件类型 | 处理方式 | 原因 |
|----------|----------|------|
| `opscli/**/*.py`（非 `__init__`） | Cython 编译 → `.so`/`.pyd` | 核心业务逻辑，需要保护 |
| `opscli/**/__init__.py` | 保留为 `.py` | Python 包发现依赖 `__init__.py`；编译后无法被识别为包 |
| `skills/templates/**/*.py` | 原样打包 | 独立脚本，用户安装到本地后直接执行，不作为模块导入 |
| `skills/templates/**/*.*` | 原样打包 | SKILL.md、VERSION.json 等数据文件 |

---

## 八、常见问题排查

### Q1：push 报 `Repository not found`

**可能原因：**
1. GitHub 仓库尚未创建 → 先去 GitHub 创建空仓库
2. HTTPS 认证失败（token 过期或无权限）→ 检查 token
3. 全局 git 配置强制将 SSH 转 HTTPS → 检查 `git config --global --list | grep insteadOf`

**解决：**
```bash
# 检查并删除 URL 重写规则
git config --global --unset url.https://github.com/.insteadOf
# 修复 SSH 密钥权限
chmod 600 ~/.ssh/id_rsa
```

### Q2：GitHub Token push 报 `refusing to allow ... without workflow scope`

项目含 `.github/workflows/` 文件，推送需要 `workflow` 权限。

**解决：** 重新生成 token，勾选 `repo` + `workflow` 两个权限。

### Q3：Actions 构建失败，报 Cython 找不到

`CIBW_BEFORE_BUILD` 未正确安装 Cython。

**检查：** 确认 workflow 中 `CIBW_BEFORE_BUILD: "pip install cython>=3 setuptools>=68 wheel"` 存在。

### Q4：wheel 中仍然包含 .py 源码

`BuildPyExcludeSource` 未正确注入。

**检查：** `setup.py` 末尾的 `cmdclass={"build_py": BuildPyExcludeSource}` 是否存在。

### Q5：`skills/templates` 下的文件未被打包进 wheel

`package_data` 配置有误或 `**` glob 不生效。

**解决：** 在 `setup.py` 中同时列出两层深度：
```python
package_data={
    "opscli": [
        "skills/templates/**/*",
        "skills/templates/**/**/*",
    ],
}
```

---

## 九、费用说明

| 资源 | 费用 |
|------|------|
| GitHub 私有仓库 | 免费（无限制） |
| GitHub Actions（私有仓库） | 每月 2000 分钟免费额度 |
| 每次构建耗时 | 约 15~20 分钟（三平台并行） |
| 每月可免费发版次数 | 约 100 次 |
| PyPI 托管 | 免费 |
| **总费用** | **$0** |

---

## 十、安全性说明

| 环节 | 源码是否可见 |
|------|------------|
| GitLab 私有仓库 | 仅授权人可见 |
| GitHub 私有仓库 | 仅授权人可见 |
| GitHub Actions 运行日志 | 不含源码，仅构建输出 |
| PyPI 发布的 wheel | 仅二进制 `.so`/`.pyd`，无 Python 源码 |
| PyPI 发布的 sdist | 仅含 `__init__.py` + 模板数据，业务逻辑已排除 |
| `PYPI_API_TOKEN` | 存储在 GitHub Secret，不出现在代码和日志中 |

> **注意：** Cython 编译的二进制理论上可被逆向工程还原伪代码，
> 但难度远高于直接读取 `.py`，足以应对绝大多数商业保护场景。

---

## 十一、版本演进建议

| 当前做法 | 升级方向 | 何时考虑 |
|----------|----------|----------|
| PyPI API Token | OIDC Trusted Publisher（无 token） | 安全要求更高时 |
| 手动执行 release.sh | GitLab CI 自动触发（需升级 GitLab EE 或配置 Runner） | 团队规模扩大时 |
| 全量 Cython 编译 | 按模块选择性编译 | 编译耗时影响 CI 效率时 |
| master 单分支 | main + release 分支策略 | 需要多版本维护时 |
