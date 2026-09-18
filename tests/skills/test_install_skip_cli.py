"""安装入口的跳过语义与显式覆盖回归。"""

import asyncio
import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from opscli.skills.commands import cli
from opscli.skills.domain.models import SkillBatchInstallResult, SkillInstallResult


@pytest.mark.parametrize("force", [False, True])
def test_remote_install_passes_explicit_force(monkeypatch, force):
    """远程安装不能擅自把普通安装变成覆盖。"""
    install = Mock(return_value={"success": True, "data": {"skipped": not force}})
    monkeypatch.setattr(cli, "install_remote_skill", install)
    result = CliRunner().invoke(cli.app, ["install", "tester@ops-test"] + (["--force"] if force else []))
    assert result.exit_code == 0
    assert install.call_args.kwargs["force"] is force


@pytest.mark.parametrize("force", [False, True])
def test_interactive_install_honors_skip_and_force(tmp_path, monkeypatch, force):
    """批量 --yes 仅免确认，不能隐式覆盖，且汇总展示跳过数量。"""
    manager = Mock()
    manager.install.return_value = SkillBatchInstallResult(
        name="ops-test",
        installs=[SkillInstallResult("ops-test", "custom", tmp_path / "ops-test", "v1.0.0", force, skipped=not force)],
    )
    monkeypatch.setattr(cli, "SkillsManager", lambda: manager)
    monkeypatch.setattr(cli, "_tui_select_skills", lambda manager, yes=False: ["ops-test"])

    result = CliRunner().invoke(
        cli.app, ["install", "--yes", "--skills-dir", str(tmp_path), "--verbose"] + (["--force"] if force else []),
    )

    assert result.exit_code == 0, result.output
    assert manager.install.call_args.kwargs["force"] is force
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["data"]["results"][0]["installed_paths"][0]["skipped"] is (not force)
    assert ("1 个跳过" if not force else "0 个跳过") in result.stdout


def test_skipped_install_does_not_inject_rules(tmp_path, monkeypatch):
    """跳过安装时也跳过 CLI 侧的用户配置注入。"""
    injector = Mock()
    monkeypatch.setattr(cli, "RuleInjector", lambda: injector)
    cli._inject_rules_for_installs([
        SkillInstallResult("ops-feedback", "codex", tmp_path / "ops-feedback", "v1.0.0", False, skipped=True),
    ])
    injector.inject.assert_not_called()


def test_mcp_install_returns_existing_version_and_skipped(tmp_path, monkeypatch, isolate_install_hook):
    """MCP 复用同一安装逻辑，重复安装也应成功返回跳过。"""
    from opscli.mcp.tools.skills import skills_install
    from opscli.skills.services.manager import SkillsManager

    manager = SkillsManager(registry_path=tmp_path / "registry.json", central_skills_dir=tmp_path / "central")
    target = tmp_path / "skills" / "ops-dataset-query"
    (target / "data").mkdir(parents=True)
    (target / "data" / "VERSION.json").write_text('{"version":"v8.0.0"}', encoding="utf-8")
    monkeypatch.setattr("opscli.skills.services.manager.SkillsManager", lambda: manager)

    payload = asyncio.run(skills_install("ops-dataset-query", skills_dir=str(target.parent)))

    assert payload["success"] is True
    assert payload["data"]["installed_paths"][0]["skipped"] is True
    assert payload["data"]["installed_paths"][0]["version"] == "v8.0.0"
    isolate_install_hook.assert_not_called()
