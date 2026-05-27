---
name: ops-skills-sync
description: 扫描各 AI 工具（Claude Code、OpenClaw、Codex、OpenCode、WorkBuddy、Trae Solo）中已安装的 Skills，并将其同步到其他 AI 工具。当用户说「把我的 Skills 同步到 Trae」「新装了 OpenClaw，复制 Claude 的技能」「扫描一下哪些工具装了哪些 Skill」时使用。同步操作直接在各工具 skills 目录之间操作，不依赖 opscli install 流程。
version: 0.1.0
---

# ops-skills-sync

同机跨 AI 工具的 Skill 目录同步工具。扫描各工具 skills 目录中已安装的 Skills，并通过符号链接（macOS/Linux）或 Junction（Windows）将其同步到目标工具。

---

## 快速开始

```bash
# 扫描所有工具下已安装的 Skills
python scripts/sync.py scan

# 把 Claude 的所有 Skills 同步到所有检测到的其他工具
python scripts/sync.py sync --from claude

# 只同步指定 Skills 到 Trae
python scripts/sync.py sync --from claude --to trae-cn --skills ops-auth,ops-dataset-query

# 同步到自定义目录
python scripts/sync.py sync --from-dir ~/.claude/skills --to-dir /custom/path/skills
```

---

## 支持的 AI 工具

| 工具标识 | 说明 |
|----------|------|
| `claude` | Claude Code（`~/.claude/skills/`） |
| `openclaw` | OpenClaw（`~/.openclaw/skills/`） |
| `codex` | Codex CLI（`~/.codex/skills/`） |
| `opencode` | OpenCode（`~/.config/opencode/skills/`） |
| `workbuddy` | WorkBuddy（`~/.workbuddy/skills/`） |
| `trae-cn` | Trae Solo（`~/.trae-cn/skills/`） |

**检测条件**：配置根目录存在 或 对应命令在 PATH 中可用。

---

## scan 子命令

扫描各 AI 工具 skills 目录，输出已安装 Skill 列表。

**执行前，AI Agent 必须先用 `AskUserQuestion` 询问扫描类型**，再带 `--type` 参数调用脚本：

```
问题：要扫描哪种类型的 Skill？
选项：
  A. 仅 opscli 规范 Skill（默认）  — 只识别带 data/VERSION.json 的 Skill
  B. 全部 Skill                    — 同时识别只有 SKILL.md 的 Skill（superpowers 类）
```

```bash
python scripts/sync.py scan [--tool TOOL] [--type opscli|all]
```

| 参数 | 说明 |
|------|------|
| `--tool` | 只扫描指定工具（不填则扫描全部） |
| `--type` | `opscli`（默认）/ `all`（含 superpowers 类 Skill） |

**输出示例**：

```json
{
  "success": true,
  "command": "skill-sync scan",
  "data": {
    "tools": [
      {
        "tool": "claude",
        "skills_dir": "/Users/mask/.claude/skills",
        "detected": true,
        "skills": [
          { "name": "ops-auth", "version": "v1.2.0" },
          { "name": "ops-dataset-query", "version": "v2.1.0" }
        ]
      },
      {
        "tool": "trae-cn",
        "skills_dir": "/Users/mask/.trae-cn/skills",
        "detected": false,
        "skills": []
      }
    ]
  },
  "error": null
}
```

- `detected: false`：该工具未安装或目录不存在
- Skill 识别条件：子目录内存在 `data/VERSION.json`

---

## sync 子命令

将 Skills 从来源工具同步到目标工具。目标已存在时直接覆盖，无需 `--force`。

```bash
python scripts/sync.py sync \
  [--from TOOL | --from-dir PATH] \
  [--to TOOL[,TOOL] | --to-dir PATH] \
  [--skills NAME[,NAME]]
```

| 参数 | 说明 |
|------|------|
| `--from TOOL` | 来源工具标识（不填则自动检测有 Skill 的工具） |
| `--from-dir PATH` | 来源 skills 目录完整路径（与 `--from` 互斥） |
| `--to TOOL[,TOOL]` | 目标工具，逗号分隔（不填则同步到所有检测到的工具） |
| `--to-dir PATH` | 目标 skills 目录完整路径（与 `--to` 互斥） |
| `--skills NAME[,NAME]` | 只同步指定 Skill（不填则同步全部） |
| `--type` | `opscli`（默认）/ `all`（含 superpowers 类），影响未指定 `--skills` 时的来源扫描范围 |

**输出示例**：

```json
{
  "success": true,
  "command": "skill-sync sync",
  "data": {
    "from": { "tool": "claude", "skills_dir": "/Users/mask/.claude/skills" },
    "results": [
      {
        "skill": "ops-auth",
        "target_tool": "trae-cn",
        "target_path": "/Users/mask/.trae-cn/skills/ops-auth",
        "method": "symlink",
        "replaced": true,
        "success": true,
        "error": null
      }
    ],
    "summary": { "total": 2, "success": 2, "failed": 0 }
  },
  "error": null
}
```

- `method`：`symlink`（macOS/Linux）、`junction`（Windows）、`copy_fallback`（Windows 降级）
- `replaced: true`：覆盖了目标已有内容

---

## 默认执行策略

用户说「同步 Skills」「扫描/列出」「把 XXX 的技能复制到 YYY」时：

1. **用 `AskUserQuestion` 询问扫描类型**（仅 opscli 规范 / 全部含 superpowers 类）
2. 带 `--type` 参数执行 `scan`，了解当前各工具安装情况
3. 根据用户描述确定来源工具和目标工具（缺失时追问）
4. 执行 `sync --type <用户选择>` 并解读输出结果告知用户
5. 如有失败条目，说明原因并给出建议

**不需要每次都重新解释工具检测规则或文件操作细节**；只在用户明确要求解释流程、或出现异常时展开说明。

---

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 指定工具名不在支持列表 | 输出错误 JSON，退出码 1，提示支持的工具列表 |
| 来源 skills 目录不存在 | 输出错误 JSON，退出码 1 |
| 来源 Skill 子目录不存在 | 该条目 `success: false`，继续处理其他条目 |
| 链接/复制失败 | 该条目 `success: false`，记录错误原因，全部处理完后退出码 1 |
| 来源与目标路径相同 | 自动跳过，不报错 |
| 未检测到任何目标工具 | 输出错误 JSON，提示使用 `--to` 或 `--to-dir` 手动指定 |

---

## 输出规范

- 所有输出均为 JSON，格式：`{ "success": bool, "command": str, "data": {...}, "error": null | {...} }`
- 退出码：0 表示全部成功，1 表示有失败或参数错误
- `data.results` 中每条记录独立标记 `success`，部分失败时顶层 `success: false`

---

## 按需加载资料

| 场景 | 读取 |
|------|------|
| 了解完整设计背景和技术方案 | `references/flow-map.md` |
| 需要解释文件操作策略（symlink/junction/copy） | `references/flow-map.md` 的「文件操作策略」章节 |

---

## 执行日志与候选提交

本 Skill 为基础工具类，日常不需要执行日志。  
如需团队共享，通过 `opscli skills publish` 发布到技能广场。
