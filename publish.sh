#!/usr/bin/env bash
# 一键升级版本号并发布到 PyPI（发布成功后自动提交版本文件并打 git tag）
# 用法：
#   ./publish.sh patch          # 0.3.0 → 0.3.1，发布到 TestPyPI（默认）
#   ./publish.sh minor          # 0.3.0 → 0.4.0，发布到 TestPyPI（默认）
#   ./publish.sh major          # 0.3.0 → 1.0.0，发布到 TestPyPI（默认）
#   ./publish.sh patch test     # 显式指定 TestPyPI
#   ./publish.sh patch prod     # 发布到正式 PyPI（需二次确认）
#   ./publish.sh                # 默认 patch + TestPyPI
# 说明：
#   每次发布成功后会提交 pyproject.toml + opscli/version.py 并创建 tag v<新版本>，
#   tag 默认只在本地创建，是否推送到远端由交互确认决定。

set -euo pipefail

PYPROJECT="pyproject.toml"
BUMP_TYPE="${1:-patch}"
TARGET="${2:-test}"

# ── 颜色输出 ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }

# ── 参数校验 ──────────────────────────────────────────────
[[ "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]] \
    || error "第一个参数必须是 patch / minor / major，当前：$BUMP_TYPE"
[[ "$TARGET" =~ ^(test|prod)$ ]] \
    || error "第二个参数必须是 test / prod，当前：$TARGET"

# ── 读取当前版本 ──────────────────────────────────────────
CURRENT_VERSION=$(grep -m1 '^version = ' "$PYPROJECT" | sed 's/version = "\(.*\)"/\1/')
[[ -n "$CURRENT_VERSION" ]] || error "无法从 $PYPROJECT 读取 version 字段"

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# ── 计算新版本 ────────────────────────────────────────────
case "$BUMP_TYPE" in
    patch) PATCH=$((PATCH + 1)) ;;
    minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
    major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
TAG_NAME="v${NEW_VERSION}"

# ── git 前置检查 ──────────────────────────────────────────
# 提前校验 git 环境和 tag 冲突，避免构建上传完成后才发现无法打 tag
command -v git &>/dev/null || error "未找到 git，无法在发布后打 tag"
git rev-parse --is-inside-work-tree &>/dev/null || error "当前目录不是 git 仓库，无法在发布后打 tag"
if git rev-parse -q --verify "refs/tags/${TAG_NAME}" &>/dev/null; then
    error "tag ${TAG_NAME} 已存在，请先处理冲突（git tag -d ${TAG_NAME}）后重试"
fi

echo -e "\n${BOLD}======================================${RESET}"
echo -e "${BOLD} aukeys-opscli 发布脚本${RESET}"
echo -e "${BOLD}======================================${RESET}"
echo -e "  当前版本：${YELLOW}${CURRENT_VERSION}${RESET}"
echo -e "  新版本  ：${GREEN}${NEW_VERSION}${RESET}  (${BUMP_TYPE})"
echo -e "  发布 tag：${GREEN}${TAG_NAME}${RESET}"
if [[ "$TARGET" == "prod" ]]; then
    echo -e "  发布目标：${RED}正式 PyPI${RESET}"
else
    echo -e "  发布目标：${BLUE}TestPyPI${RESET}"
fi
echo -e "${BOLD}======================================${RESET}\n"

read -rp "确认发布？[y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "已取消"; exit 0; }

# 正式 PyPI 二次确认，防止误操作
if [[ "$TARGET" == "prod" ]]; then
    echo ""
    warn "即将发布到 ${RED}正式 PyPI${RESET}，此操作不可撤销！"
    read -rp "再次确认发布到正式 PyPI？[y/N] " CONFIRM2
    [[ "$CONFIRM2" =~ ^[Yy]$ ]] || { warn "已取消"; exit 0; }
fi

# ── Step 1: 检查工具 ──────────────────────────────────────
info "Step 1/8  检查依赖工具..."
command -v python3 &>/dev/null || error "未找到 python3"
python3 -c "import build"   2>/dev/null || { warn "正在安装 build..."; pip install build -q; }
python3 -c "import twine"   2>/dev/null || { warn "正在安装 twine..."; pip install twine -q; }
success "工具检查通过"

# ── Step 2: 更新版本号 ────────────────────────────────────
VERSION_PY="opscli/version.py"
info "Step 2/8  更新版本号 → ${NEW_VERSION}..."
# 更新 pyproject.toml
sed -i.bak "s/^version = \"${CURRENT_VERSION}\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT"
rm -f "${PYPROJECT}.bak"
# 同步更新 version.py 的 FALLBACK_VERSION
sed -i.bak "s/^FALLBACK_VERSION = \".*\"/FALLBACK_VERSION = \"${NEW_VERSION}-dev\"/" "$VERSION_PY"
rm -f "${VERSION_PY}.bak"
success "pyproject.toml + version.py 版本号已更新"

# ── Step 3: 清理旧产物 ────────────────────────────────────
info "Step 3/8  清理旧构建产物..."
rm -rf dist/ build/ *.egg-info/
if [[ "$TARGET" == "test" ]]; then
    # 清理 Cython 编译产物，避免 .c 文件干扰纯 Python 构建
    find opscli -name '*.c' -not -path '*/templates/*' -delete 2>/dev/null
    find opscli -name '*.so' -not -path '*/templates/*' -delete 2>/dev/null
fi
success "清理完成"

# ── Step 4: 构建 ──────────────────────────────────────────
if [[ "$TARGET" == "test" ]]; then
    info "Step 4/8  构建纯 Python 包（跳过 Cython 编译）..."
    # --sdist --wheel：分别独立从源码构建，避免默认的 "wheel from sdist" 模式
    # 默认模式会先打 sdist 再从 sdist 构建 wheel，导致 Cython 产物干扰文件发现
    SKIP_CYTHON=1 python3 -m build --sdist --wheel
else
    info "Step 4/8  构建包（含 Cython 编译）..."
    python3 -m build
fi
success "构建完成"
echo "  生成文件："
ls dist/ | sed 's/^/    /'

# ── Step 5: 校验 ──────────────────────────────────────────
info "Step 5/8  校验包（twine check）..."
twine check dist/*
success "校验通过"

# ── Step 6: 上传到 PyPI ───────────────────────────────────
if [[ "$TARGET" == "prod" ]]; then
    info "Step 6/8  上传到正式 PyPI..."
    twine upload dist/*
    success "上传完成！"
    echo -e "  查看地址：${BLUE}https://pypi.org/project/aukeys-opscli/${NEW_VERSION}/${RESET}"
else
    info "Step 6/8  上传到 TestPyPI..."
    twine upload --repository testpypi dist/*
    success "上传完成！"
    echo -e "  查看地址：${BLUE}https://test.pypi.org/project/aukeys-opscli/${NEW_VERSION}/${RESET}"
fi

# ── Step 7: 提交版本文件并打 tag ──────────────────────────
# 放在上传成功之后执行：只有真正发布出去的版本才会留下 tag，
# 上传失败时 set -e 会提前终止，不会产生错误的发布标记
info "Step 7/8  提交版本文件并创建 tag ${TAG_NAME}..."
# 只提交本次脚本改动的两个版本文件，不影响工作区其他未提交内容
git commit -m "🔖 chore(release): ${TAG_NAME} (${TARGET})" -- "$PYPROJECT" "$VERSION_PY"
# 附注 tag，消息中记录发布目标，便于区分 TestPyPI 和正式 PyPI 版本
git tag -a "$TAG_NAME" -m "Release ${TAG_NAME} (${TARGET})"
success "已创建 tag ${TAG_NAME}（指向版本提交）"

# tag 默认只留在本地，推送到远端需要用户显式确认
read -rp "是否推送 tag ${TAG_NAME} 到远端？[y/N] " PUSH_TAG
if [[ "$PUSH_TAG" =~ ^[Yy]$ ]]; then
    git push origin "$TAG_NAME"
    success "tag ${TAG_NAME} 已推送到远端"
else
    warn "tag 未推送，稍后可手动执行：git push origin ${TAG_NAME}"
fi

# ── Step 8: 完成提示 ──────────────────────────────────────
echo ""
info "Step 8/8  安装验证命令（可选，手动执行）："
if [[ "$TARGET" == "prod" ]]; then
    echo "    pip install aukeys-opscli==${NEW_VERSION}"
else
    echo "    pip install -i https://test.pypi.org/simple/ aukeys-opscli==${NEW_VERSION}"
fi
echo "    opscli --version"
echo ""
if [[ "$TARGET" == "prod" ]]; then
    success "全部完成 aukeys-opscli v${NEW_VERSION} 已发布到正式 PyPI"
else
    success "全部完成 aukeys-opscli v${NEW_VERSION} 已发布到 TestPyPI"
fi
