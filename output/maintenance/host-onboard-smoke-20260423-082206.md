# Host Onboard Smoke Guide

- Generated At: 2026-04-23T08:22:06.123182+00:00
- Project: E:\code\work\open-opscli
- Install Scope: project surfaces only
- Status: ok

## Claude Code

- Status: ready
- Standard Flow First Prompt: `/super-dev 你的需求`
- Competition Flow First Prompt: `/super-dev-seeai 比赛需求`
- Install Scope: project surfaces only

### Start Playbook
- 起手建议: 优先在当前 Claude Code 会话里直接用 /super-dev，不要先退回普通聊天交代背景。
- 避免动作: 不要先手写一串 spec / quality / release 命令来替代宿主入口。

### Post-Onboard Self-Check
- Claude Code 接入后先确认入口可用: /super-dev 你的需求 / /super-dev-seeai 比赛需求
- Claude Code 接入后再确认 SEEAI 项目补充面已写入: .claude/commands/super-dev-seeai.md / .claude/skills/super-dev-seeai/SKILL.md
- Claude Code 接入后再确认 SEEAI 用户级补充面已写入: ~/.claude/skills/super-dev-seeai/SKILL.md

### Official Workflow Checks
- 确认 Claude Code 按 official-skill 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认官方接入面真实生效: 项目侧 CLAUDE.md / .claude/CLAUDE.md / .claude/skills/super-dev/SKILL.md；用户侧 ~/.claude/skills/super-dev/SKILL.md / ~/.claude/agents/super-dev.md
- 如启用当前增强接入面，再确认: 项目侧 .claude/settings.json / .claude/settings.local.json；用户侧 ~/.claude/CLAUDE.md / ~/.claude/settings.json
- 确认 SEEAI 项目补充面真实生效: .claude/commands/super-dev-seeai.md / .claude/skills/super-dev-seeai/SKILL.md
- 确认 SEEAI 用户级补充面真实生效: ~/.claude/skills/super-dev-seeai/SKILL.md
- 确认当前 Claude Code 会话真实读取 CLAUDE.md、.claude/CLAUDE.md、可选 .claude/settings*.json、.claude/skills 与 .claude/agents，而不是只把文件写进仓库。

### Official Pass Criteria
- Claude Code 官方工作流面、入口链、恢复链与 SEEAI 补充面均已真人验收通过。
- 确认 Claude Code 按 official-skill 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认官方接入面真实生效: 项目侧 CLAUDE.md / .claude/CLAUDE.md / .claude/skills/super-dev/SKILL.md；用户侧 ~/.claude/skills/super-dev/SKILL.md / ~/.claude/agents/super-dev.md
- 如启用当前增强接入面，再确认: 项目侧 .claude/settings.json / .claude/settings.local.json；用户侧 ~/.claude/CLAUDE.md / ~/.claude/settings.json

### Resume Guidance
- 优先入口: /super-dev 你的需求 / /super-dev-seeai 比赛需求
- 原生恢复: /super-dev 继续当前流程 / 回当前 Claude Code 会话继续
- 优先沿用当前宿主会话恢复，不要先走新的普通聊天入口。

### Repair Playbook
-

### SEEAI Project Supplements
- `.claude/commands/super-dev-seeai.md`
- `.claude/skills/super-dev-seeai/SKILL.md`
- `plugins/super-dev-claude/skills/super-dev-seeai/SKILL.md`

### SEEAI User Supplements
- `~/.claude/skills/super-dev-seeai/SKILL.md`

### Written Surfaces
- `E:\code\work\open-opscli\.claude-plugin\marketplace.json`
- `E:\code\work\open-opscli\.claude\CLAUDE.md`
- `E:\code\work\open-opscli\.claude\agents\super-dev.md`
- `E:\code\work\open-opscli\.claude\commands\super-dev-seeai.md`
- `E:\code\work\open-opscli\.claude\commands\super-dev.md`
- `E:\code\work\open-opscli\.claude\settings.local.json`
- `E:\code\work\open-opscli\.claude\skills\super-dev-seeai\SKILL.md`
- `E:\code\work\open-opscli\.claude\skills\super-dev\SKILL.md`
- `E:\code\work\open-opscli\CLAUDE.md`
- `E:\code\work\open-opscli\plugins\super-dev-claude\.claude-plugin\plugin.json`
- `E:\code\work\open-opscli\plugins\super-dev-claude\README.md`
- `E:\code\work\open-opscli\plugins\super-dev-claude\skills\super-dev-seeai\SKILL.md`
- `E:\code\work\open-opscli\plugins\super-dev-claude\skills\super-dev\SKILL.md`

## Codex CLI

- Status: ready
- Standard Flow First Prompt: `$super-dev`
- Competition Flow First Prompt: `$super-dev-seeai`
- Install Scope: project surfaces only

### Start Playbook
- 起手建议: 在 Codex CLI 里优先显式输入 $super-dev，不要先把 App/Desktop 的 / 列表入口和 CLI 混成一个宿主。
- 避免动作: 不要一上来先跑一串 release / proof-pack / quality 命令。

### Post-Onboard Self-Check
- Codex CLI 接入后先确认入口可用: $super-dev / super-dev: 你的需求
- Codex CLI 接入后再确认 SEEAI 项目补充面已写入: .agents/skills/super-dev-seeai/SKILL.md / plugins/super-dev-codex/skills/super-dev-seeai/SKILL.md
- Codex CLI 接入后再确认 SEEAI 用户级补充面已写入: ~/.agents/skills/super-dev-seeai/SKILL.md

### Official Workflow Checks
- 确认 Codex CLI 按 official-skill 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认官方接入面真实生效: 项目侧 AGENTS.md / .agents/skills/super-dev/SKILL.md；用户侧 ~/.agents/skills/super-dev/SKILL.md
- 如启用当前增强接入面，再确认: 项目侧 .agents/plugins/marketplace.json / plugins/super-dev-codex/.codex-plugin/plugin.json；用户侧 ~/.codex/AGENTS.md
- 确认 SEEAI 项目补充面真实生效: .agents/skills/super-dev-seeai/SKILL.md / plugins/super-dev-codex/skills/super-dev-seeai/SKILL.md
- 确认 SEEAI 用户级补充面真实生效: ~/.agents/skills/super-dev-seeai/SKILL.md
- 确认当前 Codex CLI 会话里的 $super-dev 真实可用，并已读取仓库 AGENTS 与 Skills。

### Official Pass Criteria
- Codex CLI 官方工作流面、入口链、恢复链与 SEEAI 补充面均已真人验收通过。
- 确认 Codex CLI 按 official-skill 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认官方接入面真实生效: 项目侧 AGENTS.md / .agents/skills/super-dev/SKILL.md；用户侧 ~/.agents/skills/super-dev/SKILL.md
- 如启用当前增强接入面，再确认: 项目侧 .agents/plugins/marketplace.json / plugins/super-dev-codex/.codex-plugin/plugin.json；用户侧 ~/.codex/AGENTS.md

### Resume Guidance
- 优先入口: $super-dev / super-dev: 你的需求
- 原生恢复: $super-dev / super-dev: 继续当前流程
- 优先沿用当前 Skill / session 入口，不要先退回普通聊天。

### Repair Playbook
-

### SEEAI Project Supplements
- `.agents/skills/super-dev-seeai/SKILL.md`
- `plugins/super-dev-codex/skills/super-dev-seeai/SKILL.md`

### SEEAI User Supplements
- `~/.agents/skills/super-dev-seeai/SKILL.md`

### Written Surfaces
- `E:\code\work\open-opscli\.agents\plugins\marketplace.json`
- `E:\code\work\open-opscli\.agents\skills\super-dev-seeai\SKILL.md`
- `E:\code\work\open-opscli\.agents\skills\super-dev\SKILL.md`
- `E:\code\work\open-opscli\AGENTS.md`
- `E:\code\work\open-opscli\plugins\super-dev-codex\.codex-plugin\plugin.json`
- `E:\code\work\open-opscli\plugins\super-dev-codex\README.md`
- `E:\code\work\open-opscli\plugins\super-dev-codex\skills\super-dev-seeai\SKILL.md`
- `E:\code\work\open-opscli\plugins\super-dev-codex\skills\super-dev\SKILL.md`

## Claude

- Status: ready
- Standard Flow First Prompt: `super-dev: 你的需求`
- Competition Flow First Prompt: `super-dev-seeai: 比赛需求`
- Install Scope: project surfaces only

### Start Playbook
- 起手建议: 先在当前 Claude Project 里挂好 instructions / knowledge，再直接用 super-dev:。
- 避免动作: 不要把 Claude Desktop 当成有稳定仓库级 dotfile 注入的 CLI 宿主。

### Post-Onboard Self-Check
- Claude 接入后先确认入口可用: super-dev: 你的需求 / super-dev-seeai: 比赛需求
- 确认 Claude 按 official-projects 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- Claude 接入后再确认恢复链可用: 回当前 Claude Project 会话继续 / super-dev: 继续当前流程

### Official Workflow Checks
- 确认 Claude 按 official-projects 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认当前 Claude Project 真实挂上 Project Instructions、Project Knowledge 与需要的 extensions / MCP。

### Official Pass Criteria
- Claude 官方工作流面、入口链和恢复链均已真人验收通过。
- 确认 Claude 按 official-projects 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认当前 Claude Project 真实挂上 Project Instructions、Project Knowledge 与需要的 extensions / MCP。

### Resume Guidance
- 优先入口: super-dev: 你的需求 / super-dev-seeai: 比赛需求
- 原生恢复: 回当前 Claude Project 会话继续 / super-dev: 继续当前流程
- 优先沿用当前任务线程，不要重新开一个新的任务流。

### Repair Playbook
-

## Codex

- Status: ready
- Standard Flow First Prompt: `/super-dev 你的需求`
- Competition Flow First Prompt: `/super-dev-seeai 比赛需求`
- Install Scope: project surfaces only

### Start Playbook
- 起手建议: App/Desktop 优先从 / 列表里的 super-dev 进入，不要先退回普通聊天。
- 避免动作: 不要把桌面端入口和 CLI 的 $super-dev 混成同一个宿主。

### Post-Onboard Self-Check
- Codex 接入后先确认入口可用: /super-dev 你的需求 / super-dev: 你的需求
- Codex 接入后再确认 SEEAI 项目补充面已写入: .agents/skills/super-dev-seeai/SKILL.md / plugins/super-dev-codex/skills/super-dev-seeai/SKILL.md
- Codex 接入后再确认 SEEAI 用户级补充面已写入: ~/.agents/skills/super-dev-seeai/SKILL.md

### Official Workflow Checks
- 确认 Codex 按 official-skill 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认官方接入面真实生效: 项目侧 AGENTS.md / .agents/skills/super-dev/SKILL.md；用户侧 ~/.agents/skills/super-dev/SKILL.md
- 如启用当前增强接入面，再确认: 项目侧 .agents/plugins/marketplace.json / plugins/super-dev-codex/.codex-plugin/plugin.json；用户侧 ~/.codex/AGENTS.md
- 确认 SEEAI 项目补充面真实生效: .agents/skills/super-dev-seeai/SKILL.md / plugins/super-dev-codex/skills/super-dev-seeai/SKILL.md
- 确认 SEEAI 用户级补充面真实生效: ~/.agents/skills/super-dev-seeai/SKILL.md
- 确认 Codex App/Desktop 的 / 列表 super-dev 真实可用，并已读取仓库 AGENTS 与 Skills。

### Official Pass Criteria
- Codex 官方工作流面、入口链、恢复链与 SEEAI 补充面均已真人验收通过。
- 确认 Codex 按 official-skill 官方协议面真实加载 Super Dev，而不是只检测到文件存在。
- 确认官方接入面真实生效: 项目侧 AGENTS.md / .agents/skills/super-dev/SKILL.md；用户侧 ~/.agents/skills/super-dev/SKILL.md
- 如启用当前增强接入面，再确认: 项目侧 .agents/plugins/marketplace.json / plugins/super-dev-codex/.codex-plugin/plugin.json；用户侧 ~/.codex/AGENTS.md

### Resume Guidance
- 优先入口: /super-dev 你的需求 / super-dev: 你的需求
- 原生恢复: /super-dev 继续当前流程 / 回当前 Codex 会话继续
- 优先沿用当前 Skill / session 入口，不要先退回普通聊天。

### Repair Playbook
-

### SEEAI Project Supplements
- `.agents/skills/super-dev-seeai/SKILL.md`
- `plugins/super-dev-codex/skills/super-dev-seeai/SKILL.md`

### SEEAI User Supplements
- `~/.agents/skills/super-dev-seeai/SKILL.md`

### Written Surfaces
- `E:\code\work\open-opscli\AGENTS.md`
