# ops-skills

管理 Claude Code / OpenClaw 中已安装的 Skill 生命周期，所有操作通过 `opscli skills` 子命令执行。

## 使用原则

- 安装目标由 opscli 自动检测（`.claude/skills` 或 `.openclaw/skills`），也可通过 `--runtime` 或 `--skills-dir` 显式指定
- 只有 `ops-dataset-query` 支持远端数据升级；`ops-auth` 和 `ops-skills` 为本地静态 Skill，无需升级

## 内置可安装 Skill

| Skill 名称 | 说明 | 支持远端升级 |
|-----------|------|------------|
| `ops-auth` | 认证授权管理（登录、Token 操作） | 否 |
| `ops-dataset-query` | 数据集字段索引与查询转发 | 是 |
| `ops-skills` | Skill 生命周期管理（本 Skill） | 否 |

---

## 命令参考

### `opscli skills list`

列出所有已安装的 Skill（扫描 `.claude/skills` 和 `.openclaw/skills`）。

```
选项：
  --skills-dir TEXT   指定扫描目录（覆盖默认检测路径）
  --pretty            格式化 JSON 输出
```

```bash
opscli skills list
opscli skills list --pretty
```

---

### `opscli skills status`

查看已安装 Skill 的状态，包含本地版本与远端最新版本对比（需联网）。

```
选项：
  --skills-dir TEXT   指定扫描目录
  --pretty            格式化 JSON 输出
```

```bash
opscli skills status
opscli skills status --pretty
```

---

### `opscli skills install <name>`

从内置模板安装指定 Skill 到本地运行时目录。自动检测当前目录下的 AI 工具（`.claude` / `.openclaw`），若检测到多个会交互选择。

```
参数：
  name                Skill 名称（必填）

选项：
  --runtime TEXT      目标运行时：claude、openclaw、all，或逗号分隔多个值
  --skills-dir TEXT   指定安装目录（跳过自动检测）
  --force             覆盖已存在的安装
  --pretty            格式化 JSON 输出
```

```bash
# 安装（自动检测运行时）
opscli skills install ops-auth
opscli skills install ops-dataset-query
opscli skills install ops-skills

# 指定运行时安装
opscli skills install ops-auth --runtime claude
opscli skills install ops-auth --runtime openclaw
opscli skills install ops-auth --runtime claude,openclaw

# 同时安装到所有运行时
opscli skills install ops-auth --runtime all

# 覆盖已存在的安装
opscli skills install ops-dataset-query --force

# 安装到指定目录
opscli skills install ops-auth --skills-dir /path/to/skills
```

---

### `opscli skills upgrade [name]`

升级 Skill 到远端最新版本（当前仅 `ops-dataset-query` 支持）。会先对比版本号，相同时跳过，不同时拉取远端数据并原子替换本地文件。

```
参数：
  name                Skill 名称（可选，默认 ops-dataset-query）

选项：
  --skills-dir TEXT   指定扫描目录
  --force             强制重新拉取，即使版本号相同
  --pretty            格式化 JSON 输出
```

```bash
# 升级 ops-dataset-query（默认）
opscli skills upgrade

# 显式指定名称
opscli skills upgrade ops-dataset-query

# 强制重新拉取远端数据
opscli skills upgrade ops-dataset-query --force
```

---

## 典型工作流

```bash
# 1. 查看当前安装状态
opscli skills list --pretty

# 2. 安装所有常用 Skill
opscli skills install ops-auth
opscli skills install ops-dataset-query
opscli skills install ops-skills

# 3. 检查是否有可用更新
opscli skills status --pretty

# 4. 升级有更新的 Skill
opscli skills upgrade ops-dataset-query
```
