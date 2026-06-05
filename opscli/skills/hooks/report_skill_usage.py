"""PostToolUse Hook：Skill 调用后实时上报使用次数。

支持三种 Skill 触发方式：

1. Claude Code
   - tool_name 为 "Skill"（内置 Skill 工具）
   - skill 名称从 tool_input.command 获取

2. Codex CLI 通过 MCP 工具调用（配置了 opscli MCP server 时）
   - tool_name 格式为 "mcp__opscli__<tool_name>"
   - 通过 MCP tool_name → skill 名称映射表反查

3. Codex CLI 通过 Bash 执行 opscli CLI 命令（未配置 MCP server 时，主要方式）
   - tool_name 为 "Bash"
   - 从 tool_input.command 中提取 opscli 子命令，映射到 Skill

从 stdin 读取 Hook 事件 JSON，提取 skill 名称，通过 subprocess 调用
opscli skills report-usage 上报到服务端。

仅使用 Python 标准库，不依赖 opscli 包，确保在任何环境下都能执行。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── MCP tool_name → Skill 名称映射表 ──────────────────────────────────
# 用于 Codex 等通过 MCP 工具间接使用 Skill 的场景。
# 新增 Skill/MCP 工具时需同步更新此表。
_MCP_TOOL_TO_SKILL: dict[str, str] = {
    # ops-dataset-query Skill 涵盖的查询工具
    "query_spec_must_read": "ops-dataset-query",
    "query_metadata": "ops-dataset-query",
    "query_catalog": "ops-dataset-query",
    "query_intent_match": "ops-dataset-query",
    "query_simple": "ops-dataset-query",
    "query_build": "ops-dataset-query",
    "query_run": "ops-dataset-query",
    "query_build_and_run": "ops-dataset-query",
    "query_chart": "ops-dataset-query",
    "query_chart_doc": "ops-dataset-query",
    "query_preferences": "ops-dataset-query",
    # ops-auth Skill 涵盖的认证工具
    "auth_mcp_login": "ops-auth",
    "auth_login_start": "ops-auth",
    "auth_login_poll": "ops-auth",
    "auth_get_token": "ops-auth",
    "auth_check_token": "ops-auth",
    "auth_is_authenticated": "ops-auth",
    "auth_token_refresh": "ops-auth",
    "auth_system_list": "ops-auth",
    "auth_system_add": "ops-auth",
    "auth_system_remove": "ops-auth",
    "auth_system_sync": "ops-auth",
    "auth_build_request_auth": "ops-auth",
    "auth_logout": "ops-auth",
    "auth_doctor": "ops-auth",
    # ops-feedback Skill 涵盖的反馈工具
    "feedback_submit": "ops-feedback",
    "feedback_detail": "ops-feedback",
    # ops-skills Skill 涵盖的技能管理工具
    "skills_list": "ops-skills",
    "skills_status": "ops-skills",
    "skills_install": "ops-skills",
    "skills_upgrade": "ops-skills",
    "skills_marketplace_list": "ops-skills",
    "skills_marketplace_info": "ops-skills",
    "skills_record_usage": "ops-skills",
    # 卖家精灵
    "seller_sprite_scenarios": "seller-sprite",
    "seller_sprite_run": "seller-sprite",
    "seller_sprite_job_status": "seller-sprite",
    "seller_sprite_export": "seller-sprite",
}

# MCP tool_name 前缀：mcp__<server>__<tool>
# server 名称通常为 "opscli"（FastMCP 实例注册时的 name）
_MCP_TOOL_PREFIX = "mcp__"

# ── Bash 命令中 opscli 子命令 → Skill 名称映射 ──────────────────────────
# Codex 等没有 MCP 配置时，通过 Bash 执行 opscli CLI 命令使用 Skill。
# 从命令行中提取 opscli 子命令，映射到对应的 Skill。
_BASH_OPSCLI_TO_SKILL: dict[str, str] = {
    "auth": "ops-auth",
    "query": "ops-dataset-query",
    "skills": "ops-skills",
    "mcp": "ops-skills",
}


def _resolve_skill_name(data: dict) -> str | None:
    """从 Hook 事件数据中提取 Skill 名称。

    优先级：
    1. Claude Code：tool_name == "Skill" → tool_input.command
    2. Codex 等 MCP 工具：tool_name 以 "mcp__" 开头 → 映射表反查
    3. Bash 命令：tool_name == "Bash" → 从 command 中提取 opscli 子命令

    Args:
        data: stdin 读取的 Hook 事件 JSON dict

    Returns:
        Skill 名称字符串，或 None（无法识别时）
    """
    tool_name = data.get("tool_name", "")

    # 路径 1：Claude Code 的 Skill 内置工具
    if tool_name == "Skill":
        tool_input = data.get("tool_input") or {}
        return tool_input.get("command") or None

    # 路径 2：Codex 等通过 MCP 工具间接调用 Skill
    if tool_name.startswith(_MCP_TOOL_PREFIX):
        # 提取 MCP tool 名：mcp__opscli__query_simple → query_simple
        mcp_tool = tool_name.split("__")[-1] if "__" in tool_name else tool_name
        return _MCP_TOOL_TO_SKILL.get(mcp_tool)

    # 路径 3：Bash 命令中执行 opscli 子命令（Codex 无 MCP 时的主要方式）
    if tool_name == "Bash":
        tool_input = data.get("tool_input") or {}
        return _resolve_bash_opscli_command(tool_input.get("command", ""))

    return None


def _resolve_bash_opscli_command(command: str) -> str | None:
    """从 Bash 命令字符串中提取 opscli 子命令并映射到 Skill。

    支持的命令格式：
    - opscli auth token status
    - opscli query metadata --dataset xxx
    - opscli skills list
    - "D:\\path\\to\\opscli.exe" auth login
    - python -m opscli auth ...

    不匹配的命令返回 None（如 git、npm 等非 opscli 命令）。

    Args:
        command: Bash 工具的 command 字段值

    Returns:
        Skill 名称字符串，或 None
    """
    cmd = command.strip()
    # 移除可能的引号包裹（Windows 路径常被引号包裹）
    if (cmd.startswith('"') and cmd.endswith('"')) or (cmd.startswith("'") and cmd.endswith("'")):
        cmd = cmd[1:-1].strip()

    # 提取命令中 "opscli" 后面的第一个子命令
    # 支持格式：opscli <sub> ... 或 path/to/opscli.exe <sub> ... 或 python -m opscli <sub> ...
    parts = cmd.split()
    for i, part in enumerate(parts):
        base = part.replace("\\", "/").rsplit("/", 1)[-1]  # 取文件名部分
        base = base.removesuffix(".exe")
        if "opscli" in base.lower():
            # 下一个 token 就是子命令
            if i + 1 < len(parts):
                subcmd = parts[i + 1].lower()
                return _BASH_OPSCLI_TO_SKILL.get(subcmd)
            break

    return None


# ── 去重窗口（秒） ──────────────────────────────────────────────────
# Claude Code 触发 Skill 时会产生两次 PostToolUse 事件：
#   1. Skill 工具调用（读取 SKILL.md 指令），tool_name="Skill"
#   2. Bash 命令执行（实际 opscli CLI 调用），tool_name="Bash"
# 两次间隔通常 10-20 秒。30 秒窗口覆盖一次完整的 skill 交互周期。
_DEDUP_SECONDS = 30


def _is_duplicate(skill_name: str) -> bool:
    """检查同一 skill 是否在去重窗口内已被触发过。

    使用标记文件（~/.opscli/hooks/.dedup_<skill_name>）的修改时间判断。
    跨进程安全：多个 hook 进程并发时文件时间戳天然序列化。
    标记文件长期残留无副作用（下次触发时覆盖时间戳即可）。

    Args:
        skill_name: Skill 名称

    Returns:
        True 表示重复触发，应跳过；False 表示首次或窗口外，应上报
    """
    import time

    marker_path = Path.home() / ".opscli" / "hooks" / f".dedup_{skill_name}"
    try:
        if marker_path.exists():
            elapsed = time.time() - marker_path.stat().st_mtime
            if elapsed < _DEDUP_SECONDS:
                return True
        # 写入/更新标记文件（首次触发或窗口外）
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.touch()
    except Exception:
        # 去重失败不影响主流程，放行上报
        pass
    return False


def _report_usage(skill_name: str) -> None:
    """调用 opscli skills report-usage 上报使用记录。

    Args:
        skill_name: Skill 名称
    """
    import subprocess

    # opscli 可执行文件与 python 在同一 venv Scripts 目录下
    opscli_cmd = Path(sys.executable).parent / "opscli.exe"
    if not opscli_cmd.exists():
        # Windows 开发环境可能用 opscli（无 .exe 后缀）
        opscli_cmd = Path(sys.executable).parent / "opscli"

    subprocess.run(
        [str(opscli_cmd), "skills", "report-usage", skill_name],
        capture_output=True,
        timeout=10,
    )


def main() -> None:
    """Hook 入口函数。matcher 设为 .* ，脚本内部过滤只处理 Skill 相关调用。

    去重：同一 skill 在 5 秒内重复触发时只上报一次。
    Claude Code 有时会对同一 Skill 产生两次 PostToolUse 事件，
    通过标记文件实现进程间去重。
    """
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    skill_name = _resolve_skill_name(data)
    if not skill_name:
        sys.exit(0)

    # 5 秒内同一 skill 去重：用标记文件的修改时间判断
    if _is_duplicate(skill_name):
        sys.exit(0)

    try:
        _report_usage(skill_name)
    except Exception:
        # 上报失败不影响主流程
        pass


if __name__ == "__main__":
    main()
