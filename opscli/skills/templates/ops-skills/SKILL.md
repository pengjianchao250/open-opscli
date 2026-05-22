---
name: ops-skills
description: 管理 AI 工具中已安装的 Skill 生命周期，包含技能广场的发布、安装、浏览与评分
version: v1.3.0
---

# ops-skills

管理 Claude Code、OpenClaw、Codex CLI、OpenCode 中 Skill 的完整生命周期，所有操作通过 `opscli skills` 子命令执行。

包含三大能力域：
- **本地生命周期**：列表、状态检查、内置模板安装、版本升级
- **技能广场**：浏览、搜索、查看详情、远程安装（`username@skill_name`）、提交评分
- **发布管理**：将本地 Skill 发布到广场、下架已发布技能

---

## 概述

`ops-skills` 是 Aukeys 运营工具体系的 Skill 生命周期管理器。它负责：

- **发现**：扫描全局路径，识别所有已安装的 Skill
- **安装**：从内置模板或技能广场将 Skill 部署到目标运行时的全局目录
- **版本检查**：对比本地版本与远端最新版本，告知是否需要升级
- **升级**：拉取远端最新数据，原子替换本地文件，确保数据不中断
- **广场发布**：将本地 Skill 目录打包 zip 上传到技能广场，支持首次发布与追加新版本
- **广场浏览**：查看广场上的公开技能列表、搜索、查看详情与版本历史
- **评分**：为已安装或使用过的技能提交 1-5 分评价（小数自动向下取整）

所有操作均通过 `opscli skills` 子命令完成，Skill 脚本本身不直接调用任何后端 HTTP API。

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

优先级如下：

1. 如果用户明确要求使用 CLI，直接遵循用户指定
2. 默认使用 CLI，并继续执行本文件中的 `opscli skills` 正式命令流程
3. 如果一开始按 CLI 执行首个正式命令就失败（例如 `opscli skills ...` 不可用、当前宿主不适合跑本地命令），由于当前没有 MCP 版本，直接回退为帮助用户安装 `aukeys-opscli`

建议提问方式：

- `当前 CLI 入口不可用。你希望我先安装 aukeys-opscli，再继续处理这个 Skill 吗？`

简化原则：

- `ops-skills` 当前只提供 CLI 入口，不提供 MCP 版本
- 不单独检查发行包、命令路径、子命令 help；用"首次正式调用是否可执行"作为唯一验证
- CLI 首次正式调用失败后，直接回退为帮助用户安装 `aukeys-opscli`

---

## 强制认证门禁

> **【强制】每次调用 `ops-skills` 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现"未登录 / 未授权 / Token 过期 / expired / 401"等状态，必须立即切换到 `ops-auth` Skill
- 若是"未登录 / 未授权 / 401"等状态，在 `ops-auth` 中执行 `opscli auth login` 完成授权登录
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh`（例如 `opscli auth token refresh --all` 或 `opscli auth token refresh -s ops`）；刷新失败或仍异常时，再执行 `opscli auth login`
- 必要时执行 `opscli auth token check -s ops` 或 `opscli auth doctor` 做确认
- 只有认证检查通过后，才允许继续执行后续命令
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
- **中央存储**：远程安装时统一解压到 `~/.opscli/skills/<skill_name>/`，再软链接到各 AI 工具全局目录

---

## 内置可安装 Skill

| Skill 名称 | 说明 | 支持远端升级 |
|-----------|------|------------|
| `ops-auth` | 认证授权管理（登录、Token 查看与刷新、系统管理） | 否 |
| `ops-dataset-query` | 数据集字段索引与查询转发（支持 metadata 拉取和 query 执行） | 是 |
| `ops-amazon` | Amazon 商品页与搜索结果抓取工作流指导 | 否 |
| `ops-skills` | Skill 生命周期管理（本 Skill） | 否 |

> 技能广场上还有更多由社区发布的 Skill，通过 `opscli skills marketplace list` 浏览，或直接用 `opscli skills install username@skill_name` 远程安装。

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

**远程安装的中央存储路径：**

```
~/.opscli/skills/<skill_name>/    ← 解压后的 zip 内容（中央存储）
├── SKILL.md
├── data/
│   └── VERSION.json
└── ...（zip 内其他文件）

~/.claude/skills/<skill_name>      ← 软链接 → 中央存储目录
~/.openclaw/skills/<skill_name>    ← 软链接 → 中央存储目录
```

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
opscli skills status
opscli skills status --pretty
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
  }
]
```

---

### `opscli skills install [name|identifier]`

安装 Skill，支持两种来源：

- **内置模板**：`name` 传内置 Skill 名称（如 `ops-auth`）
- **技能广场远程安装**：`name` 传 `username@skill_name` 格式标识符

不指定任何参数时进入 TUI 交互模式，可批量安装内置模板。

**远程安装流程（`username@skill_name` 格式）：**
1. 从广场获取技能元数据与下载地址
2. 下载 zip 包，解压到 `~/.opscli/skills/<skill_name>/`（中央存储）
3. 软链接到 `~/.claude/skills/`、`~/.openclaw/skills/` 等全局 AI 工具目录
4. 回调广场记录安装次数
5. **【强制】安装成功后，立即用 `AskUserQuestion` 工具引导用户评分（见"安装后评分引导"章节）**

```
参数：
  [name|identifier]   Skill 名称（ops-auth 等）或广场标识符（username@skill_name）
                      不填则进入 TUI 交互模式

选项：
  --runtime TEXT      目标运行时：claude / openclaw / codex / opencode / all
                      支持逗号分隔多个值，如 claude,openclaw
  --version TEXT      指定安装版本（仅远程安装有效）
  --skills-dir TEXT   指定安装目录（跳过自动检测和 --runtime）
  --force             覆盖已存在的安装（默认跳过已安装）
  --pretty            格式化 JSON 输出
```

**示例：**

```bash
# ── 内置模板安装 ──────────────────────────────────────────
opscli skills install ops-auth
opscli skills install ops-dataset-query
opscli skills install ops-auth --runtime claude
opscli skills install ops-auth --runtime claude,openclaw
opscli skills install ops-auth --runtime all
opscli skills install ops-dataset-query --force

# ── 从技能广场远程安装 ─────────────────────────────────────
opscli skills install pengjianchao@ops-auth
opscli skills install pengjianchao@ops-auth --force
opscli skills install pengjianchao@ops-auth --runtime claude

# ── TUI 交互模式（批量安装内置模板）──────────────────────────
opscli skills install
```

**安装后目录结构（以 Claude Code 为例）：**

```
~/.opscli/skills/ops-auth/          ← 中央存储（远程安装时）
├── SKILL.md
└── data/
    └── VERSION.json

~/.claude/skills/ops-auth           ← 软链接 → 中央存储（或直接复制，内置模板）
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

选项：
  --skills-dir TEXT   指定扫描目录
  --force             强制重新拉取，即使版本号相同
  --pretty            格式化 JSON 输出
```

**示例：**

```bash
opscli skills upgrade
opscli skills upgrade ops-dataset-query
opscli skills upgrade ops-dataset-query --force
opscli skills upgrade ops-dataset-query --skills-dir ~/.claude/skills/
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

---

### `opscli skills publish`

将本地 Skill 目录打包（zip）发布到技能广场。

- **首次发布**：自动创建技能条目，上传文件，设置元数据
- **再次发布**：追加新版本到已有技能，文件覆盖，支持 changelog

技能目录必须包含：
- `SKILL.md`：技能指南（可在顶部 YAML frontmatter 中声明 `title`、`description`、`tags`、`category_id`）
- `data/VERSION.json`：`{"name": "skill-name", "version": "1.2.0"}`（版本号不要带 `v` 前缀）

发布时整个目录被打包为 zip（排除 `__pycache__`、`.pyc` 等），上传至 OSS。

```
选项：
  --dir / -d TEXT     Skill 目录（默认当前目录 .）
  --title TEXT        技能标题（覆盖 SKILL.md frontmatter）
  --desc TEXT         技能简介
  --tags TEXT         标签，逗号分隔（如 "ai,ops,auth"）
  --category INT      分类 ID
  --changelog TEXT    本次版本变更说明
  --json              输出原始 JSON（适合脚本）
```

**示例：**

```bash
# 发布当前目录（读取 SKILL.md frontmatter 作为元数据）
opscli skills publish

# 指定目录，附加变更说明
opscli skills publish --dir ./my-skill --changelog "修复了 xxx 问题"

# 附带完整元数据（覆盖 frontmatter）
opscli skills publish \
  --title "我的技能" \
  --desc "这是一个示例技能" \
  --tags "ai,demo" \
  --changelog "初始版本"

# JSON 输出（脚本模式）
opscli skills publish --json
```

**data/VERSION.json 格式：**

```json
{
  "name": "ops-auth",
  "version": "1.1.0"
}
```

**SKILL.md frontmatter 格式（可选）：**

```markdown
---
title: Ops 认证授权
description: 管理 Claude Code 中的 ops/polaris 认证授权流程
tags: auth,ops,认证
category_id: 1
---
```

**发布成功后的 identifier：**

```
pengjianchao@ops-auth
```

其他用户可通过 `opscli skills install pengjianchao@ops-auth` 安装。

---

### `opscli skills unpublish <identifier>`

下架已发布的技能（软删除，不影响已安装到本地的用户）。

```
参数：
  identifier          技能标识符，格式 username@skill_name

选项：
  --force / -f        跳过交互确认提示
  --json              输出原始 JSON
```

**示例：**

```bash
opscli skills unpublish pengjianchao@ops-auth
opscli skills unpublish pengjianchao@ops-auth --force
```

> 注意：下架后广场新用户无法搜索或安装该技能，但已安装到本地的用户不受影响。

---

## 安装后评分引导

> **【强制行为】每次远程安装（`username@skill_name` 格式）成功后，必须立即触发评分引导，禁止跳过。**

### 触发条件

仅限以下场景触发：

- 执行 `opscli skills install username@skill_name` 且命令返回 **安装成功**（包含 `"status": "installed"` 或等价成功提示）
- 强制重装（`--force`）同样触发
- 内置模板安装（`ops-auth`、`ops-dataset-query` 等）**不触发**（无 `@`）
- 安装失败时**不触发**

### 引导方式（必须使用 `AskUserQuestion` 工具，分两步）

安装命令执行完毕、向用户报告安装结果之后，立即调用 `AskUserQuestion` 工具，**不得仅在对话文本中口头询问**。

> ⚠️ `AskUserQuestion` 每题最多 4 个选项（+自动追加"其他"），评分 6 项（1-5分 + 暂不评分）需拆成两步调用。

---

**第一步：询问是否愿意评分**

```
AskUserQuestion({
  questions: [
    {
      question: "安装成功！你愿意为「<skill_title>（<identifier>）」打个分吗？",
      header: "技能评分",
      multiSelect: false,
      options: [
        { label: "是，我要评分", description: "为这个技能提交 1-5 分评价" },
        { label: "暂不评分",     description: "跳过，稍后用命令手动评分" }
      ]
    }
  ]
})
```

- 用户选 **"暂不评分"** → 告知用户可稍后使用 `opscli skills marketplace rate <identifier> <1-5>` 手动评分，流程结束
- 用户选 **"是，我要评分"** → 立即进入第二步

---

**第二步：选择具体分数**

```
AskUserQuestion({
  questions: [
    {
      question: "请为「<skill_title>」选择评分：",
      header: "选择分数",
      multiSelect: false,
      options: [
        { label: "⭐⭐⭐⭐⭐ 5分", description: "非常棒，强烈推荐！" },
        { label: "⭐⭐⭐⭐ 4分",  description: "挺好用，值得推荐" },
        { label: "⭐⭐⭐ 3分",    description: "一般，凑合能用" },
        { label: "⭐⭐ 2分",      description: "较差，有明显问题" }
      ]
    }
  ]
})
```

> 第二步中 `AskUserQuestion` 会自动追加"其他"选项，用户可在"其他"中输入 `1` 来提交 1 分评价。

> **说明**：`<skill_title>` 取安装元数据中的 `title` 字段；若无则用 `<identifier>` 代替（如 `pengjianchao@ops-auth`）。

---

### 根据用户选择执行后续操作

| 用户选择 | 对应分数 | 后续动作 |
|---------|---------|---------|
| ⭐⭐⭐⭐⭐ 5分 | 5 | 执行评分命令 |
| ⭐⭐⭐⭐ 4分 | 4 | 执行评分命令 |
| ⭐⭐⭐ 3分 | 3 | 执行评分命令 |
| ⭐⭐ 2分 | 2 | 执行评分命令 |
| 其他（用户输入 `1`） | 1 | 执行评分命令 |
| 其他（用户输入非法值） | — | 告知格式要求后跳过 |
| 第一步选"暂不评分" | — | 流程在第一步结束，不进入第二步 |

**评分命令（用户选择数字后自动执行，无需二次确认）：**

```bash
opscli skills marketplace rate <identifier> <score>
```

**评分执行后，向用户简短回报结果：**

```
✅ 已为 pengjianchao@ops-auth 提交 ⭐⭐⭐⭐⭐ (5/5) 评分，感谢！
```

### 完整引导示例（场景还原）

```
[安装完成后]
AI 输出：
  ✅ pengjianchao@ops-auth 安装成功（v1.2.0）
  └ 软链接已创建：~/.claude/skills/ops-auth → ~/.opscli/skills/ops-auth

[第一步：AskUserQuestion]
  ❓ 安装成功！你愿意为「Ops 认证授权（pengjianchao@ops-auth）」打个分吗？
     是，我要评分  /  暂不评分

[用户选"是，我要评分" → 第二步：AskUserQuestion]
  ❓ 请为「Ops 认证授权」选择评分：
     ⭐⭐⭐⭐⭐ 5分  /  ⭐⭐⭐⭐ 4分  /  ⭐⭐⭐ 3分  /  ⭐⭐ 2分  /  其他（可输入 1）

[用户选 ⭐⭐⭐⭐⭐ 5分]
  → 自动执行：opscli skills marketplace rate pengjianchao@ops-auth 5
  → AI 回报：✅ 已为 pengjianchao@ops-auth 提交 ⭐⭐⭐⭐⭐ (5/5) 评分，感谢！

[用户在第一步选"暂不评分"]
  → AI 提示：好的，你可以稍后通过以下命令手动评分：
              opscli skills marketplace rate pengjianchao@ops-auth <1-5>

[用户在第二步"其他"中输入 1]
  → 自动执行：opscli skills marketplace rate pengjianchao@ops-auth 1
  → AI 回报：✅ 已为 pengjianchao@ops-auth 提交 ⭐ (1/5) 评分，感谢反馈！
```

---

## 技能广场子命令 `opscli skills marketplace`

### `opscli skills marketplace list`

浏览广场公开技能列表。

```
选项：
  --category INT      按分类 ID 筛选
  --sort TEXT         排序字段：downloads（默认）/ rating / created_at
  --order TEXT        排序方向：desc（默认）/ asc
  --page INT          页码（默认 1）
  --limit INT         每页条数（默认 20，最大 50）
  --official          只显示官方技能
  --json              输出原始 JSON
```

**示例：**

```bash
# 浏览全部技能，按下载量降序
opscli skills marketplace list

# 按评分排序，每页 10 条
opscli skills marketplace list --sort rating --limit 10

# 按分类筛选
opscli skills marketplace list --category 1

# 只看官方技能
opscli skills marketplace list --official
```

---

### `opscli skills marketplace search <keyword>`

按关键词搜索广场技能。

```bash
opscli skills marketplace search ops-auth
opscli skills marketplace search "数据查询" --limit 5
opscli skills marketplace search auth --sort rating --json
```

---

### `opscli skills marketplace info <identifier>`

查看指定技能的详细信息（元数据、统计、版本列表）。

```bash
opscli skills marketplace info pengjianchao@ops-auth
opscli skills marketplace info pengjianchao@ops-auth --json
```

---

### `opscli skills marketplace versions <identifier>`

查看指定技能的历史版本列表。

```bash
opscli skills marketplace versions pengjianchao@ops-auth
```

---

### `opscli skills marketplace rate <identifier> <score>`

为广场技能提交评分。评分范围 **1-5 分整数**；若传入小数，自动向下取整后再提交（如 4.7 → 4）。重复调用则更新已有评分（每人每技能只有一条评分记录）。

```
参数：
  identifier          技能标识符，格式 username@skill_name
  score               评分，1-5 的数字；小数自动 floor（如 4.7 → 4）

选项：
  --comment / -c TEXT 评价文字（可选，最多 500 字符）
  --json              输出原始 JSON
```

**示例：**

```bash
# 整数评分
opscli skills marketplace rate pengjianchao@ops-auth 5
opscli skills marketplace rate pengjianchao@ops-auth 4 --comment "非常实用，推荐！"

# 小数评分（自动 floor：4.7 → 4）
opscli skills marketplace rate pengjianchao@ops-auth 4.7
# 输出：评分 4.7 向下取整为 4
#       已为 pengjianchao@ops-auth 提交评分：⭐⭐⭐⭐ (4/5)

# JSON 模式（脚本场景）
opscli skills marketplace rate pengjianchao@ops-auth 5 --json
```

**注意：**
- 向下取整在客户端完成，服务端只接受整数 1-5；直接传小数会被服务端拒绝
- 每人每技能只有一条评分，重复调用自动更新评分与评价文字

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
# 1. 先检查认证状态
opscli auth token status

# 2. 检查所有 Skill 的版本状态
opscli skills status --pretty

# 3. 如果 ops-dataset-query 有新版本，执行升级
opscli skills upgrade ops-dataset-query

# 4. 验证升级后的版本
opscli skills list --pretty
```

### 场景三：从广场发现并安装技能

```bash
# 1. 先检查认证状态
opscli auth token status

# 2. 浏览广场技能
opscli skills marketplace list

# 3. 搜索感兴趣的技能
opscli skills marketplace search "数据查询"

# 4. 查看详情与版本历史
opscli skills marketplace info pengjianchao@ops-auth
opscli skills marketplace versions pengjianchao@ops-auth

# 5. 远程安装
opscli skills install pengjianchao@ops-auth

# 6. 确认安装成功
opscli skills list --pretty

# 7. 【强制】安装成功后立即用 AskUserQuestion 引导用户评分（1-5 分）
#    用户选择后自动执行：
opscli skills marketplace rate pengjianchao@ops-auth <score>
```

### 场景四：将自己的 Skill 发布到广场

```bash
# 1. 先检查认证状态
opscli auth token status

# 2. 进入技能目录
cd my-skill/

# 3. 确认目录结构完整
ls SKILL.md data/VERSION.json

# 4. 首次发布
opscli skills publish --changelog "初始版本"
# 输出：技能已发布，标识符：pengjianchao@my-skill

# 5. 修改内容后发布新版本（先更新 data/VERSION.json 中的 version）
opscli skills publish --changelog "修复了 xxx，新增了 yyy"
```

### 场景五：多运行时环境安装

同时使用多种 AI 工具（如 Claude Code + OpenClaw）时：

```bash
# 1. 先检查认证状态
opscli auth token status

# 2. 安装所有 Skill 到全部已检测运行时
opscli skills install --runtime all

# 3. 或分开安装到指定运行时
opscli skills install ops-auth --runtime claude,openclaw
opscli skills install ops-dataset-query --runtime claude,openclaw

# 4. 从广场远程安装也会自动软链接到各运行时
opscli skills install pengjianchao@ops-auth

# 5. 验证各运行时均已安装
opscli skills list --pretty
```

### 场景六：强制重置安装

当 Skill 文件损坏或需要回退到内置版本时：

```bash
# 1. 先检查认证状态
opscli auth token status

# 2. 强制覆盖安装（重置为内置模板版本）
opscli skills install ops-auth --force
opscli skills install ops-dataset-query --force
opscli skills install ops-skills --force

# 3. 如需同时重置远端数据，再执行升级
opscli skills upgrade ops-dataset-query --force
```

### 场景七：指定路径安装（CI/脚本环境）

在自动化脚本或 CI 环境中，指定明确路径跳过交互：

```bash
# 1. 先检查认证状态
opscli auth token status

# 2. 指定运行时跳过自动检测
opscli skills install ops-auth --runtime claude --force

# 3. 或直接指定目标目录
opscli skills install ops-auth --skills-dir ~/.claude/skills/ --force

# 4. JSON 输出便于脚本解析
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

**解决**：
```bash
opscli skills install ops-auth --force
```

### 远程安装失败：标识符格式错误

```
错误：无效的 Skill 标识符: "ops-auth"，应为 username@skill_name 格式
```

**原因**：广场远程安装必须用 `username@skill_name` 格式（如 `pengjianchao@ops-auth`）。  
内置模板安装直接用 Skill 名称（如 `ops-auth`，不含 `@`）。

### 发布失败：VERSION.json 格式错误

```
错误：data/VERSION.json 中 name 字段不能为空
```

**解决**：确认 `data/VERSION.json` 内容格式正确：
```json
{
  "name": "ops-auth",
  "version": "1.0.0"
}
```

> 注意：`version` 字段**不要**带 `v` 前缀（如写 `"1.0.0"` 而非 `"v1.0.0"`）。

### 升级失败：网络不可达

```
错误：无法连接到远端服务，请检查网络连接
```

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
  "version": "1.1.0"
}
```

- `name`：必须与 Skill 目录名一致
- `version`：语义化版本号，格式 `{major}.{minor}.{patch}`（**不带 `v` 前缀**）

---

## 注意事项

1. **不修改 VERSION.json**：手动修改版本文件会导致 `status` 命令产生误判，请勿手动编辑
2. **发布时版本号不带 v**：`data/VERSION.json` 中的 `version` 字段写 `"1.1.0"` 而非 `"v1.1.0"`；SKILL.md frontmatter 中的 `version` 字段则带 `v`（如 `v1.1.0`），两者用途不同
3. **升级不影响认证**：`ops-dataset-query` 升级的是字段元数据，不会清除已登录的凭证
4. **多运行时独立管理**：每个运行时（claude/openclaw/codex/opencode）的 Skills 目录相互独立，安装和升级互不影响
5. **全局 vs 项目级**：Skills 安装在全局路径（`~/`），对该用户下所有项目生效，无需在每个项目中单独安装
6. **不得跳过登录检测**：即使当前任务只做本地 Skill 安装或列表，也必须先走 `ops-auth` 约定的认证检测流程
7. **远程安装中央存储**：通过广场安装的 Skill 统一存放在 `~/.opscli/skills/`，各 AI 工具目录通过软链接引用，升级时只需更新中央存储
8. **下架仅影响广场**：`unpublish` 是软删除，只阻止广场新用户搜索和安装，不影响已安装的本地副本
