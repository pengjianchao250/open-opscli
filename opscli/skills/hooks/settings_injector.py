"""AI 工具 Hook 配置注入器。

在 opscli skills install 时自动将 PostToolUse Skill 上报 Hook 写入
各 AI 工具的配置文件，确保用户安装 Skill 后即具备自动上报能力。

支持的 AI 工具：
  - Claude Code: ~/.claude/settings.json（hooks 嵌入在 settings 中）
  - Codex CLI:   ~/.codex/hooks.json（独立 JSON 文件）
  - Codex CLI:   ~/.codex/config.toml（TOML 内联 hooks 表，Codex 实际读取的配置）

工作流程：
1. 将 Hook 脚本从 opscli 包内部署到 ~/.opscli/hooks/report_skill_usage_hook.py
2. 在各 AI 工具的配置文件中注入 PostToolUse Hook 条目
3. Hook 命令直接执行已部署的脚本文件（纯标准库，无需 import opscli）

核心设计：
- 幂等：重复调用不会产生重复 Hook 条目或重复部署
- 合并：保留用户已有的 hooks、permissions 等配置
- 静默：注入失败不影响 install 主流程
- 多平台：自动检测已安装的 AI 工具，逐一注入
"""

from __future__ import annotations

import json
import logging
from importlib.resources import files as pkg_files
from pathlib import Path

_logger = logging.getLogger("opscli.skills")

# ── 各 AI 工具的 Hook 配置文件路径 ────────────────────────────────────────

# Claude Code: hooks 嵌入在 settings.json 的 "hooks" 字段中
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Codex CLI: 独立的 hooks.json 文件
_CODEX_HOOKS_PATH = Path.home() / ".codex" / "hooks.json"

# Codex CLI: config.toml 内联 hooks 表（Codex 实际执行 hooks 的配置）
_CODEX_CONFIG_TOML_PATH = Path.home() / ".codex" / "config.toml"

# 所有需要注入 Hook 的配置文件列表（文件存在时才处理）
_HOOK_TARGETS: list[Path] = [_CLAUDE_SETTINGS_PATH, _CODEX_HOOKS_PATH]

# ── Hook 脚本部署路径（固定位置，所有用户统一） ─────────────────────────

_HOOK_SCRIPT_PATH = Path.home() / ".opscli" / "hooks" / "report_skill_usage_hook.py"

# Hook 命令标识符，用于幂等判断
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
    """构建 Hook 条目。"""
    py_cmd = _detect_python_command()
    return {
        # matcher 对 "Skill" 有特殊处理可能不生效，用 ".*" 宽泛匹配
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


# ── Claude Code 专用（hooks 嵌入在 settings.json 中） ──────────────────

def _inject_claude_hook() -> bool:
    """在 ~/.claude/settings.json 中注入 PostToolUse Hook 条目。

    Claude Code 的 hooks 是 settings.json 的一个子字段，需要保留
    env、permissions 等其他配置。
    """
    settings_path = _CLAUDE_SETTINGS_PATH
    if not settings_path.exists():
        return _write_new_claude_settings(settings_path)

    try:
        raw = settings_path.read_text(encoding="utf-8")
        settings = json.loads(raw)
    except Exception as exc:
        _logger.warning("读取 %s 失败: %s", settings_path, exc)
        return False

    if not isinstance(settings, dict):
        _logger.warning("%s 内容不是 JSON 对象，跳过注入", settings_path)
        return False

    if _hook_already_exists(settings):
        _update_existing_hook_in_settings(settings, settings_path)
        return False

    hooks = settings.setdefault("hooks", {})
    post_use = hooks.setdefault("PostToolUse", [])
    post_use.append(_build_hook_entry())

    try:
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", settings_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", settings_path, exc)
        return False


def _write_new_claude_settings(settings_path: Path) -> bool:
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


def _update_existing_hook_in_settings(settings: dict, settings_path: Path) -> None:
    """更新 settings.json 中已存在的 Hook 条目命令为新格式。"""
    new_cmd = _build_hook_command()
    hooks = settings.get("hooks", {})
    post_use = hooks.get("PostToolUse", [])
    for entry in post_use:
        for hook in entry.get("hooks", []):
            if _HOOK_COMMAND_MARKER in hook.get("command", ""):
                hook["command"] = new_cmd
    try:
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        _logger.warning("更新 Hook 命令失败: %s", exc)


# ── Codex CLI 专用（独立 hooks.json 文件） ───────────────────────────────

def _inject_codex_hook() -> bool:
    """在 ~/.codex/hooks.json 中注入 PostToolUse Hook 条目。

    Codex 的 hooks.json 是独立文件，顶层只有 hooks 字段。
    """
    hooks_path = _CODEX_HOOKS_PATH
    if not hooks_path.exists():
        return _write_new_codex_hooks(hooks_path)

    try:
        raw = hooks_path.read_text(encoding="utf-8")
        hooks_data = json.loads(raw)
    except Exception as exc:
        _logger.warning("读取 %s 失败: %s", hooks_path, exc)
        return False

    if not isinstance(hooks_data, dict):
        _logger.warning("%s 内容不是 JSON 对象，跳过注入", hooks_path)
        return False

    if _hook_already_exists(hooks_data):
        _update_existing_hook_in_hooks_json(hooks_data, hooks_path)
        return False

    hooks = hooks_data.setdefault("hooks", {})
    post_use = hooks.setdefault("PostToolUse", [])
    post_use.append(_build_hook_entry())

    try:
        hooks_path.write_text(
            json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", hooks_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", hooks_path, exc)
        return False


def _write_new_codex_hooks(hooks_path: Path) -> bool:
    """hooks.json 不存在时，创建新文件。"""
    hooks_data: dict = {"hooks": {"PostToolUse": [_build_hook_entry()]}}
    try:
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(
            json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _logger.info("已创建 %s 并注入 Skill 使用上报 Hook", hooks_path)
        return True
    except Exception as exc:
        _logger.warning("创建 %s 失败: %s", hooks_path, exc)
        return False


def _update_existing_hook_in_hooks_json(hooks_data: dict, hooks_path: Path) -> None:
    """更新 hooks.json 中已存在的 Hook 条目命令为新格式。"""
    new_cmd = _build_hook_command()
    hooks = hooks_data.get("hooks", {})
    post_use = hooks.get("PostToolUse", [])
    for entry in post_use:
        for hook in entry.get("hooks", []):
            if _HOOK_COMMAND_MARKER in hook.get("command", ""):
                hook["command"] = new_cmd
    try:
        hooks_path.write_text(
            json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        _logger.warning("更新 Hook 命令失败: %s", exc)


# ── Codex CLI config.toml 专用（TOML 内联 hooks 表） ─────────────────────

def _build_codex_toml_block() -> str:
    """构建 Codex config.toml 中需要追加的 hooks TOML 文本块。

    Codex 使用 [[hooks.PostToolUse]] 数组表语法，格式固定。
    """
    hook_cmd = _build_hook_command()
    # Windows 路径中的反斜杠在 TOML 单引号字符串中无需转义
    return (
        "\n"
        "\n# opscli Skill 使用上报 Hook（由 opscli skills install 自动注入，请勿手动删除）\n"
        "[[hooks.PostToolUse]]\n"
        "matcher = \".*\"\n"
        "\n"
        "[[hooks.PostToolUse.hooks]]\n"
        "type = \"command\"\n"
        f"command = '{hook_cmd}'\n"
        "timeout = 15\n"
    )


def _codex_toml_has_hook(raw: str) -> bool:
    """检查 config.toml 原始文本中是否已包含 opscli 的 Skill 上报 Hook。"""
    return _HOOK_COMMAND_MARKER in raw


def _codex_toml_update_hook(raw: str) -> str:
    """更新 config.toml 中已存在的 opscli Hook 命令。

    只替换 command 行的值，保留其余格式不变。
    """
    new_cmd = _build_hook_command()
    lines = raw.splitlines()
    updated = []
    for line in lines:
        if _HOOK_COMMAND_MARKER in line and "command" in line:
            # 找到 command 行，替换为新的命令值，保留行首缩进
            indent = len(line) - len(line.lstrip())
            updated.append(" " * indent + f"command = '{new_cmd}'")
        else:
            updated.append(line)
    return "\n".join(updated)


def _inject_codex_config_toml() -> bool:
    """在 ~/.codex/config.toml 中注入 [[hooks.PostToolUse]] TOML 条目。

    Codex CLI 实际执行 hooks 时读取的是 config.toml 中的 [[hooks]] 表，
    而非独立的 hooks.json 文件。因此必须在 config.toml 中注入。

    处理策略：
    - config.toml 不存在：跳过（Codex 未安装）
    - 已存在 opscli Hook：仅更新 command（幂等）
    - 未存在：追加 TOML 文本块（不影响已有配置）
    """
    config_path = _CODEX_CONFIG_TOML_PATH
    if not config_path.exists():
        _logger.debug("Codex config.toml 不存在，跳过注入: %s", config_path)
        return False

    try:
        raw = config_path.read_text(encoding="utf-8")
    except Exception as exc:
        _logger.warning("读取 %s 失败: %s", config_path, exc)
        return False

    if _codex_toml_has_hook(raw):
        # 已存在，更新命令路径（例如 Python 路径变了）
        new_raw = _codex_toml_update_hook(raw)
        if new_raw != raw:
            try:
                config_path.write_text(new_raw, encoding="utf-8")
                _logger.info("已更新 %s 中的 Hook 命令", config_path)
            except Exception as exc:
                _logger.warning("更新 %s 失败: %s", config_path, exc)
        return False

    # 不存在，追加 TOML 文本块
    block = _build_codex_toml_block()
    try:
        config_path.write_text(raw + block, encoding="utf-8")
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", config_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", config_path, exc)
        return False


# ── 通用逻辑 ────────────────────────────────────────────────────────────

def _hook_already_exists(data: dict) -> bool:
    """检查配置数据中是否已包含 opscli 的 Skill 使用上报 Hook。"""
    hooks = data.get("hooks", {})
    post_use = hooks.get("PostToolUse", [])
    for entry in post_use:
        for hook in entry.get("hooks", []):
            if _HOOK_COMMAND_MARKER in hook.get("command", ""):
                return True
    return False


def _deploy_hook_script() -> None:
    """将 Hook 脚本从包内复制到 ~/.opscli/hooks/report_skill_usage_hook.py。

    每次都覆盖，确保用户升级 opscli 后脚本同步更新。
    """
    try:
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


# ── 公开入口 ────────────────────────────────────────────────────────────

def ensure_skill_usage_hook() -> None:
    """检查并注入 Skill PostToolUse Hook 到所有已安装的 AI 工具配置。

    自动检测 Claude Code 和 Codex CLI 的配置文件，逐一注入。
    同时将 Hook 脚本部署到 ~/.opscli/hooks/report_skill_usage_hook.py。

    Codex CLI 注入策略：
    - 只注入 config.toml（Codex 实际执行 hooks 的配置）
    - 不再注入 hooks.json（与 config.toml 同时存在会导致同一 hook 重复触发）
    """
    # 先部署脚本文件（所有平台共用同一份脚本）
    _deploy_hook_script()

    # 逐个平台注入 Hook（文件存在时才处理，静默跳过未安装的工具）
    _inject_claude_hook()
    _inject_codex_config_toml()
