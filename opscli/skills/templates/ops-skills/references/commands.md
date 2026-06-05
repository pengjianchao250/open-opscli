# ops-skills 命令参考

## 目录

- [opscli skills list](#list)
- [opscli skills status](#status)
- [opscli skills install](#install)
- [opscli skills install --sync-market](#sync-market)
- [opscli skills sync-exclude](#sync-exclude)
- [opscli skills upgrade](#upgrade)
- [opscli skills publish](#publish)
- [opscli skills edit](#edit)
- [opscli skills unpublish](#unpublish)
- [opscli skills marketplace](#marketplace)

---

## `opscli skills list` {#list}

列出所有已安装的 Skill（扫描全局路径）。

```
选项：
  --skills-dir TEXT   指定扫描目录
  --pretty            格式化 JSON 输出
```

```bash
opscli skills list
opscli skills list --pretty
opscli skills list --skills-dir ~/.claude/skills/
```

**典型输出：**

```json
[
  {"name": "ops-auth", "version": "v1.0.0", "path": "/Users/you/.claude/skills/ops-auth", "runtime": "claude"},
  {"name": "ops-dataset-query", "version": "v2.1.0", "path": "/Users/you/.claude/skills/ops-dataset-query", "runtime": "claude"}
]
```

---

## `opscli skills status` {#status}

查看已安装 Skill 的本地版本 vs 远端最新版本（需联网）。

```
选项：
  --skills-dir TEXT   指定扫描目录
  --pretty            格式化 JSON 输出
```

```bash
opscli skills status
opscli skills status --pretty
opscli skills status --skills-dir ~/.claude/skills/
```

**典型输出：**

```json
[
  {"name": "ops-auth", "local_version": "v1.0.0", "remote_version": null, "needs_upgrade": false, "upgradable": false},
  {"name": "ops-dataset-query", "local_version": "v2.0.0", "remote_version": "v2.1.0", "needs_upgrade": true, "upgradable": true}
]
```

---

## `opscli skills install` {#install}

安装 Skill，支持内置模板和广场远程两种来源：

- **内置模板**：传内置名称（如 `ops-auth`）
- **广场远程**：传 `username@skill_name` 格式
- **TUI 模式**：不传参数，进入交互批量安装

**远程安装流程：**
1. 从广场获取元数据与下载地址
2. 下载 zip，解压到 `~/.opscli/skills/<name>/`（中央存储）
3. 软链到 `~/.claude/skills/` 等运行时目录
4. 回调广场记录安装次数
5. **强制**：安装成功后触发评分引导（见 [rating-guide.md](rating-guide.md)）

```
参数：
  [name|identifier]   Skill 名称或 username@skill_name；不填进入 TUI 模式

选项：
  --runtime TEXT      目标运行时：claude / openclaw / codex / opencode / all；支持逗号分隔
  --version TEXT      指定安装版本（仅远程安装有效）
  --skills-dir TEXT   指定安装目录（跳过自动检测）
  --force             覆盖已存在的安装
  --pretty            格式化 JSON 输出
```

```bash
# 内置模板安装
opscli skills install ops-auth
opscli skills install ops-auth --runtime claude
opscli skills install ops-auth --runtime claude,openclaw
opscli skills install ops-auth --runtime all
opscli skills install ops-dataset-query --force

# 广场远程安装
opscli skills install pengjianchao@ops-auth
opscli skills install pengjianchao@ops-auth --force
opscli skills install pengjianchao@ops-auth --runtime claude

# TUI 批量安装
opscli skills install
```

**安装后目录结构（Claude Code）：**

```
~/.opscli/skills/ops-auth/          # 中央存储（远程安装）
├── SKILL.md
└── data/VERSION.json

~/.claude/skills/ops-auth           # 软链接 → 中央存储（或直接复制，内置模板）
```

---

## `opscli skills install --sync-market` {#sync-market}

从技能广场安装记录同步，自动补装缺失 + 升级旧版。

**版本比较规则：**

| 本地状态 | 动作 |
|---------|------|
| 不存在 | 安装最新版 |
| 本地版本 < 市场版本 | 升级到最新版 |
| 本地版本 >= 市场版本 | 跳过 |
| 存在但无 VERSION.json | 强制重装（记录警告） |

```
选项：
  --dry-run           仅预览计划，不实际安装
  --runtime TEXT      安装目标运行时
  --skills-dir TEXT   指定安装目录
```

```bash
opscli skills install --sync-market --dry-run   # 预览
opscli skills install --sync-market             # 执行
opscli skills install --sync-market --runtime claude
```

**预览输出示例（--dry-run）：**

```
┌─ 同步预览 ─────────────────────────────────────────────────────┐
│ 标识符                   本地版本   市场版本   动作              │
│ pengjianchao@ops-auth    未安装     1.3.0      安装              │
│ alice@data-query          1.0.0     1.2.0      升级              │
│ bob@amazon-helper         1.1.0     1.1.0      跳过              │
└─────────────────── 安装 1 个 / 升级 1 个 / 跳过 1 个 ──────────┘
```

---

## `opscli skills sync-exclude` {#sync-exclude}

管理不同步到本地的技能排除名单（存储在服务端，多机共享）。

```
子命令：
  add    <identifier>   加入排除名单
  remove <identifier>   移出排除名单
  list                  查看当前排除名单
```

```bash
opscli skills sync-exclude add alice@data-query
opscli skills sync-exclude remove alice@data-query
opscli skills sync-exclude list
```

---

## `opscli skills upgrade` {#upgrade}

升级 Skill 到远端最新版本（当前仅 `ops-dataset-query` 支持远端升级）。

**升级流程：** 获取本地版本 → 查询远端版本 → 版本相同则跳过 → 下载到临时目录 → 验证后原子替换

```
参数：
  [name]              Skill 名称（默认 ops-dataset-query）

选项：
  --skills-dir TEXT   指定扫描目录
  --force             强制重新拉取（即使版本号相同）
  --pretty            格式化 JSON 输出
```

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

## `opscli skills publish` {#publish}

将本地 Skill 目录打包发布到技能广场。

**目录必须包含：**
- `SKILL.md`：可在 frontmatter 声明 `title`、`description`、`tags`、`category_id`
- `data/VERSION.json`：`{"name": "skill-name", "version": "1.2.0"}`（不带 `v` 前缀）

> **自动分类匹配**：未指定 `--category` 时，自动从广场获取分类列表做关键词匹配，输出 `已自动匹配分类：<name>` 提示。

**分享权限类型：**

| 类型 | 含义 |
|------|------|
| `personal`（默认）| 仅发布者本人可见 |
| `department` | 部门内成员可见 |
| `company` | 全员可见 |

```
选项：
  --dir / -d TEXT     Skill 目录（默认当前目录 .）
  --title TEXT        技能标题（覆盖 SKILL.md frontmatter）
  --desc TEXT         详细描述
  --summary TEXT      一句话简介（最多 500 字符）
  --share-type TEXT   分享权限：personal / department / company
  --tags TEXT         标签，逗号分隔
  --category INT      分类 ID（不传时自动匹配）
  --changelog TEXT    本次变更说明
  --json              输出原始 JSON
```

```bash
opscli skills publish
opscli skills publish --share-type company
opscli skills publish --share-type department --summary "部门内共享的数据查询辅助技能"
opscli skills publish --dir ./my-skill --changelog "修复了 xxx 问题"
opscli skills publish --title "我的技能" --share-type company --tags "ai,demo" --changelog "初始版本"
opscli skills publish --json
```

**SKILL.md frontmatter 格式（可选）：**

```markdown
---
title: Ops 认证授权
description: 管理认证授权流程
summary: 一键完成 ops/polaris 登录与 Token 管理
share_type: company
tags: auth,ops,认证
category_id: 1
---
```

---

## `opscli skills edit` {#edit}

编辑已发布技能的元数据、文件或版本号。

- **仅修改元数据**：不传 `--dir/--file`，纯 JSON 更新（速度快）
- **重传文件**：传 `--dir` 或 `--file`，multipart/form-data 上传

**版本变更规则：**

| 场景 | 行为 |
|------|------|
| 传 `--version`，版本号与当前相同 + 传文件 | OSS 文件覆盖，不新建版本记录 |
| 传 `--version`，版本号高于当前 | 新建版本记录，更新 latest_version |
| 传 `--version`，版本号低于当前 | 拒绝（400 错误） |
| 只传文件，不传 `--version` | 以当前版本号覆盖 OSS |
| 只传 `--version`，不传文件 | 复用当前文件，新建版本记录 |

```
参数：
  identifier          username@skill_name

选项：
  --dir / -d TEXT     技能目录（自动打包；与 --file 互斥）
  --file TEXT         直接指定 zip 或 md 文件（与 --dir 互斥）
  --title TEXT        更新标题
  --desc TEXT         更新详细描述
  --summary TEXT      更新一句话简介（最多 500 字符）
  --share-type TEXT   更新分享权限
  --tags TEXT         更新标签（逗号分隔）
  --category INT      更新分类 ID（不传时自动匹配）
  --version TEXT      更新版本号（格式 x.y.z）
  --changelog TEXT    版本变更说明
  --json              输出原始 JSON
```

```bash
# 仅修改元数据
opscli skills edit pengjianchao@ops-auth --title "Ops 认证授权 v2" --summary "新版登录流程"
opscli skills edit pengjianchao@ops-auth --share-type company
opscli skills edit pengjianchao@ops-auth --version 1.3.0 --changelog "重构登录逻辑"

# 重新上传文件
opscli skills edit pengjianchao@ops-auth --dir ./ops-auth/
opscli skills edit pengjianchao@ops-auth --dir ./ops-auth/ --version 1.4.0 --changelog "修复重大 Bug"
opscli skills edit pengjianchao@ops-auth --file ./ops-auth-1.4.0.zip --version 1.4.0
opscli skills edit pengjianchao@ops-auth --file ./SKILL.md

# JSON 输出
opscli skills edit pengjianchao@ops-auth --title "新标题" --json
```

> `--dir` 模式自动读取 `SKILL.md` frontmatter 作为字段默认值；命令行显式参数优先级更高。

---

## `opscli skills unpublish` {#unpublish}

下架已发布技能（软删除，不影响已安装用户）。

```
参数：
  identifier          username@skill_name

选项：
  --force / -f        跳过交互确认
  --json              输出原始 JSON
```

```bash
opscli skills unpublish pengjianchao@ops-auth
opscli skills unpublish pengjianchao@ops-auth --force
```

---

## `opscli skills marketplace` {#marketplace}

### `marketplace categories`

查看所有技能分类（ID、slug、名称）。

```bash
opscli skills marketplace categories
opscli skills marketplace categories --json
```

**典型输出：**

```
┌─ Skill 技能分类 ─────────────────────────┐
│ ID   Slug         分类名称               │
│ 1    auth         认证授权               │
│ 2    data-query   数据查询               │
└────────────────── 共 2 个分类 ──────────┘
```

---

### `marketplace list`

浏览技能列表。

**范围（`--scope`）：**

| 范围 | 含义 |
|------|------|
| `all`（默认） | 公开广场（share_type 为 department 或 company） |
| `personal` | 个人相关（我创建的 + 分享给我的） |

**个人子筛选（`--sub`，仅 `--scope personal` 有效）：**

| 子筛选 | 含义 |
|--------|------|
| 不传（默认） | 我创建的 + 分享给我的 |
| `mine` | 仅我创建的 |
| `shared_with_me` | 仅他人分享给我的 |

```
选项：
  --scope TEXT        all（默认）/ personal
  --sub TEXT          mine / shared_with_me（仅 personal 有效）
  --category TEXT     按分类 slug 筛选
  --share-type TEXT   按分享类型筛选
  --sort TEXT         install_count（默认）/ usage_count / rating_avg / new
  --order TEXT        asc / desc（默认 desc）
  --page INT          页码（默认 1）
  --limit INT         每页条数（最多 100，默认 20）
  --official          只看官方技能
  --json              输出原始 JSON
```

```bash
opscli skills marketplace list
opscli skills marketplace list --sort rating_avg --limit 10
opscli skills marketplace list --category auth --official
opscli skills marketplace list --scope personal
opscli skills marketplace list --scope personal --sub mine
opscli skills marketplace list --scope personal --sub shared_with_me
```

---

### `marketplace search <keyword>`

按关键词搜索广场技能。

```bash
opscli skills marketplace search ops-auth
opscli skills marketplace search "数据查询" --limit 5
opscli skills marketplace search auth --sort rating --json
```

---

### `marketplace info <identifier>`

查看指定技能详情（元数据、统计、版本列表）。

```bash
opscli skills marketplace info pengjianchao@ops-auth
opscli skills marketplace info pengjianchao@ops-auth --json
```

---

### `marketplace versions <identifier>`

查看历史版本列表。

```bash
opscli skills marketplace versions pengjianchao@ops-auth
```

---

### `marketplace rate <identifier> <score>`

提交评分（1-5 分；小数自动 floor，如 4.7 → 4；重复调用更新已有评分）。

```
参数：
  identifier          username@skill_name
  score               1-5 的数字（小数自动 floor）

选项：
  --comment / -c TEXT 评价文字（最多 500 字符）
  --json              输出原始 JSON
```

```bash
opscli skills marketplace rate pengjianchao@ops-auth 5
opscli skills marketplace rate pengjianchao@ops-auth 4 --comment "非常实用！"
opscli skills marketplace rate pengjianchao@ops-auth 4.7  # → 自动取整为 4
opscli skills marketplace rate pengjianchao@ops-auth 5 --json
```

---

## 运行时全局路径

| 运行时 | 全局 Skills 路径 | 检测条件 |
|--------|----------------|---------|
| `claude`    | `~/.claude/skills/`           | `~/.claude/` 存在 或 `which claude` |
| `openclaw`  | `~/.openclaw/skills/`         | `~/.openclaw/` 存在 或 `which openclaw` |
| `codex`     | `~/.codex/skills/`            | `~/.codex/` 存在 或 `which codex` |
| `opencode`  | `~/.config/opencode/skills/`  | `~/.config/opencode/` 存在 或 `which opencode` |
| `workbuddy` | `~/.workbuddy/skills/`        | `~/.workbuddy/` 存在 或 `which workbuddy` |
| `trae-cn`   | `~/.trae-cn/skills/`          | `~/.trae-cn/` 存在 或 `which trae` |
| `agents`    | `~/.agents/skills/`           | `~/.agents/` 存在 或 `which agents` |

**安装模式说明：**

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| 模式 B（默认） | 不传 `--skills-dir` | 复制到中央存储，再软链到各工具目录 |
| 模式 A（兼容） | 传 `--skills-dir` | 直接复制到指定目录，不经过中央存储 |

**中央存储目录结构（模式 B）：**

```
~/.opscli/skills/<skill_name>/    # 中央存储（macOS/Linux）
├── SKILL.md
├── data/VERSION.json
└── ...

~/.claude/skills/<skill_name>     # 软链接 → 中央存储
~/.openclaw/skills/<skill_name>   # 软链接 → 中央存储
```

> Windows 中央存储路径为 `%LOCALAPPDATA%\opscli\skills\`，可通过环境变量 `OPSCLI_CENTRAL_SKILLS_DIR` 覆盖。

---

## 版本标识文件格式

`data/VERSION.json` 是 SkillDetector 的识别标志：

```json
{
  "name": "ops-skills",
  "version": "1.7.2"
}
```

- `name`：必须与 Skill 目录名一致
- `version`：格式 `{major}.{minor}.{patch}`，**不带 `v` 前缀**
