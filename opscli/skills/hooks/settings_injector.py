"""Claude Code settings.json 注入器。

在 opscli skills install 时自动将 PostToolUse Skill 上报 Hook 写入
~/.claude/settings.json，确保所有用户安装 Skill 后即具备自动上报能力。

工作流程：
1. 将 Hook 脚本从 opscli 包内部署到 ~/.opscli/report_skill_usage_hook.py
2. 在 ~/.claude/settings.json 中注入 PostToolUse Hook 条目
3. Hook 命令直接执行已部署的脚本文件（纯标准库，无需 import opscli）

核心设计：
- 幂等：重复调用不会产生重复 Hook 条目或重复部署
- 合并：保留用户已有的 hooks、permissions 等配置
- 静默：注入失败不影响 install 主流程
- 跨平台：自动检测 python3 / python 命令可用性
"""

from __future__ import annotations

import json
import logging
import shutil
from importlib.resources import files as pkg_files
from pathlib import Path

_logger = logging.getLogger("opscli.skills")

# Claude Code 全局配置文件路径
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Hook 脚本部署路径（固定位置，所有用户统一）
_HOOK_SCRIPT_PATH = Path.home() / ".opscli" / "hooks" / "report_skill_usage_hook.py"

# Hook 命令标识符，用于幂等判断（匹配旧 import 方式和新文件方式）
_HOOK_COMMAND_MARKER = "report_skill_usage"


def _detect_python_command() -> str:
    """获取当前 Python 解释器的完整路径。

    必须使用完整路径而非裸命令名，Windows 上裸 python 会解析到
    系统 Python（如 Python311），而非 opscli 所在的 venv Python，
    导致 Hook 脚本中 sys.executable.parent 找不到 opscli.exe。
    """
    import sys
    return sys.executable


def _build_hook_entry() -> dict:
    """构建 Hook 条目，Python 命令在注入时动态检测。"""
    py_cmd = _detect_python_command()
    return {
        # Claude Code matcher 对 "Skill" 有特殊处理不生效，用 ".*" 宽泛匹配
        # 脚本内部通过 tool_name != "Skill" 过滤非 Skill 工具调用
        "matcher": ".*",
        "hooks": [
            {
                "type": "command",
                "command": f'{py_cmd} "{_HOOK_SCRIPT_PATH}"',
                "timeout": 15,
            }
        ],
    }


def _build_hook_command() -> str:
    """构建 Hook 命令字符串。"""
    py_cmd = _detect_python_command()
    return f'{py_cmd} "{_HOOK_SCRIPT_PATH}"'


def ensure_skill_usage_hook() -> bool:
    """检查并注入 Skill PostToolUse Hook 到 ~/.claude/settings.json。

    同时将 Hook 脚本部署到 ~/.opscli/report_skill_usage_hook.py。

    Returns:
        True 表示新注入了 Hook，False 表示已存在或注入失败。
    """
    # 先部署脚本文件
    _deploy_hook_script()

    # 再注入/更新 settings.json
    return _inject_hook_entry()


def _deploy_hook_script() -> None:
    """将 Hook 脚本从包内复制到 ~/.opscli/report_skill_usage_hook.py。

    每次都覆盖，确保用户升级 opscli 后脚本同步更新。
    """
    try:
        # 从 opscli 包内读取源脚本
        source = pkg_files("opscli").joinpath(
            "skills", "hooks", "report_skill_usage.py"
        )
        content = source.read_text(encoding="utf-8")
    except Exception as exc:
        _logger.warning("读取包内 Hook 脚本失败: %s", exc)
        return

    try:
        _HOOK_SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HOOK_SCRIPT_PATH.write_text(content, encoding="utf-8")
        _logger.info("已部署 Hook 脚本到 %s", _HOOK_SCRIPT_PATH)
    except Exception as exc:
        _logger.warning("部署 Hook 脚本失败: %s", exc)


def _inject_hook_entry() -> bool:
    """在 ~/.claude/settings.json 中注入 PostToolUse Hook 条目。"""
    settings_path = _CLAUDE_SETTINGS_PATH
    if not settings_path.exists():
        return _write_new_settings(settings_path)

    try:
        raw = settings_path.read_text(encoding="utf-8")
        settings = json.loads(raw)
    except Exception as exc:
        _logger.warning("读取 %s 失败: %s", settings_path, exc)
        return False

    if not isinstance(settings, dict):
        _logger.warning("%s 内容不是 JSON 对象，跳过注入", settings_path)
        return False

    # 检查是否已存在同名 Hook（幂等判断）
    if _hook_already_exists(settings):
        # 已存在但命令可能指向旧格式，更新为最新命令
        _update_existing_hook(settings)
        return False

    # 追加 Hook 条目
    hooks = settings.setdefault("hooks", {})
    post_use = hooks.setdefault("PostToolUse", [])
    post_use.append(_build_hook_entry())

    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", settings_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", settings_path, exc)
        return False


def _update_existing_hook(settings: dict) -> None:
    """更新已存在的 Hook 条目命令为新格式。"""
    hooks = settings.get("hooks", {})
    post_use = hooks.get("PostToolUse", [])
    new_cmd = _build_hook_command()
    for entry in post_use:
        for hook in entry.get("hooks", []):
            if _HOOK_COMMAND_MARKER in hook.get("command", ""):
                hook["command"] = new_cmd
    try:
        _CLAUDE_SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        _logger.warning("更新 Hook 命令失败: %s", exc)


def _hook_already_exists(settings: dict) -> bool:
    """检查 settings 中是否已包含 opscli 的 Skill 使用上报 Hook。"""
    hooks = settings.get("hooks", {})
    post_use = hooks.get("PostToolUse", [])
    for entry in post_use:
        for hook in entry.get("hooks", []):
            if _HOOK_COMMAND_MARKER in hook.get("command", ""):
                return True
    return False


def _write_new_settings(settings_path: Path) -> bool:
    """settings.json 不存在时，创建包含 Hook 的新文件。"""
    settings: dict = {"hooks": {"PostToolUse": [_build_hook_entry()]}}
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _logger.info("已创建 %s 并注入 Skill 使用上报 Hook", settings_path)
        return True
    except Exception as exc:
        _logger.warning("创建 %s 失败: %s", settings_path, exc)
        return False
