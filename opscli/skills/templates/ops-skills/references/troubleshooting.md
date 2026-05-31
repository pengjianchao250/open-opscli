# ops-skills 错误排查

## 安装失败：运行时未检测到

```
错误：未检测到任何已安装的 AI 工具运行时
```

**原因**：全局路径均不存在（如 `~/.claude/` 不存在）。

```bash
# 方式 1：使用 --runtime 显式指定（opscli 自动创建目录）
opscli skills install ops-auth --runtime claude

# 方式 2：手动创建目录后重试
mkdir -p ~/.claude/skills/
opscli skills install ops-auth
```

---

## 安装失败：Skill 已存在

```
错误：Skill ops-auth 已存在于 ~/.claude/skills/ops-auth
```

```bash
opscli skills install ops-auth --force
```

---

## 远程安装失败：标识符格式错误

```
错误：无效的 Skill 标识符: "ops-auth"，应为 username@skill_name 格式
```

**原因**：广场远程安装必须用 `username@skill_name`（如 `pengjianchao@ops-auth`）；内置模板安装直接用名称（不含 `@`）。

---

## 发布失败：VERSION.json 格式错误

```
错误：data/VERSION.json 中 name 字段不能为空
```

确认 `data/VERSION.json` 格式：

```json
{
  "name": "ops-auth",
  "version": "1.0.0"
}
```

> `version` 字段**不要**带 `v` 前缀（写 `"1.0.0"` 而非 `"v1.0.0"`）。

---

## 升级失败：网络不可达

```
错误：无法连接到远端服务，请检查网络连接
```

```bash
opscli auth token status    # 检查认证状态
opscli auth doctor          # 检查网络连通性
opscli skills upgrade ops-dataset-query  # 网络恢复后重试
```

---

## 升级失败：Token 过期

```
错误：认证 Token 已过期，请重新登录
```

```bash
opscli auth token refresh --all    # 优先刷新
opscli auth login                  # 刷新失败时重新登录
opscli skills upgrade ops-dataset-query
```

---

## 发布/编辑失败：版本号不一致

**常见原因：**
- `data/VERSION.json` 未更新，与广场版本号不一致
- `SKILL.md` frontmatter `version` 未同步
- `--version` 参数与 `VERSION.json` 中版本号不匹配

**检查清单：**

```
data/VERSION.json: "1.8.0"（无 v）
SKILL.md frontmatter: "1.8.0"（无 v）
--version 参数: "1.8.0"（无 v，仅 edit 时）
→ 三者必须完全相同，全部不带 v 前缀
```
