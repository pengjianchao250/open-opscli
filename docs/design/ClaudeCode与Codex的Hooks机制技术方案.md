# Claude Code 与 Codex Hooks 机制技术方案

> 本文档说明如何利用 Claude Code 和 Codex CLI 的 Hooks 机制，在 Skill 调用后自动触发上报命令（如 `opscli skills report-usage`），实现使用次数统计。

---

## 一、概述

### 1.1 什么是 Hooks

Hooks 是 AI 编程工具（Claude Code、Codex CLI）提供的生命周期扩展机制，允许在工具调用的前后注入自定义 shell 脚本，实现：

- 使用次数上报 / 埋点统计
- 敏感内容拦截（如防止粘贴 API Key）
- 自定义校验与合规检查
- 会话日志落地与分析

### 1.2 两种工具的对比

| 特性 | Claude Code | Codex CLI |
|------|-------------|-----------|
| 配置文件 | `.claude/settings.json` | `.codex/hooks.json` 或 `.codex/config.toml` |
| Skill tool name | `Skill` | `mcp__<server>__<tool>` |
| Hook 并发模型 | 串行执行 | **并发执行**（同事件多 hook 同时触发） |
| 信任机制 | 无需显式信任 | 必须 `/hooks` 手动 Trust（或 `--dangerously-bypass-hook-trust`） |
| 异步 Hook | 支持 | 已解析但暂未实现（`async: true` 会被跳过） |
| stdin 格式 | JSON | JSON（与 Claude Code 相同协议） |

---

## 二、Claude Code 配置方案

### 2.1 配置文件位置

- **全局**：`~/.claude/settings.json`
- **项目级**：`<repo>/.claude/settings.json`

### 2.2 配置示例

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Skill",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 \"$(git rev-parse --show-toplevel)/.claude/hooks/report_skill_usage.py\"",
            "statusMessage": "上报 Skill 使用次数"
          }
        ]
      }
    ]
  }
}
```

### 2.3 Hook 脚本（`.claude/hooks/report_skill_usage.py`）

```python
#!/usr/bin/env python3
"""PostToolUse hook：上报 Skill 使用次数（Claude Code）"""
import json, sys, subprocess

data = json.load(sys.stdin)

tool_input   = data.get("tool_input", {})
session_id   = data.get("session_id", "")
cwd          = data.get("cwd", ".")

# Claude Code 的 Skill 工具，tool_input.skill 即 skill 名称
skill_name = tool_input.get("skill", "unknown")

subprocess.run(
    ["opscli", "skills", "report-usage", "--skill", skill_name, "--session", session_id],
    cwd=cwd,
    capture_output=True,  # 不让输出干扰主流程
)

sys.exit(0)
```

### 2.4 stdin 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 当前会话 ID |
| `hook_event_name` | string | 当前事件名，如 `PostToolUse` |
| `tool_name` | string | 工具名，Claude Code 中为 `Skill` |
| `tool_input` | JSON | 工具入参，`tool_input.skill` 是 skill 名称，`tool_input.args` 是参数 |
| `tool_response` | JSON | 工具返回结果 |
| `cwd` | string | 工作目录 |

---

## 三、Codex CLI 配置方案

### 3.1 配置文件位置（优先级从低到高）

```
~/.codex/hooks.json          # 全局用户级
~/.codex/config.toml         # 全局用户级（TOML 格式）
<repo>/.codex/hooks.json     # 项目级（推荐）
<repo>/.codex/config.toml    # 项目级（TOML 格式）
```

> 多个配置文件**同时生效**，高优先级不会覆盖低优先级，所有匹配的 hook 都会执行。

### 3.2 Matcher 说明

Codex 中 Skill 通过 MCP 服务暴露，tool name 格式为 `mcp__<server>__<tool>`。

| 场景 | matcher 值 |
|------|-----------|
| skill-seeker 所有工具 | `mcp__skill-seeker__.*` |
| 所有 MCP 工具 | `mcp__.*` |
| 特定工具 | `mcp__skill-seeker__install_skill` |
| 所有工具（含 Bash） | 省略 matcher 或留空 |
| Bash 命令 | `Bash` |
| 文件编辑 | `Edit\|Write` 或 `apply_patch` |

### 3.3 配置示例（`hooks.json` 格式）

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__skill-seeker__.*",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/report_skill_usage.py\"",
            "statusMessage": "上报 Skill 使用次数",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### 3.4 配置示例（`config.toml` 格式）

```toml
[[hooks.PostToolUse]]
matcher = "mcp__skill-seeker__.*"

[[hooks.PostToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/report_skill_usage.py"'
timeout = 10
statusMessage = "上报 Skill 使用次数"
```

### 3.5 Hook 脚本（`.codex/hooks/report_skill_usage.py`）

```python
#!/usr/bin/env python3
"""PostToolUse hook：上报 Skill 使用次数（Codex CLI）"""
import json, sys, subprocess

data = json.load(sys.stdin)

tool_name    = data.get("tool_name", "")       # 如 mcp__skill-seeker__install_skill
tool_input   = data.get("tool_input", {})
session_id   = data.get("session_id", "")
cwd          = data.get("cwd", ".")

# MCP tool name 格式：mcp__<server>__<tool>，提取最后一段作为操作名
operation  = tool_name.split("__")[-1] if "__" in tool_name else tool_name
# skill 名称从 tool_input 中取（skill-seeker 工具通常有 name/skill_name 参数）
skill_name = tool_input.get("name") or tool_input.get("skill_name") or operation

subprocess.run(
    ["opscli", "skills", "report-usage", "--skill", skill_name, "--session", session_id],
    cwd=cwd,
    capture_output=True,
)

sys.exit(0)
```

### 3.6 stdin 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 当前会话 ID |
| `hook_event_name` | string | 当前事件名，如 `PostToolUse` |
| `turn_id` | string | Codex 专属，当前 turn ID |
| `model` | string | Codex 专属，当前模型 slug |
| `tool_name` | string | 完整 tool name，如 `mcp__skill-seeker__install_skill` |
| `tool_use_id` | string | 本次调用 ID |
| `tool_input` | JSON | 工具入参（MCP 工具传入完整参数对象） |
| `tool_response` | JSON | 工具返回结果 |
| `cwd` | string | 工作目录 |
| `permission_mode` | string | 当前权限模式：`default`/`acceptEdits`/`plan`/`dontAsk`/`bypassPermissions` |

---

## 四、信任与审核（Codex 专属）

Codex 要求所有非托管 hook 必须经过 review 后才能执行。

### 4.1 交互式信任

在 Codex CLI 中执行：

```
/hooks
```

在弹出界面中选择 **Trust** 当前 hook 定义。每次 hook 文件内容变更后需重新信任。

### 4.2 一次性跳过（仅限 CI/自动化）

```bash
codex --dangerously-bypass-hook-trust "执行任务..."
```

### 4.3 企业级托管 Hook（`requirements.toml`）

适用于需要强制推送给所有用户的场景：

```toml
allow_managed_hooks_only = true

[features]
hooks = true

[[hooks.PostToolUse]]
matcher = "mcp__skill-seeker__.*"

[[hooks.PostToolUse.hooks]]
type = "command"
command = "python3 /enterprise/hooks/report_skill_usage.py"
timeout = 10
```

---

## 五、支持的 Hook 事件总览

| 事件 | 触发时机 | matcher 过滤目标 | 适合上报场景 |
|------|----------|-----------------|------------|
| `PostToolUse` | 工具调用完成后 | tool name | **Skill 调用后上报**（推荐） |
| `PreToolUse` | 工具调用前 | tool name | 拦截 / 鉴权前置 |
| `UserPromptSubmit` | 用户提交 prompt 后 | 不支持 | 提示词审计 |
| `Stop` | 每轮对话结束时 | 不支持 | 会话级统计汇总 |
| `SessionStart` | 会话启动或恢复时 | 启动来源 | 加载偏好 / 初始化 |
| `SubagentStart` | 子 Agent 启动时 | agent type | 子任务追踪 |
| `SubagentStop` | 子 Agent 停止时 | agent type | 子任务结果归档 |
| `PreCompact` / `PostCompact` | 会话压缩前/后 | `manual\|auto` | 压缩策略控制 |

---

## 六、目录结构建议

```
<repo>/
├── .claude/
│   ├── settings.json          # Claude Code hook 配置
│   └── hooks/
│       └── report_skill_usage.py   # Claude Code hook 脚本
└── .codex/
    ├── hooks.json             # Codex hook 配置
    └── hooks/
        └── report_skill_usage.py   # Codex hook 脚本
```

---

## 七、已知限制

### Codex CLI

- `apply_patch`（文件编辑）和部分 MCP 工具调用的 hook 触发存在已知缺口（upstream issue #16732）
- `async: true` 的 handler 目前会被跳过
- 多 hook 并发执行，**一个 hook 无法阻止另一个同事件 hook 启动**

### 共同限制

- `PostToolUse` 无法撤销已完成的工具副作用
- Hook 脚本执行失败（非零退出）会被记录为错误，但**不会中断主流程**（`PreToolUse` 的 exit 2 例外）

---

## 八、参考资料

- [Codex Hooks 官方文档](https://developers.openai.com/codex/hooks)
- [Claude Code Hooks 参考](https://code.claude.com/docs/en/hooks)
- [Codex GitHub issue #16732 — MCP hook 覆盖缺口](https://github.com/openai/codex/issues/16732)
