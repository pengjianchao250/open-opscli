"""Codex/Claude Skill 使用上报 Hook 的配置、迁移与稳定 Runner 回归。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.skills.hooks import settings_injector as injector

_REAL_ENSURE = injector.ensure_skill_usage_hook


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    hooks_json = tmp_path / "codex" / "hooks.json"
    config_toml = tmp_path / "codex" / "config.toml"
    claude_json = tmp_path / "claude" / "settings.json"
    script = tmp_path / "opscli" / "hooks" / "report_skill_usage_hook.py"
    runner = tmp_path / "opscli" / "hooks" / "report_skill_usage_hook"
    monkeypatch.setattr(injector, "_CODEX_HOOKS_PATH", hooks_json)
    monkeypatch.setattr(injector, "_CODEX_CONFIG_TOML_PATH", config_toml)
    monkeypatch.setattr(injector, "_CLAUDE_SETTINGS_PATH", claude_json)
    monkeypatch.setattr(injector, "_HOOK_SCRIPT_PATH", script)
    monkeypatch.setattr(injector, "_HOOK_RUNNER_PATH", runner)
    return hooks_json, config_toml, claude_json, runner


def test_hook_command_is_stable_when_python_path_changes(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(injector, "_detect_python_command", lambda: "/old/python")
    first = injector._build_hook_command()
    monkeypatch.setattr(injector, "_detect_python_command", lambda: "/new/python")
    second = injector._build_hook_command()
    assert first == second == str(tmp_path / "opscli/hooks/report_skill_usage_hook")


def test_ensure_deploys_script_runner_and_single_toml_representation(monkeypatch, tmp_path: Path):
    hooks_json, config_toml, claude_json, runner = _patch_paths(monkeypatch, tmp_path)
    config_toml.parent.mkdir(parents=True)
    config_toml.write_text("[mcp_servers]\n", encoding="utf-8")

    _REAL_ENSURE()

    assert not hooks_json.exists()
    assert claude_json.exists()
    assert runner.exists()
    assert runner.read_text(encoding="utf-8").startswith("#!/bin/sh")
    config = config_toml.read_text(encoding="utf-8")
    assert config.count("[[hooks.PostToolUse]]") == 1
    assert str(runner) in config

    before = config_toml.read_text(encoding="utf-8")
    monkeypatch.setattr(injector, "_detect_python_command", lambda: "/another/python")
    _REAL_ENSURE()
    assert config_toml.read_text(encoding="utf-8") == before


def test_toml_comment_does_not_mask_missing_hook(monkeypatch, tmp_path: Path):
    _hooks_json, config_toml, _claude_json, _runner = _patch_paths(monkeypatch, tmp_path)
    config_toml.parent.mkdir(parents=True)
    config_toml.write_text("# report_skill_usage is only a note\n[mcp_servers]\n", encoding="utf-8")

    _REAL_ENSURE()

    assert config_toml.read_text(encoding="utf-8").count("[[hooks.PostToolUse]]") == 1


def test_ensure_reuses_existing_json_and_removes_toml_duplicate(monkeypatch, tmp_path: Path):
    hooks_json, config_toml, _claude_json, runner = _patch_paths(monkeypatch, tmp_path)
    hooks_json.parent.mkdir(parents=True)
    hooks_json.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {"hooks": [{"type": "command", "command": "echo keep-me"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    config_toml.write_text(
        "[hooks.state]\n" + injector._build_codex_toml_block() + "\n[mcp_servers]\n",
        encoding="utf-8",
    )

    before = injector.codex_hook_status()
    assert before["duplicate_representation"] is True

    _REAL_ENSURE()

    hooks_data = json.loads(hooks_json.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in hooks_data["hooks"]["PostToolUse"]
        for hook in group["hooks"]
    ]
    assert commands == ["echo keep-me", str(runner)]
    migrated_toml = config_toml.read_text(encoding="utf-8")
    assert "[[hooks.PostToolUse]]" not in migrated_toml
    assert "[mcp_servers]" in migrated_toml
    assert injector.codex_hook_status()["duplicate_representation"] is False


def test_migrate_legacy_hooks_preserves_custom_handlers_and_rolls_back(monkeypatch, tmp_path: Path):
    hooks_json, config_toml, _claude_json, runner = _patch_paths(monkeypatch, tmp_path)
    hooks_json.parent.mkdir(parents=True)
    hooks_json.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {"type": "command", "command": "echo keep-me"},
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    config_toml.write_text(
        "[mcp_servers]\n" + injector._build_codex_toml_block(),
        encoding="utf-8",
    )

    preview = injector.migrate_codex_hooks(dry_run=True)
    assert preview["canonical"] == "hooks.json"
    assert preview["moved_to_hooks_json"] == 1
    assert preview["removed_from_config_toml"] == 1
    assert str(runner) not in hooks_json.read_text(encoding="utf-8")

    applied = injector.migrate_codex_hooks(dry_run=False)
    backup_dir = Path(applied["backup_dir"])
    assert backup_dir.is_dir()
    migrated = json.loads(hooks_json.read_text(encoding="utf-8"))
    handlers = migrated["hooks"]["PostToolUse"][0]["hooks"]
    assert handlers == [{"type": "command", "command": "echo keep-me"}]
    assert str(runner) in hooks_json.read_text(encoding="utf-8")
    assert str(runner) not in config_toml.read_text(encoding="utf-8")

    restored = injector.rollback_codex_hooks(backup_dir)
    assert str(hooks_json) in restored["restored"]
    assert str(runner) not in hooks_json.read_text(encoding="utf-8")
    assert "[[hooks.PostToolUse]]" in config_toml.read_text(encoding="utf-8")


def test_migrate_without_existing_hooks_is_read_only(monkeypatch, tmp_path: Path):
    _hooks_json, config_toml, _claude_json, _runner = _patch_paths(monkeypatch, tmp_path)
    config_toml.parent.mkdir(parents=True)
    original = "[mcp_servers]\n"
    config_toml.write_text(original, encoding="utf-8")

    result = injector.migrate_codex_hooks(dry_run=False)

    assert result["config_toml_changed"] is False
    assert result["hooks_json_changed"] is False
    assert config_toml.read_text(encoding="utf-8") == original
