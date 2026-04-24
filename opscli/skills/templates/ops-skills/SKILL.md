---
name: ops-skills
description: 管理 AI 工具中已安装的 Skill 生命周期
version: v1.0.2
---

# ops-skills

管理 Claude Code、OpenClaw、Codex CLI、OpenCode 中已安装的 Skill 生命周期，所有操作通过 `opscli skills` 子命令执行。

---

## 概述

`ops-skills` 是 Aukeys 运营工具体系的 Skill 生命周期管理器。它负责：

- **发现**：扫描全局路径，识别所有已安装的 Skill
- **安装**：从内置模板将 Skill 部署到目标运行时的全局目录
- **版本检查**：对比本地版本与远端最新版本，告知是否需要升级
- **升级**：拉取远端最新数据，原子替换本地文件，确保数据不中断

所有操作均通过 `opscli skills` 子命令完成，Skill 脚本本身不直接调用任何后端 HTTP API。

---

## 强制认证门禁

> **【强制】每次调用 `ops-skills` 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现“未登录 / 未授权 / Token 过期 / expired / 401”等状态，必须立即切换到 `ops-auth` Skill
- 若是“未登录 / 未授权 / 401”等状态，在 `ops-auth` 中执行 `opscli auth login` 完成授权登录
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh`（例如 `opscli auth token refresh --all` 或 `opscli auth token refresh -s ops`）；刷新失败或仍异常时，再执行 `opscli auth login`
- 必要时执行 `opscli auth token check -s ops` 或 `opscli auth doctor` 做确认
- 只有认证检查通过后，才允许继续执行 `opscli skills list`、`install`、`status`、`upgrade` 等后续动作
- 即使当前任务看起来只涉及本地安装或本地列表，也必须先完成这一轮登录检测

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

---

## 使用原则

- **全局路径优先**：安装目标由 opscli 自动检测全局 Skills 路径（如 `~/.claude/skills/`、`~/.openclaw/skills/` 等），也可通过 `--runtime` 或 `--skills-dir` 显式指定
- **支持的运行时**：Claude Code（`claude`）、OpenClaw（`openclaw`）、Codex CLI（`codex`）、OpenCode（`opencode`）
- **升级范围**：只有 `ops-dataset-query` 支持远端数据升级；`ops-auth` 和 `ops-skills` 为本地静态 Skill，无需升级
- **幂等安装**：默认不覆盖已存在的安装，需要 `--force` 才会覆盖
- **原子升级**：升级过程先下载到临时目录，验证完成后再替换，避免升级中途失败导致数据损坏
- **认证前置**：所有 `ops-skills` 工作流默认依赖 `ops-auth` 完成登录检测；未完成认证前，不得直接执行后续命令

---

## 内置可安装 Skill

| Skill 名称 | 说明 | 支持远端升级 |
|-----------|------|------------|
| `ops-auth` | 认证授权管理（登录、Token 查看与刷新、系统管理） | 否 |
| `ops-dataset-query` | 数据集字段索引与查询转发（支持 metadata 拉取和 query 执行） | 是 |
| `ops-amazon` | Amazon 商品页与搜索结果抓取工作流指导 | 否 |
| `ops-skills` | Skill 生命周期管理（本 Skill） | 否 |

---

## 运行时全局路径说明

opscli 检测以下全局路径来发现已安装的 Skill：

| 运行时 | 全局 Skills 路径 |
|--------|----------------|
| Claude Code | `~/.claude/skills/` |
| OpenClaw | `~/.openclaw/skills/` |
| Codex CLI | `~/.codex/skills/` |
| OpenCode | `~/.opencode/skills/` |

> 注意：检测路径为全局用户目录（`~/`），而非项目级目录。这确保 Skill 在所有项目中均可使用，无需每个项目单独安装。

若使用 `--skills-dir` 显式指定路径，将跳过自动检测逻辑，直接操作指定目录。

---

## 命令参考

### `opscli skills list`

列出所有已安装的 Skill（扫描全局路径，如 `~/.claude/skills/`、`~/.openclaw/skills/` 等）。

输出包含每个 Skill 的：
- 名称（`name`）
- 当前版本（`version`）
- 安装路径（`path`）
- 所属运行时（`runtime`）

```
选项：
  --skills-dir TEXT   指定扫描目录（覆盖默认自动检测路径）
  --pretty            格式化 JSON 输出（适合人工阅读）
```

**示例：**

```bash
# 列出所有已安装 Skill（JSON 紧凑格式）
opscli skills list

# 格式化输出，便于阅读
opscli skills list --pretty

# 仅扫描指定目录
opscli skills list --skills-dir ~/.claude/skills/
```

**典型输出：**

```json
[
  {
    "name": "ops-auth",
    "version": "v1.0.0",
    "path": "/Users/you/.claude/skills/ops-auth",
    "runtime": "claude"
  },
  {
    "name": "ops-dataset-query",
    "version": "v2.1.0",
    "path": "/Users/you/.claude/skills/ops-dataset-query",
    "runtime": "claude"
  }
]
```

---

### `opscli skills status`

查看已安装 Skill 的状态，包含本地版本与远端最新版本对比（需联网）。

输出包含每个 Skill 的：
- 名称（`name`）
- 本地版本（`local_version`）
- 远端最新版本（`remote_version`，无远端来源则为 `null`）
- 是否需要升级（`needs_upgrade`）
- 是否支持远端升级（`upgradable`）

```
选项：
  --skills-dir TEXT   指定扫描目录（覆盖默认自动检测路径）
  --pretty            格式化 JSON 输出
```

**示例：**

```bash
# 查看所有 Skill 状态
opscli skills status

# 格式化输出
opscli skills status --pretty

# 检查指定目录下的 Skill 状态
opscli skills status --skills-dir ~/.claude/skills/
```

**典型输出：**

```json
[
  {
    "name": "ops-auth",
    "local_version": "v1.0.0",
    "remote_version": null,
    "needs_upgrade": false,
    "upgradable": false
  },
  {
    "name": "ops-dataset-query",
    "local_version": "v2.0.0",
    "remote_version": "v2.1.0",
    "needs_upgrade": true,
    "upgradable": true
  },
  {
    "name": "ops-skills",
    "local_version": "v1.0.0",
    "remote_version": null,
    "needs_upgrade": false,
    "upgradable": false
  }
]
```

---

### `opscli skills install [name]`

从内置模板安装 Skill 到全局运行时目录。`name` 为可选参数：

- **不指定 name**：进入 TUI 交互模式，可勾选并批量安装全部可用 Skill
- **指定 name**：直接安装指定 Skill，跳过 TUI

自动检测全局已配置的 AI 工具（检测路径如 `~/.claude/skills/`、`~/.openclaw/skills/` 等），若检测到多个运行时会交互选择目标运行时，也可通过 `--runtime` 直接指定跳过交互。

```
参数：
  [name]              Skill 名称（可选；不填则进入 TUI 交互模式安装全部 Skills）
                      可选值：ops-auth、ops-dataset-query、ops-amazon、ops-skills

选项：
  --runtime TEXT      目标运行时（跳过自动检测）：
                        claude     → ~/.claude/skills/
                        openclaw   → ~/.openclaw/skills/
                        codex      → ~/.codex/skills/
                        opencode   → ~/.opencode/skills/
                        all        → 所有已检测到的运行时
                      支持逗号分隔多个值，如 claude,openclaw
  --skills-dir TEXT   指定安装目录（跳过自动检测和 --runtime）
  --force             覆盖已存在的安装（默认跳过已安装）
  --pretty            格式化 JSON 输出
```

**示例：**

```bash
# ── TUI 交互模式 ────────────────────────────────────────────
# 不指定 name，进入 TUI 勾选界面，可批量安装全部 Skills
opscli skills install

# ── 安装指定 Skill（自动检测运行时）────────────────────────
opscli skills install ops-auth
opscli skills install ops-dataset-query
opscli skills install ops-amazon
opscli skills install ops-skills

# ── 指定单个运行时安装 ────────────────────────────────────
opscli skills install ops-auth --runtime claude
opscli skills install ops-auth --runtime openclaw
opscli skills install ops-auth --runtime codex
opscli skills install ops-auth --runtime opencode

# ── 同时安装到多个运行时 ──────────────────────────────────
opscli skills install ops-auth --runtime claude,openclaw
opscli skills install ops-auth --runtime claude,codex,opencode

# ── 安装到所有已检测运行时 ───────────────────────────────
opscli skills install ops-auth --runtime all

# ── 覆盖已存在的安装 ──────────────────────────────────────
opscli skills install ops-dataset-query --force
opscli skills install ops-auth --runtime all --force

# ── 安装到指定自定义目录 ──────────────────────────────────
opscli skills install ops-auth --skills-dir ~/.claude/skills/
opscli skills install ops-auth --skills-dir /custom/path/to/skills/
```

**安装后目录结构（以 Claude Code 为例）：**

```
~/.claude/skills/
└── ops-auth/
    ├── data/
    │   └── VERSION.json      # 版本标识文件
    └── SKILL.md              # AI Agent 使用指南
```

---

### `opscli skills upgrade [name]`

升级 Skill 到远端最新版本（当前仅 `ops-dataset-query` 支持远端升级）。

升级流程：
1. 获取本地当前版本
2. 请求远端 API 获取最新版本号与数据
3. 版本号相同时跳过（除非指定 `--force`）
4. 版本号不同时，下载远端数据到临时目录
5. 验证完整性后，原子替换本地文件
6. 输出升级结果（成功/跳过/失败）

```
参数：
  [name]              Skill 名称（可选，默认 ops-dataset-query）
                      当前支持远端升级的 Skill：ops-dataset-query

选项：
  --skills-dir TEXT   指定扫描目录（覆盖默认自动检测路径）
  --force             强制重新拉取，即使版本号相同
  --pretty            格式化 JSON 输出
```

**示例：**

```bash
# 升级 ops-dataset-query（默认目标）
opscli skills upgrade

# 显式指定 Skill 名称升级
opscli skills upgrade ops-dataset-query

# 强制重新拉取远端数据（即使版本号相同）
opscli skills upgrade ops-dataset-query --force

# 升级指定目录中的 Skill
opscli skills upgrade ops-dataset-query --skills-dir ~/.claude/skills/

# 强制升级并格式化输出
opscli skills upgrade --force --pretty
```

**典型输出（有更新）：**

```json
{
  "name": "ops-dataset-query",
  "status": "upgraded",
  "from_version": "v2.0.0",
  "to_version": "v2.1.0",
  "path": "/Users/you/.claude/skills/ops-dataset-query"
}
```

**典型输出（已是最新）：**

```json
{
  "name": "ops-dataset-query",
  "status": "skipped",
  "reason": "already at latest version v2.1.0"
}
```

---

## 典型工作流

### 场景一：全新环境初始化

在新机器或新用户目录中，首次配置所有 Skill：

```bash
# 1. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 2. 确认 opscli 已正常安装
opscli --version

# 3. 通过 TUI 交互模式，勾选并批量安装全部 Skills
opscli skills install

# 4. 验证安装结果
opscli skills list --pretty

# 5. 检查版本状态
opscli skills status --pretty
```

### 场景二：日常版本维护

定期检查并更新 Skills，确保数据集查询功能使用最新字段索引：

```bash
# 1. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 2. 检查所有 Skill 的版本状态
opscli skills status --pretty

# 3. 如果 ops-dataset-query 有新版本，执行升级
opscli skills upgrade ops-dataset-query

# 4. 验证升级后的版本
opscli skills list --pretty
```

### 场景三：多运行时环境安装

同时使用多种 AI 工具（如 Claude Code + OpenClaw）时：

```bash
# 1. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 2. 安装所有 Skill 到全部已检测运行时
opscli skills install --runtime all

# 3. 或分开安装到指定运行时
opscli skills install ops-auth --runtime claude,openclaw
opscli skills install ops-dataset-query --runtime claude,openclaw
opscli skills install ops-skills --runtime claude,openclaw

# 4. 验证各运行时均已安装
opscli skills list --pretty
```

### 场景四：强制重置安装

当 Skill 文件损坏或需要回退到内置版本时：

```bash
# 1. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 2. 强制覆盖安装（重置为内置模板版本）
opscli skills install ops-auth --force
opscli skills install ops-dataset-query --force
opscli skills install ops-skills --force

# 3. 如需同时重置远端数据，再执行升级
opscli skills upgrade ops-dataset-query --force
```

### 场景五：指定路径安装（CI/脚本环境）

在自动化脚本或 CI 环境中，指定明确路径跳过交互：

```bash
# 1. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 2. 指定运行时跳过自动检测
opscli skills install ops-auth --runtime claude --force

# 3. 或直接指定目标目录
opscli skills install ops-auth --skills-dir ~/.claude/skills/ --force
opscli skills install ops-dataset-query --skills-dir ~/.claude/skills/ --force

# 4. 输出 JSON 便于脚本解析
opscli skills list --skills-dir ~/.claude/skills/
```

---

## 错误排查

### 安装失败：运行时未检测到

```
错误：未检测到任何已安装的 AI 工具运行时
```

**原因**：全局路径均不存在（如 `~/.claude/` 不存在）。

**解决**：
```bash
# 方式 1：使用 --runtime 显式指定运行时（opscli 会自动创建目录）
opscli skills install ops-auth --runtime claude

# 方式 2：手动创建目录后重试
mkdir -p ~/.claude/skills/
opscli skills install ops-auth
```

### 安装失败：Skill 已存在

```
错误：Skill ops-auth 已存在于 ~/.claude/skills/ops-auth
```

**原因**：目标目录已有同名 Skill，且未指定 `--force`。

**解决**：
```bash
opscli skills install ops-auth --force
```

### 升级失败：网络不可达

```
错误：无法连接到远端服务，请检查网络连接
```

**原因**：升级需要访问 ops 后端 API，网络异常时无法拉取。

**解决**：
```bash
# 1. 先调用 ops-auth Skill，检查 auth 状态
opscli auth token status

# 2. 检查网络连通性
opscli auth doctor

# 3. 网络恢复后重试
opscli skills upgrade ops-dataset-query
```

### 升级失败：Token 过期

```
错误：认证 Token 已过期，请重新登录
```

**解决**：
```bash
# 先调用 ops-auth Skill 处理认证

# JWT Token 过期时优先刷新
opscli auth token refresh --all

# 若刷新失败或仍异常，再重新登录
opscli auth login

# 再执行升级
opscli skills upgrade ops-dataset-query
```

---

## 版本标识文件格式

每个 Skill 目录下的 `data/VERSION.json` 是 `SkillDetector` 的识别标志。格式为：

```json
{
  "name": "ops-skills",
  "version": "v1.0.0"
}
```

- `name`：必须与 Skill 目录名一致，且必须带 `ops-` 前缀
- `version`：语义化版本号，格式 `v{major}.{minor}.{patch}`

---

## 注意事项

1. **不修改 VERSION.json**：手动修改版本文件会导致 `status` 命令产生误判，请勿手动编辑
2. **升级不影响认证**：`ops-dataset-query` 升级的是字段元数据，不会清除已登录的凭证
3. **多运行时独立管理**：每个运行时（claude/openclaw/codex/opencode）的 Skills 目录相互独立，安装和升级互不影响
4. **全局 vs 项目级**：Skills 安装在全局路径（`~/`），对该用户下所有项目生效，无需在每个项目中单独安装
5. **不得跳过登录检测**：即使当前任务只做本地 Skill 安装或列表，也必须先走 `ops-auth` 约定的认证检测流程
