"""AI 工具 Hook 配置注入器。

在 opscli skills install 时自动将 PostToolUse Skill 上报 Hook 写入
各 AI 工具的配置文件，确保用户安装 Skill 后即具备自动上报能力。

支持的 AI 工具：
  - Claude Code: ~/.claude/settings.json（hooks 嵌入在 settings 中）
  - Codex CLI:   ~/.codex/hooks.json 或 ~/.codex/config.toml
                  同一用户层复用已有有效表示，避免两者并存触发启动告警

工作流程：
1. 将 Hook 脚本从 opscli 包内部署到 ~/.opscli/hooks/report_skill_usage_hook.py
2. 写入稳定的 ~/.opscli/hooks/report_skill_usage Runner
3. 在各 AI 工具的配置文件中注入 PostToolUse Hook 条目
4. Hook 命令执行稳定 Runner，Runner 再调用当前 Python 解释器和脚本

核心设计：
- 幂等：重复调用不会产生重复 Hook 条目或重复部署
- 合并：保留用户已有的 hooks、permissions 等配置
- 静默：注入失败不影响 install 主流程
- 多平台：自动检测已安装的 AI 工具，逐一注入
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime
from importlib.resources import files as pkg_files
from pathlib import Path

_logger = logging.getLogger("opscli.skills")

# ── 各 AI 工具的 Hook 配置文件路径 ────────────────────────────────────────

# Claude Code: hooks 嵌入在 settings.json 的 "hooks" 字段中
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Codex CLI: 用户级独立 hooks.json 文件；同层已有该表示时优先复用
_CODEX_HOOKS_PATH = Path.home() / ".codex" / "hooks.json"

# Codex CLI: config.toml 内联 hooks 表；仅在没有有效 hooks.json Hook 时使用
_CODEX_CONFIG_TOML_PATH = Path.home() / ".codex" / "config.toml"

# ── Hook 脚本部署路径（固定位置，所有用户统一） ─────────────────────────

_HOOK_SCRIPT_PATH = Path.home() / ".opscli" / "hooks" / "report_skill_usage_hook.py"

# Keep the configured command stable across Python/virtualenv upgrades. The runner
# content is refreshed separately and points at the current interpreter.
_HOOK_RUNNER_PATH = Path.home() / ".opscli" / "hooks" / (
    "report_skill_usage_hook.cmd" if os.name == "nt" else "report_skill_usage_hook"
)

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
    return {
        # matcher 对 "Skill" 有特殊处理可能不生效，用 ".*" 宽泛匹配
        # 脚本内部通过 tool_name != "Skill" 过滤非 Skill 工具调用
        "matcher": ".*",
        "hooks": [
            {
                "type": "command",
                "command": _build_hook_command(),
                "timeout": 15,
            }
        ],
    }


def _shell_quote_arg(value: str) -> str:
    """按当前平台生成 hook command 中的单个参数。

    Codex / Claude hooks 的 command 字段最终交给宿主 shell 执行：
    - POSIX 使用 shlex.quote，处理空格、单引号、$ 等特殊字符。
    - Windows 使用 subprocess.list2cmdline，生成 cmd/CreateProcess 兼容的双引号格式。
    """
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def _build_hook_command() -> str:
    """构建稳定的 Hook 命令字符串。"""
    return _shell_quote_arg(str(_HOOK_RUNNER_PATH))


def _atomic_write_text(path: Path, content: str, *, mode: int | None = None) -> None:
    """以同目录临时文件 + 原子替换写入配置或脚本。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            tmp_path.chmod(mode)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _build_runner_content() -> str:
    """构建跨平台稳定 Runner，实际解释器路径只存在于 Runner 内容中。"""
    py_cmd = _shell_quote_arg(_detect_python_command())
    script_path = _shell_quote_arg(str(_HOOK_SCRIPT_PATH))
    if os.name == "nt":
        return f"@echo off\r\n{py_cmd} {script_path} %*\r\n"
    return f"#!/bin/sh\nexec {py_cmd} {script_path} \"$@\"\n"


def _toml_string(value: str) -> str:
    """生成 TOML basic string。

    TOML basic string 与 JSON 字符串转义规则对本场景兼容，能正确处理
    Windows 反斜杠、双引号和 POSIX shlex 产生的单引号。
    """
    return json.dumps(value, ensure_ascii=False)


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
        _atomic_write_text(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", settings_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", settings_path, exc)
        return False


def _write_new_claude_settings(settings_path: Path) -> bool:
    """settings.json 不存在时，创建包含 Hook 的新文件。"""
    settings: dict = {"hooks": {"PostToolUse": [_build_hook_entry()]}}
    try:
        _atomic_write_text(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
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
        _atomic_write_text(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    except Exception as exc:
        _logger.warning("更新 Hook 命令失败: %s", exc)


# ── Codex CLI 专用（独立 hooks.json 文件） ───────────────────────────────

def _write_new_codex_hooks(hooks_path: Path) -> bool:
    """hooks.json 不存在时，创建包含 opscli Hook 的新文件。"""
    hooks_data = {"hooks": {"PostToolUse": [_build_hook_entry()]}}
    try:
        _atomic_write_text(hooks_path, json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n")
        _logger.info("已创建 %s 并注入 Skill 使用上报 Hook", hooks_path)
        return True
    except Exception as exc:
        _logger.warning("创建 %s 失败: %s", hooks_path, exc)
        return False


def _update_existing_hook_in_hooks_json(hooks_data: dict, hooks_path: Path) -> None:
    """更新 hooks.json 中已有 opscli Hook 的命令为稳定 Runner。"""
    new_cmd = _build_hook_command()
    hooks = hooks_data.get("hooks", {})
    post_use = hooks.get("PostToolUse", [])
    for entry in post_use:
        for hook in entry.get("hooks", []):
            if _is_opscli_hook_command(hook.get("command")):
                hook["command"] = new_cmd
    try:
        _atomic_write_text(hooks_path, json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n")
    except Exception as exc:
        _logger.warning("更新 %s 中的 Hook 命令失败: %s", hooks_path, exc)


def _inject_codex_hooks_json() -> bool:
    """在已有 hooks.json 中复用同层表示并注入 PostToolUse Hook。"""
    hooks_path = _CODEX_HOOKS_PATH
    if not hooks_path.exists():
        return _write_new_codex_hooks(hooks_path)

    hooks_data = _read_json_file(hooks_path)
    if hooks_data is None:
        _logger.warning("读取 %s 失败，跳过 JSON Hook 注入", hooks_path)
        return False

    if _hook_already_exists(hooks_data):
        _update_existing_hook_in_hooks_json(hooks_data, hooks_path)
        return False

    hooks = hooks_data.setdefault("hooks", {})
    post_use = hooks.setdefault("PostToolUse", [])
    post_use.append(_build_hook_entry())
    try:
        _atomic_write_text(hooks_path, json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n")
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", hooks_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", hooks_path, exc)
        return False

# ── Codex CLI config.toml 专用（TOML 内联 hooks 表） ─────────────────────

def _build_codex_toml_block() -> str:
    """构建 Codex config.toml 中需要追加的 hooks TOML 文本块。

    Codex 使用 [[hooks.PostToolUse]] 数组表语法，格式固定。
    """
    hook_cmd = _build_hook_command()
    return (
        "\n"
        "\n# opscli Skill 使用上报 Hook（由 opscli skills install 自动注入，请勿手动删除）\n"
        "[[hooks.PostToolUse]]\n"
        "matcher = \".*\"\n"
        "\n"
        "[[hooks.PostToolUse.hooks]]\n"
        "type = \"command\"\n"
        f"command = {_toml_string(hook_cmd)}\n"
        "timeout = 15\n"
    )


def _codex_toml_has_hook(raw: str) -> bool:
    """检查 config.toml 原始文本中是否已包含 opscli 的 Skill 上报 Hook。"""
    return _count_opscli_hooks_in_toml(raw) > 0


def _codex_toml_update_hook(raw: str) -> str:
    """更新 config.toml 中已存在的 opscli Hook 命令。

    只替换 command 行的值，保留其余格式不变。
    """
    new_cmd = _build_hook_command()
    had_trailing_newline = raw.endswith("\n")
    lines = raw.splitlines()
    updated = []
    for line in lines:
        if re.match(r"^\s*command\s*=", line) and _HOOK_COMMAND_MARKER in line:
            # 找到 command 行，替换为新的命令值，保留行首缩进
            indent = len(line) - len(line.lstrip())
            updated.append(" " * indent + f"command = {_toml_string(new_cmd)}")
        else:
            updated.append(line)
    result = "\n".join(updated)
    return result + ("\n" if had_trailing_newline else "")


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
                _atomic_write_text(config_path, new_raw)
                _logger.info("已更新 %s 中的 Hook 命令", config_path)
            except Exception as exc:
                _logger.warning("更新 %s 失败: %s", config_path, exc)
        return False

    # 不存在，追加 TOML 文本块
    block = _build_codex_toml_block()
    try:
        _atomic_write_text(config_path, raw + block)
        _logger.info("已注入 Skill 使用上报 Hook 到 %s", config_path)
        return True
    except Exception as exc:
        _logger.warning("写入 %s 失败: %s", config_path, exc)
        return False


def _count_opscli_hooks_in_toml(raw: str) -> int:
    """统计 TOML 事件 Hook 中由 opscli 生成的命令处理器数量。"""
    return sum(
        bool(re.match(r"^\s*command\s*=", line)) and _HOOK_COMMAND_MARKER in line
        for line in raw.splitlines()
    )


def _count_event_hooks_in_toml(raw: str) -> int:
    """统计 TOML 中的事件数组表，排除 hooks.state 和嵌套处理器表。"""
    event_header = re.compile(r"^\s*\[\[hooks\.[^.\]]+\]\]\s*(?:#.*)?$")
    return sum(bool(event_header.match(line)) for line in raw.splitlines())


def _count_hook_handlers_in_toml(raw: str) -> int:
    """统计 TOML 事件组中的处理器数组表数量。"""
    handler_header = re.compile(r"^\s*\[\[hooks\.[^.\]]+\.hooks\]\]\s*(?:#.*)?$")
    return sum(bool(handler_header.match(line)) for line in raw.splitlines())


def _remove_opscli_hooks_from_toml(raw: str) -> tuple[str, int]:
    """移除 TOML 中 opscli 生成的完整事件组，保留其他配置。"""
    lines = raw.splitlines(keepends=True)
    event_header = re.compile(r"^\s*\[\[hooks\.[^.\]]+\]\]\s*(?:#.*)?$")
    event_starts = [
        index
        for index, line in enumerate(lines)
        if event_header.match(line.rstrip("\r\n"))
    ]
    if not event_starts:
        return raw, 0

    remove_ranges: list[tuple[int, int]] = []
    removed = 0
    for start in event_starts:
        end = start + 1
        while end < len(lines):
            stripped = lines[end].strip()
            # 嵌套处理器仍属于当前事件组；其他表头表示事件组结束。
            if stripped.startswith("[") and not stripped.startswith("[[hooks."):
                break
            if event_header.match(lines[end].rstrip("\r\n")):
                break
            end += 1
        block = lines[start:end]
        if any(
            re.match(r"^\s*command\s*=", line) and _HOOK_COMMAND_MARKER in line
            for line in block
        ):
            remove_ranges.append((start, end))
            removed += 1

    if not remove_ranges:
        return raw, 0

    removed_indexes = {
        index
        for start, end in remove_ranges
        for index in range(start, end)
    }
    updated = "".join(line for index, line in enumerate(lines) if index not in removed_indexes)
    return updated, removed


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
        _atomic_write_text(_HOOK_SCRIPT_PATH, content)
        mode = 0o755 if os.name != "nt" else None
        _atomic_write_text(_HOOK_RUNNER_PATH, _build_runner_content(), mode=mode)
        _logger.info("已部署 Hook 脚本到 %s", _HOOK_SCRIPT_PATH)
    except Exception as exc:
        _logger.warning("部署 Hook 脚本失败: %s", exc)


# ── 公开入口 ────────────────────────────────────────────────────────────

def ensure_skill_usage_hook() -> None:
    """检查并注入 Skill PostToolUse Hook 到所有已安装的 AI 工具配置。

    自动检测 Claude Code 和 Codex CLI 的配置文件，逐一注入。
    同时将 Hook 脚本部署到 ~/.opscli/hooks/report_skill_usage_hook.py。

    Codex CLI 注入策略：
    - 同层已有有效 hooks.json Hook 时复用 JSON 表示，并清理 TOML 中的 opscli 条目
    - 没有有效 hooks.json Hook 时才使用 config.toml 表示
    - 不自动搬运用户自定义 Hook，避免改变其授权来源
    """
    # 先部署脚本文件（所有平台共用同一份脚本）
    _deploy_hook_script()

    # 逐个平台注入 Hook（文件存在时才处理，静默跳过未安装的工具）
    _inject_claude_hook()
    _ensure_codex_single_representation()


def _codex_hook_paths() -> tuple[Path, Path]:
    """返回用户级 Codex hooks.json 与 config.toml 路径。"""
    return _CODEX_HOOKS_PATH, _CODEX_CONFIG_TOML_PATH


def _is_opscli_hook_command(command: object) -> bool:
    """只识别 opscli 自己生成的上报 Hook，不误删用户自定义命令。"""
    text = str(command or "")
    return "report_skill_usage_hook.py" in text or "report_skill_usage_hook" in text


def _count_opscli_hooks_in_json(data: object) -> int:
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return 0
    count = 0
    for groups in data["hooks"].values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            count += sum(
                isinstance(handler, dict) and _is_opscli_hook_command(handler.get("command"))
                for handler in group["hooks"]
            )
    return count


def _read_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _count_codex_json_hooks(data: object) -> int:
    """统计 hooks.json 中所有有效 Hook 处理器数量。"""
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return 0
    count = 0
    for groups in data["hooks"].values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                count += sum(isinstance(handler, dict) for handler in group["hooks"])
    return count


def _ensure_codex_single_representation() -> None:
    """按同层已有配置选择 JSON 或 TOML，并清理可安全识别的重复 opscli 条目。"""
    hooks_path, config_path = _codex_hook_paths()
    hooks_data = _read_json_file(hooks_path)
    if hooks_path.exists() and hooks_data is None:
        # 损坏的 JSON 不可安全改写，保留现场并继续维护可用的 TOML 配置。
        _inject_codex_config_toml()
        return

    json_hook_count = _count_codex_json_hooks(hooks_data)
    if json_hook_count > 0:
        _inject_codex_hooks_json()
        if not config_path.exists():
            return
        try:
            config_raw = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            _logger.warning("读取 %s 失败: %s", config_path, exc)
            return

        toml_opscli_count = _count_opscli_hooks_in_toml(config_raw)
        toml_handler_count = _count_hook_handlers_in_toml(config_raw)
        if toml_opscli_count == 0:
            return
        if toml_handler_count > toml_opscli_count:
            _logger.warning(
                "%s 与 %s 同时包含用户 Hook，无法安全自动合并；请运行 skills hooks status 处理",
                hooks_path,
                config_path,
            )
            return
        updated_config, removed = _remove_opscli_hooks_from_toml(config_raw)
        if removed and updated_config != config_raw:
            try:
                _atomic_write_text(config_path, updated_config)
                _logger.info("已移除 %s 中重复的 opscli Hook", config_path)
            except Exception as exc:
                _logger.warning("清理 %s 中重复 Hook 失败: %s", config_path, exc)
        return

    # 没有有效 JSON Hook 时，config.toml 是唯一可用表示。
    _inject_codex_config_toml()


def codex_hook_status() -> dict:
    """读取用户级 Codex Hook 状态，不修改任何文件。"""
    hooks_path, config_path = _codex_hook_paths()
    hooks_data = _read_json_file(hooks_path)
    config_raw = ""
    if config_path.exists():
        try:
            config_raw = config_path.read_text(encoding="utf-8")
        except OSError:
            config_raw = ""
    hooks_json_count = _count_opscli_hooks_in_json(hooks_data)
    hooks_json_total = _count_codex_json_hooks(hooks_data)
    toml_count = _count_opscli_hooks_in_toml(config_raw)
    toml_total = _count_event_hooks_in_toml(config_raw)
    toml_handlers = _count_hook_handlers_in_toml(config_raw)
    return {
        "canonical": "hooks.json" if hooks_json_total else ("config.toml" if toml_total else None),
        "hooks_json": {
            "path": str(hooks_path),
            "exists": hooks_path.exists(),
            "hook_handlers": hooks_json_total,
            "opscli_hooks": hooks_json_count,
            "valid_json": hooks_data is not None if hooks_path.exists() else True,
        },
        "config_toml": {
            "path": str(config_path),
            "exists": config_path.exists(),
            "hook_groups": toml_total,
            "hook_handlers": toml_handlers,
            "opscli_hooks": toml_count,
            "has_opscli_hook": toml_count > 0,
        },
        "duplicate_representation": hooks_json_total > 0 and toml_total > 0,
        "duplicate_opscli_hooks": hooks_json_count + toml_count,
        "runner_path": str(_HOOK_RUNNER_PATH),
        "script_path": str(_HOOK_SCRIPT_PATH),
    }


def _make_migration_backup(paths: list[Path]) -> Path:
    """为迁移涉及的文件创建可回滚备份，并记录原始存在状态。"""
    root = _CODEX_CONFIG_TOML_PATH.parent / "opscli-hook-backups"
    backup_dir = root / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, bool] = {}
    for path in paths:
        existed = path.exists()
        manifest[path.name] = existed
        if existed:
            shutil.copy2(path, backup_dir / path.name)
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return backup_dir


def migrate_codex_hooks(*, dry_run: bool = True) -> dict:
    """将用户级 Codex Hook 收敛到当前层已经使用的单一表示。"""
    hooks_path, config_path = _codex_hook_paths()
    hooks_data = _read_json_file(hooks_path)
    if hooks_path.exists() and hooks_data is None:
        raise ValueError(f"无法解析 Codex hooks.json：{hooks_path}")

    config_exists = config_path.exists()
    config_raw = config_path.read_text(encoding="utf-8") if config_exists else ""
    json_hook_count = _count_codex_json_hooks(hooks_data)
    toml_hook_count = _count_event_hooks_in_toml(config_raw)
    toml_handler_count = _count_hook_handlers_in_toml(config_raw)
    toml_opscli_count = _count_opscli_hooks_in_toml(config_raw)

    updated_hooks = hooks_data
    migrated_config = config_raw
    moved_to_hooks_json = 0
    removed_from_config_toml = 0
    canonical = "config.toml"
    if json_hook_count > 0:
        canonical = "hooks.json"
        if toml_hook_count and toml_handler_count > toml_opscli_count:
            raise ValueError(
                "hooks.json 与 config.toml 都包含非 opscli Hook，无法安全自动合并；"
                "请先选择要保留的用户级 Hook 表示"
            )

        # 复用已有 JSON 表示，只追加或刷新 opscli 自己的处理器。
        updated_hooks = json.loads(json.dumps(hooks_data, ensure_ascii=False))
        if not _hook_already_exists(updated_hooks):
            hooks = updated_hooks.setdefault("hooks", {})
            hooks.setdefault("PostToolUse", []).append(_build_hook_entry())
            moved_to_hooks_json = 1
        else:
            new_cmd = _build_hook_command()
            for entry in updated_hooks.get("hooks", {}).get("PostToolUse", []):
                for hook in entry.get("hooks", []):
                    if _is_opscli_hook_command(hook.get("command")):
                        hook["command"] = new_cmd
        migrated_config, removed_from_config_toml = _remove_opscli_hooks_from_toml(config_raw)
    elif config_exists and _codex_toml_has_hook(config_raw):
        migrated_config = _codex_toml_update_hook(config_raw)

    changed_hooks = updated_hooks != hooks_data
    changed_config = migrated_config != config_raw
    backup_dir: Path | None = None
    if not dry_run and (changed_hooks or changed_config):
        backup_dir = _make_migration_backup([hooks_path, config_path])
        if changed_hooks and updated_hooks is not None:
            _atomic_write_text(hooks_path, json.dumps(updated_hooks, ensure_ascii=False, indent=2) + "\n")
        if changed_config:
            _atomic_write_text(config_path, migrated_config)
        # A successful migration must leave the configured stable Runner usable.
        _deploy_hook_script()

    return {
        "dry_run": dry_run,
        "canonical": canonical,
        "removed_from_hooks_json": 0,
        "moved_to_hooks_json": moved_to_hooks_json,
        "removed_from_config_toml": removed_from_config_toml,
        "config_toml_changed": changed_config,
        "hooks_json_changed": changed_hooks,
        "backup_dir": str(backup_dir) if backup_dir else None,
        "status": codex_hook_status(),
    }


def rollback_codex_hooks(backup_dir: str | Path) -> dict:
    """从 migrate 生成的备份目录恢复用户级 Codex Hook 配置。"""
    source = Path(backup_dir).expanduser().resolve()
    manifest_path = source / "manifest.json"
    if not source.is_dir() or not manifest_path.exists():
        raise ValueError(f"无效的 Hook 迁移备份目录：{source}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hooks_path, config_path = _codex_hook_paths()
    restored: list[str] = []
    for path in (hooks_path, config_path):
        existed = bool(manifest.get(path.name))
        backup_file = source / path.name
        if existed:
            if not backup_file.exists():
                raise ValueError(f"备份文件缺失：{backup_file}")
            _atomic_write_text(path, backup_file.read_text(encoding="utf-8"))
            restored.append(str(path))
        elif path.exists():
            path.unlink()
            restored.append(str(path))
    return {"backup_dir": str(source), "restored": restored, "status": codex_hook_status()}
