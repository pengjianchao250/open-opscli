#!/usr/bin/env bash
# 一键升级版本号并发布到 PyPI
# 用法：
#   ./publish.sh patch     # 0.3.0 → 0.3.1（Bug 修复）
#   ./publish.sh minor     # 0.3.0 → 0.4.0（新功能）
#   ./publish.sh major     # 0.3.0 → 1.0.0（破坏性变更）
#   ./publish.sh           # 默认 patch

set -euo pipefail

PYPROJECT="pyproject.toml"
BUMP_TYPE="${1:-patch}"

# ── 颜色输出 ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }

# ── 参数校验 ──────────────────────────────────────────────
[[ "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]] \
    || error "参数必须是 patch / minor / major，当前：$BUMP_TYPE"

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

echo -e "\n${BOLD}======================================${RESET}"
echo -e "${BOLD} aukeys-opscli 发布脚本${RESET}"
echo -e "${BOLD}======================================${RESET}"
echo -e "  当前版本：${YELLOW}${CURRENT_VERSION}${RESET}"
echo -e "  新版本  ：${GREEN}${NEW_VERSION}${RESET}  (${BUMP_TYPE})"
echo -e "${BOLD}======================================${RESET}\n"

read -rp "确认发布？[y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "已取消"; exit 0; }

# ── Step 1: 检查工具 ──────────────────────────────────────
info "Step 1/7  检查依赖工具..."
command -v python3 &>/dev/null || error "未找到 python3"
python3 -c "import build"   2>/dev/null || { warn "正在安装 build..."; pip install build -q; }
python3 -c "import twine"   2>/dev/null || { warn "正在安装 twine..."; pip install twine -q; }
success "工具检查通过"

# ── Step 2: 更新版本号 ────────────────────────────────────
info "Step 2/7  更新 pyproject.toml 版本号 → ${NEW_VERSION}..."
sed -i.bak "s/^version = \"${CURRENT_VERSION}\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT"
rm -f "${PYPROJECT}.bak"
success "版本号已更新"

# ── Step 3: 清理旧产物 ────────────────────────────────────
info "Step 3/7  清理旧构建产物..."
rm -rf dist/ build/ *.egg-info/
success "清理完成"

# ── Step 4: 构建 ──────────────────────────────────────────
info "Step 4/7  构建包..."
python3 -m build
success "构建完成"
echo "  生成文件："
ls dist/ | sed 's/^/    /'

# ── Step 5: 校验 ──────────────────────────────────────────
info "Step 5/7  校验包（twine check）..."
twine check dist/*
success "校验通过"

# ── Step 6: 上传到 PyPI ───────────────────────────────────
info "Step 6/7  上传到 PyPI..."
twine upload dist/*
success "上传完成！"
echo -e "  查看地址：${BLUE}https://pypi.org/project/aukeys-opscli/${NEW_VERSION}/${RESET}"

# ── Step 7: 完成提示 ──────────────────────────────────────
echo ""
info "Step 7/7  安装验证命令（可选，手动执行）："
echo "    pip install aukeys-opscli==${NEW_VERSION}"
echo "   opscli version"
echo ""
success "全部完成 aukeys-opscli v${NEW_VERSION} 已发布到 PyPI 🎉"
