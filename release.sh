#!/bin/bash
# 发版脚本：拉取最新代码 → 更新版本号 → 打 Tag → 双端推送（GitLab + GitHub）
# 使用方式：./release.sh 0.0.32
set -e  # 任何步骤失败立即停止

VERSION=$1

# ── 参数校验 ──────────────────────────────────────────────
if [ -z "$VERSION" ]; then
  echo "❌ 请输入版本号，例如: ./release.sh 0.0.32"
  exit 1
fi

if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "❌ 版本号格式错误，应为 x.y.z，例如: 0.0.32"
  exit 1
fi

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
  echo "❌ Tag v$VERSION 已存在，请检查版本号"
  exit 1
fi

# 确认在 master 分支
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "master" ]; then
  echo "❌ 当前分支为 $CURRENT_BRANCH，请切换到 master 再执行发版"
  exit 1
fi

echo "🚀 开始发布 v$VERSION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 第一步：拉取所有人的最新提交 ──────────────────────────
echo "📥 [1/4] 拉取最新代码..."
git pull origin master

# ── 第二步：更新版本号（用 Python 保证跨平台兼容）────────
echo "✏️  [2/4] 更新版本号为 $VERSION ..."

python3 - <<PYEOF
import re

# 更新 pyproject.toml 中的 version 字段
with open("pyproject.toml", "r") as f:
    content = f.read()
content = re.sub(r'^version = ".*"', f'version = "{VERSION}"', content, flags=re.MULTILINE)
with open("pyproject.toml", "w") as f:
    f.write(content)

# 同步更新 version.py 中的 FALLBACK_VERSION（开发态 fallback）
with open("opscli/version.py", "r") as f:
    content = f.read()
content = re.sub(r'^FALLBACK_VERSION = ".*"', f'FALLBACK_VERSION = "{VERSION}-dev"', content, flags=re.MULTILINE)
with open("opscli/version.py", "w") as f:
    f.write(content)

print(f"  pyproject.toml version → {VERSION}")
print(f"  opscli/version.py FALLBACK_VERSION → {VERSION}-dev")
PYEOF

git add pyproject.toml opscli/version.py
git commit -m "release: 发布 v$VERSION"

# ── 第三步：打 Tag ─────────────────────────────────────────
echo "🏷️  [3/4] 打 Tag: v$VERSION"
git tag "v$VERSION" -m "Release v$VERSION"

# ── 第四步：推送到 GitLab + GitHub ────────────────────────
echo "📤 [4/4] 推送到 GitLab (origin) + GitHub..."
git push origin master
git push origin "v$VERSION"

git push github master
git push github "v$VERSION"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 完成！GitHub Actions 开始构建"
echo "   约 15~20 分钟后自动发布到 PyPI"
echo "   构建进度：https://github.com/pengjianchao250/open-opscli/actions"
