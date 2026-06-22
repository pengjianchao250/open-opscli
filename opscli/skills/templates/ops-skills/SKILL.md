---
name: ops-skills
description: 管理 AI 工具中已安装的 Skill 生命周期，包含技能广场的发布、编辑、安装、浏览与评分。当用户需要：安装/升级/列出 Skill、发布或编辑广场技能、浏览技能广场、查看已安装技能版本状态、管理多运行时 Skill 时使用。所有操作通过 opscli skills 子命令完成。触发场景：发布到广场、发布到技能广场、把技能发布到广场、发布skill到广场、发布到运营系统广场、发布到BI广场、上传skill到广场、把技能上架到广场、把这个skill发布出去、发布新版skill、提交技能到广场、publish skill、发布技能、上架技能、分享技能。
version: 1.7.3
---

# ops-skills

管理 Claude Code、OpenClaw、Codex CLI、OpenCode 中 Skill 的完整生命周期，所有操作通过 `opscli skills` 子命令执行。

三大能力域：**本地生命周期**（列表、安装、状态、升级）、**技能广场**（浏览、搜索、安装、评分）、**发布管理**（发布、编辑、下架）

---

## 运行模式判断

`ops-skills` 仅提供 CLI 入口，无 MCP 版本。默认执行 `opscli skills` 命令；首次调用失败则提示用户安装 `aukeys-opscli`，无需额外检测。

---

## 强制认证门禁

**进入本 Skill 后，第一步必须执行 `opscli auth token status`**，根据结果：

- 未登录/未授权/401 → 切换 `ops-auth` Skill，执行 `opscli auth login`
- JWT 过期 → 优先 `opscli auth token refresh --all`，失败再执行 `opscli auth login`
- 通过后才执行后续命令（即使当前任务仅涉及本地操作也不可跳过）

```bash
opscli auth token status          # 第一步：检查登录状态
opscli auth token refresh --all   # JWT 过期时先刷新
opscli auth login                 # 未登录或刷新失败时登录
```

---

## 发布版本号铁律

**发布新版 Skill 前，必须同步更新版本号：**

1. 读取 `data/VERSION.json` 中的 `version`（如 `"1.7.1"`）
2. 按规则递增：patch 逢 100 进 minor，minor 逢 100 进 major（从 `0.0.1` 起）
3. 更新 `data/VERSION.json`（无 `v` 前缀，如 `"1.7.2"`）
4. 同步更新 `SKILL.md` frontmatter（无 `v` 前缀，如 `1.7.2`）
5. `--version` 参数值必须与 `VERSION.json` 一致

**首次发布注意**：新创建的 Skill 应从 `0.0.1` 开始，而非 `1.0.0`。若 `VERSION.json` 中未指定 `version` 字段，系统将自动使用 `0.0.1` 作为初始版本。

**发布前一致性检查：**

```
data/VERSION.json: "1.7.2"（无 v）
SKILL.md frontmatter: "1.7.2"（无 v）
--version 参数: "1.7.2"（无 v，仅 edit 时）
→ 三者必须完全相同，全部不带 v 前缀
```

---

## 发布范围铁律

**发布 Skill 时，禁止主动添加 `--share-type`，除非用户明确指定分享范围。**

- CLI 默认值已为 `personal`（仅本人可见），直接 `opscli skills publish` 即可，无需传参
- 只有用户明确说"全员"、"公司级"、"部门可见"等时，才加 `--share-type company/department`
- ❌ 错误：用户只说"帮我发布" → 自行追加 `--share-type company`
- √ 正确：用户只说"帮我发布" → 执行 `opscli skills publish --changelog "..."` 不加 `--share-type`

---

## 使用原则

- **安装模式**：
  - 默认（模式 B）：先复制到中央存储 `~/.opscli/skills/<name>/`，再软链到各工具目录
  - 显式 `--skills-dir`（模式 A）：直接复制到指定目录，不使用中央存储
- **支持运行时**：`claude` / `openclaw` / `codex` / `opencode` / `workbuddy` / `trae-cn` / `agents`
- **幂等安装**：已存在时默认跳过，`--force` 强制覆盖
- **升级范围**：仅 `ops-dataset-query` 支持远端数据升级；`ops-auth` / `ops-skills` 为本地静态 Skill

---

## 内置可安装 Skill

| Skill 名称 | 说明 | 支持远端升级 |
|-----------|------|------------|
| `ops-auth` | 认证授权管理 | 否 |
| `ops-dataset-query` | 数据集查询（metadata + query） | 是 |
| `ops-amazon` | Amazon 抓取工作流 | 否 |
| `ops-skills` | Skill 生命周期管理（本 Skill） | 否 |

> 技能广场上还有更多社区 Skill，通过 `opscli skills marketplace list` 浏览，或直接用 `opscli skills install username@skill_name` 远程安装。

---

## 命令速查

| 命令 | 用途 |
|------|------|
| `opscli skills list` | 列出已安装 Skill |
| `opscli skills status` | 查看本地 vs 远端版本 |
| `opscli skills install [name\|username@skill]` | 安装（内置模板或广场远程） |
| `opscli skills install --sync-market [--dry-run]` | 从广场同步安装记录 |
| `opscli skills sync-exclude <add\|remove\|list>` | 管理同步排除名单 |
| `opscli skills upgrade [name]` | 升级（当前仅 ops-dataset-query） |
| `opscli skills publish` | 发布到广场 |
| `opscli skills edit <identifier>` | 编辑已发布技能 |
| `opscli skills unpublish <identifier>` | 下架技能 |
| `opscli skills marketplace <list\|search\|info\|rate\|categories>` | 广场操作 |

完整参数说明与示例 → [references/commands.md](references/commands.md)

---

## 安装后评分引导

远程安装（`username@skill_name`）成功后，**必须**立即用 `AskUserQuestion` 工具触发两步评分流程：

1. 询问是否评分（选项：是/暂不评分）
2. 若选"是"，询问具体分数（2-5 分；"其他"可输入 1）
3. 自动执行：`opscli skills marketplace rate <identifier> <score>`

完整引导脚本与示例 → [references/rating-guide.md](references/rating-guide.md)

---

## 典型工作流

### 全新环境初始化

```bash
opscli auth token status          # 认证检查
opscli skills install             # TUI 批量安装
opscli skills list --pretty       # 验证安装
opscli skills status --pretty     # 检查版本
```

### 发布新版 Skill

```bash
# 1. 按铁律更新版本号（VERSION.json + SKILL.md frontmatter 同步）
# 2. 发布（禁止自行加 --share-type，用户未指定范围时不传该参数，默认个人可见）
opscli skills publish --changelog "变更说明"
# 3. 确认
opscli skills marketplace info pengjianchao@my-skill
```

### 从广场发现并安装技能

```bash
opscli auth token status
opscli skills marketplace list
opscli skills marketplace search "数据查询"
opscli skills install pengjianchao@ops-auth
# 安装成功后触发评分引导（见 references/评分引导.md）
```

更多场景（多运行时、强制重置、CI 环境、同步市场等）→ [references/workflows.md](references/workflows.md)

---

## 错误排查

常见错误原因与解决方案 → [references/troubleshooting.md](references/troubleshooting.md)

---

## 参考文档

| 文档 | 内容 |
|------|------|
| [references/commands.md](references/commands.md) | 所有命令的完整参数说明与示例 |
| [references/workflows.md](references/workflows.md) | 9 个典型使用场景的完整步骤 |
| [references/rating-guide.md](references/rating-guide.md) | 安装后评分的 AskUserQuestion 完整流程 |
| [references/troubleshooting.md](references/troubleshooting.md) | 常见错误原因与解决方案 |
