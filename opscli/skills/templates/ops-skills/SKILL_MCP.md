---
name: ops-skills
mcp-version: v1.0.0
description: 通过 MCP Tool 管理 AI 工具中已安装的 Skill 生命周期（无状态模式）
---

# ops-skills (MCP 无状态模式)

通过 MCP Tool 管理 Claude Code、OpenClaw、Codex CLI、OpenCode 中已安装的 Skill 生命周期。

**无状态模式**：服务器负责本地路径扫描、模板安装和远端数据拉取；调用方无需管理会话状态，所有认证由服务器端内部处理。

---

## 概述

`ops-skills` 是 Aukeys 运营工具体系的 Skill 生命周期管理器。它负责：

- **发现**：扫描全局路径，识别所有已安装的 Skill
- **安装**：从内置模板将 Skill 部署到目标运行时的全局目录
- **版本检查**：对比本地版本与远端最新版本，告知是否需要升级
- **升级**：拉取远端最新数据，原子替换本地文件，确保数据不中断

---

## 使用原则

- **全局路径优先**：安装目标由服务器自动检测全局 Skills 路径（如 `~/.claude/skills/`、`~/.openclaw/skills/` 等），也可通过 `skills_dir` 显式指定
- **支持的运行时**：Claude Code（`claude`）、OpenClaw（`openclaw`）、Codex CLI（`codex`）、OpenCode（`opencode`）
- **升级范围**：只有 `ops-dataset-query` 支持远端数据升级；`ops-auth` 和 `ops-skills` 为本地静态 Skill，无需升级
- **幂等安装**：默认不覆盖已存在的安装，需要 `force=True` 才会覆盖
- **原子升级**：升级过程先下载到临时目录，验证完成后再替换，避免升级中途失败导致数据损坏
- **认证说明**：
  - `skills_list`、`skills_install` 为纯本地操作，无需认证
  - `skills_status`、`skills_upgrade` 涉及远端 API 调用，由服务器端内部处理认证；如服务器端未登录，upgrade 可能返回认证错误

---

## 内置可安装 Skill

| Skill 名称 | 说明 | 支持远端升级 |
|-----------|------|------------|
| `ops-auth` | 认证授权管理（登录、Token 查看与刷新、系统管理） | 否 |
| `ops-dataset-query` | 数据集字段索引与查询转发（支持 metadata 拉取和 query 执行） | 是 |
| `ops-amazon` | Amazon 商品页与搜索结果抓取工作流指导 | 否 |
| `ops-skills` | Skill 生命周期管理（本 Skill） | 否 |

---

## MCP Tool 调用参考

### `skills_list`

列出当前环境中已安装的所有 Skill（扫描全局路径）。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定扫描目录（覆盖默认自动检测路径） |

**调用示例**：
```python
skills_list()
skills_list(skills_dir="/Users/mask/.config/opencode/skills")
```

**返回结构**：
```json
{
  "success": true,
  "data": [
    {
      "name": "ops-auth",
      "version": "v1.0.0",
      "runtime": "claude-code",
      "root": "/Users/you/.claude/skills/ops-auth",
      "version_file": "/Users/you/.claude/skills/ops-auth/data/VERSION.json"
    },
    {
      "name": "ops-dataset-query",
      "version": "v2.1.0",
      "runtime": "claude-code",
      "root": "/Users/you/.claude/skills/ops-dataset-query",
      "version_file": "/Users/you/.claude/skills/ops-dataset-query/data/VERSION.json"
    }
  ]
}
```

---

### `skills_status`

查询 Skill 安装状态，包含本地版本与远端最新版本对比。涉及远端 API 调用。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定扫描目录（覆盖默认自动检测路径） |

**调用示例**：
```python
skills_status()
skills_status(skills_dir="/Users/mask/.config/opencode/skills")
```

**返回结构**：
```json
{
  "success": true,
  "data": {
    "skills": [
      {
        "name": "ops-auth",
        "local_version": "v1.0.0",
        "remote_version": null,
        "has_update": false,
        "installed_paths": [
          {"tool": "claude-code", "path": "/Users/you/.claude/skills/ops-auth"}
        ]
      },
      {
        "name": "ops-dataset-query",
        "local_version": "v2.0.0",
        "remote_version": "v2.1.0",
        "has_update": true,
        "installed_paths": [
          {"tool": "claude-code", "path": "/Users/you/.claude/skills/ops-dataset-query"}
        ]
      }
    ],
    "installed": [
      {
        "name": "ops-dataset-query",
        "version": "v2.0.0",
        "runtime": "claude-code",
        "root": "/Users/you/.claude/skills/ops-dataset-query",
        "version_file": "/Users/you/.claude/skills/ops-dataset-query/data/VERSION.json",
        "remote_version": "v2.1.0",
        "has_update": true
      }
    ],
    "remote_manifest": {"version": "v2.1.0", ...},
    "remote_summary": {...},
    "remote_error": null
  }
}
```

**字段说明**：
| 字段 | 说明 |
|------|------|
| `skills` | 按名称聚合的安装摘要（含远端版本对比） |
| `installed` | 完整的安装记录列表（含 runtime、path、version） |
| `remote_manifest` | 远端 manifest 数据，无远端来源则为 `null` |
| `remote_error` | 远端请求失败时的错误信息 |

---

### `skills_install`

从内置模板安装 Skill 到全局运行时目录。**纯本地操作，不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Skill 名称（如 `ops-auth`、`ops-dataset-query`） |
| `skills_dir` | string | 否 | 安装到指定目录（覆盖自动检测） |
| `runtime` | string | 否 | 目标运行时：`claude` / `openclaw` / `codex` / `opencode` |
| `force` | boolean | 否 | 是否覆盖已有安装，默认 `false` |

**调用示例**：
```python
# 安装到默认检测路径
skills_install(name="ops-auth")
skills_install(name="ops-dataset-query")

# 指定运行时
skills_install(name="ops-auth", runtime="claude")
skills_install(name="ops-dataset-query", runtime="opencode")

# 安装到指定目录
skills_install(name="ops-auth", skills_dir="/Users/mask/.config/opencode/skills")

# 强制覆盖
skills_install(name="ops-dataset-query", force=True)
```

**返回结构**（成功）：
```json
{
  "success": true,
  "data": {
    "name": "ops-auth",
    "version": "v1.0.0",
    "installed_paths": [
      {
        "tool": "claude-code",
        "path": "/Users/you/.claude/skills/ops-auth",
        "replaced": false
      }
    ]
  }
}
```

---

### `skills_upgrade`

升级指定 Skill 到远端最新版本（当前仅 `ops-dataset-query` 支持远端升级）。涉及远端 API 调用。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | Skill 名称，默认 `ops-dataset-query` |
| `skills_dir` | string | 否 | 指定扫描目录 |
| `force` | boolean | 否 | 强制重新拉取（即使版本号相同），默认 `false` |

**调用示例**：
```python
# 升级默认 Skill（ops-dataset-query）
skills_upgrade()

# 显式指定 Skill 名称
skills_upgrade(name="ops-dataset-query")

# 强制重新拉取
skills_upgrade(name="ops-dataset-query", force=True)

# 指定目录
skills_upgrade(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")
```

**返回结构**（有更新）：
```json
{
  "success": true,
  "data": {
    "updated": [
      {
        "name": "ops-dataset-query",
        "from_version": "v2.0.0",
        "to_version": "v2.1.0",
        "field_count": 150,
        "tools": ["claude-code"]
      }
    ],
    "already_latest": [],
    "failed": []
  }
}
```

**返回结构**（已是最新）：
```json
{
  "success": true,
  "data": {
    "updated": [],
    "already_latest": [
      {
        "name": "ops-dataset-query",
        "from_version": "v2.1.0",
        "to_version": "v2.1.0",
        "field_count": 150,
        "tools": ["claude-code"]
      }
    ],
    "failed": []
  }
}
```

---

## 运行时全局路径说明

ops-skills 检测以下全局路径来发现已安装的 Skill：

| 运行时 | 全局 Skills 路径 |
|--------|----------------|
| Claude Code | `~/.claude/skills/` |
| OpenClaw | `~/.openclaw/skills/` |
| Codex CLI | `~/.codex/skills/` |
| OpenCode | `~/.opencode/skills/` |

> 注意：检测路径为全局用户目录（`~/`），而非项目级目录。这确保 Skill 在所有项目中均可使用，无需每个项目单独安装。

---

## 典型工作流

### 场景一：全新环境初始化

在新机器或新用户目录中，首次配置所有 Skill：

```python
# 1. 列出当前已安装 Skill
skills_list()

# 2. 安装 ops-auth（认证管理）
skills_install(name="ops-auth")

# 3. 安装 ops-dataset-query（数据查询）
skills_install(name="ops-dataset-query")

# 4. 安装 ops-skills（本 Skill，通常已内置）
skills_install(name="ops-skills")

# 5. 验证安装结果
skills_list()

# 6. 检查版本状态（含远端对比）
skills_status()
```

### 场景二：日常版本维护

定期检查并更新 Skills，确保数据集查询功能使用最新字段索引：

```python
# 1. 检查所有 Skill 的版本状态
skills_status()

# 2. 如果 ops-dataset-query 有新版本，执行升级
skills_upgrade(name="ops-dataset-query")

# 3. 如需强制重新拉取
skills_upgrade(name="ops-dataset-query", force=True)

# 4. 验证升级后的版本
skills_list()
```

### 场景三：指定路径安装（CI/脚本环境）

在自动化脚本或 CI 环境中，指定明确路径跳过交互：

```python
# 安装到指定目录
skills_install(
    name="ops-dataset-query",
    skills_dir="/Users/mask/.config/opencode/skills",
    force=True
)

# 检查指定目录下的状态
skills_status(skills_dir="/Users/mask/.config/opencode/skills")
```

### 场景四：强制重置安装

当 Skill 文件损坏或需要回退到内置版本时：

```python
# 强制覆盖安装（重置为内置模板版本）
skills_install(name="ops-auth", force=True)
skills_install(name="ops-dataset-query", force=True)

# 如需同时重置远端数据，再执行升级
skills_upgrade(name="ops-dataset-query", force=True)
```

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 未检测到任何运行时 | 使用 `skills_install(name="...", runtime="claude")` 显式指定，服务器会自动创建目录 |
| Skill 已存在 | 指定 `force=True` 覆盖，或先确认是否需要保留 |
| 升级失败：网络不可达 | 检查网络连通性，重试；如持续失败可调用 `auth_doctor()` 诊断 |
| 升级失败：认证错误 | 服务器端未登录，需通过 ops-auth Skill 完成 Device Flow 授权 |
| 升级失败：远端服务异常 | 稍后重试，或联系运维人员 |
| 安装失败：内置模板不存在 | 确认 Skill 名称拼写正确，可选值为 `ops-auth`、`ops-dataset-query`、`ops-amazon`、`ops-skills` |

---

## 版本标识文件格式

每个 Skill 目录下的 `data/VERSION.json` 是识别标志。格式为：

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

1. **不修改 VERSION.json**：手动修改版本文件会导致 `skills_status` 产生误判，请勿手动编辑
2. **升级不影响认证**：`ops-dataset-query` 升级的是字段元数据，不会清除已登录的凭证
3. **多运行时独立管理**：每个运行时（claude/openclaw/codex/opencode）的 Skills 目录相互独立，安装和升级互不影响
4. **全局 vs 项目级**：Skills 安装在全局路径（`~/`），对该用户下所有项目生效，无需在每个项目中单独安装
5. **`skills_upgrade` 仅支持 `ops-dataset-query`**：其他 Skill（`ops-auth`、`ops-skills`、`ops-amazon`）为静态模板，无需远端升级
6. **`skills_install` 不依赖认证**：纯本地文件操作，但 `skills_upgrade` 需要服务器端已登录才能访问远端 API
