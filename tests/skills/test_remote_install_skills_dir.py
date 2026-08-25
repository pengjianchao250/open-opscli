"""远程广场安装的 `--skills-dir` 隔离语义回归测试。

背景（回归防线）：`install_remote_skill()` 曾经接收 `skills_dir` 却完全不使用，
导致 `opscli skills install <id> --skills-dir DIR` 把技能链接进本机探测到的
**全部**运行时目录（~/.claude、~/.codex、~/.openclaw ...），而 DIR 里空空如也。
下游「自带独立 CODEX_HOME 的本地 Agent」依赖 `--skills-dir` 做隔离安装，
一旦回退成探测就会篡改用户自己 codex 可见的技能集合与版本。

本文件锁定三件事：
1. 显式传 `skills_dir` → 只落这一个目录，不碰任何运行时目录；
2. 不传 `skills_dir` → 多运行时探测 + 全装的既有默认行为不变；
3. `skills_dir` 与 `runtime` 同传 → `skills_dir` 优先，`runtime` 被忽略。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from opscli.skills.marketplace import remote_installer
from opscli.skills.services.manager import SkillsManager

_SKILL_NAME = "ops-weather-query"
_IDENTIFIER = f"tester@{_SKILL_NAME}"
_VERSION = "1.0.0"

# 探测逻辑会检查的全部运行时目录名（相对 fake home），用于断言"一个都没被写"
_RUNTIME_SKILL_DIRS = (
    Path(".claude") / "skills",
    Path(".codex") / "skills",
    Path(".openclaw") / "skills",
    Path(".config") / "opencode" / "skills",
    Path(".workbuddy") / "skills",
    Path(".trae-cn") / "skills",
    Path(".agents") / "skills",
)


def _make_zip_bytes() -> bytes:
    """构造一个最小可用的技能 zip 包（SKILL.md + data/VERSION.json）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("SKILL.md", "# ops-weather-query\n\n测试用技能。\n")
        zf.writestr(
            "data/VERSION.json",
            json.dumps({"name": _SKILL_NAME, "version": _VERSION}, ensure_ascii=False),
        )
    return buffer.getvalue()


class _FakeResponse:
    """替代 httpx.Response，只提供 remote_installer 用到的两个成员。"""

    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        """下载成功，无需抛错。"""
        return None


class _FakeMarketplaceClient:
    """替代 MarketplaceClient，屏蔽全部网络调用（铁律8：测试不依赖真实网络）。"""

    def get_by_identifier(self, username: str, skill_name: str, share_code=None) -> dict:
        """返回最小可用的广场元数据。"""
        return {"id": 1, "latest_version": _VERSION}

    def get_download_url(self, skill_id, version=None, share_code=None) -> str:
        """返回一个占位下载地址，实际内容由被 patch 的 httpx.get 提供。"""
        return "https://example.invalid/skill.zip"

    def record_install(self, skill_id, payload) -> None:
        """安装回调：测试中不做任何事。"""
        return None


@pytest.fixture
def remote_env(tmp_path: Path, monkeypatch):
    """搭建隔离的远程安装环境，返回 (fake_home, central_dir)。

    - fake home 预置 .claude / .codex 两个运行时配置目录：
      修复前的错误行为会把技能写进它们，因此它们是回归断言的"探针"；
    - 中央存储、安装注册表全部重定向到 tmp_path（铁律8：不触碰真实用户目录）；
    - 网络与 client_id 全部打桩。
    """
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".codex").mkdir(parents=True)
    central = tmp_path / "central"

    # Path.home() 同时被 remote_installer（cwd）和 detector（运行时探测）使用，
    # 整体重定向才能保证探测结果落在 fake home 内、可被断言
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(remote_installer, "get_central_skills_dir", lambda: central)
    monkeypatch.setattr(remote_installer, "MarketplaceClient", _FakeMarketplaceClient)
    monkeypatch.setattr(remote_installer, "_get_client_id", lambda: "test-client")
    monkeypatch.setattr(
        remote_installer.httpx, "get", lambda *args, **kwargs: _FakeResponse(_make_zip_bytes())
    )

    # SkillsManager 在 install_remote_skill 内部按需 import，patch 模块属性即可生效；
    # 注入 tmp 注册表与 tmp 中央目录，避免写入真实 ~/.config/opscli
    def _managed(*args, **kwargs):
        kwargs.setdefault("registry_path", tmp_path / "registry.json")
        kwargs.setdefault("central_skills_dir", central)
        return SkillsManager(*args, **kwargs)

    monkeypatch.setattr("opscli.skills.services.manager.SkillsManager", _managed)

    return fake_home, central


def _assert_no_runtime_dir_touched(fake_home: Path) -> None:
    """断言 fake home 下没有任何运行时 skills 目录被创建或写入技能。"""
    for relative in _RUNTIME_SKILL_DIRS:
        runtime_dir = fake_home / relative
        assert not (runtime_dir / _SKILL_NAME).exists(), f"不应写入运行时目录: {runtime_dir}"


def test_skills_dir_installs_only_into_that_directory(remote_env, tmp_path: Path):
    """显式 --skills-dir 时只落指定目录，不写任何运行时目录。"""
    fake_home, central = remote_env
    isolated = tmp_path / "isolated" / "skills"

    payload = remote_installer.install_remote_skill(
        identifier=_IDENTIFIER,
        skills_dir=str(isolated),
        force=True,
    )

    assert payload["success"] is True, payload.get("error")
    # 指定目录里确实有技能，且内容可读（链接指向中央存储实体）
    assert (isolated / _SKILL_NAME / "SKILL.md").exists()
    assert (central / _SKILL_NAME / "SKILL.md").exists()
    # 安装结果只有一条，指向指定目录
    installs = payload["data"]["installs"]
    assert len(installs) == 1
    assert Path(installs[0]["target_dir"]) == isolated / _SKILL_NAME
    assert payload["data"]["skills_dir"] == str(isolated)
    # 核心回归断言：用户自己的运行时目录一个都没被碰
    _assert_no_runtime_dir_touched(fake_home)


def test_without_skills_dir_keeps_multi_runtime_detection(remote_env):
    """不传 --skills-dir 时，保持"探测本机运行时 + 全装"的既有默认行为。"""
    fake_home, _central = remote_env

    payload = remote_installer.install_remote_skill(
        identifier=_IDENTIFIER,
        force=True,
    )

    assert payload["success"] is True, payload.get("error")
    assert payload["data"]["skills_dir"] is None
    installed_paths = {Path(item["target_dir"]) for item in payload["data"]["installs"]}
    # fake home 预置的两个运行时目录都应被装上（默认行为未回归）
    assert fake_home / ".claude" / "skills" / _SKILL_NAME in installed_paths
    assert fake_home / ".codex" / "skills" / _SKILL_NAME in installed_paths
    assert (fake_home / ".claude" / "skills" / _SKILL_NAME / "SKILL.md").exists()
    assert (fake_home / ".codex" / "skills" / _SKILL_NAME / "SKILL.md").exists()


def test_skills_dir_takes_precedence_over_runtime(remote_env, tmp_path: Path):
    """--skills-dir 与 --runtime 同传时，以 --skills-dir 为准，runtime 被忽略。"""
    fake_home, _central = remote_env
    isolated = tmp_path / "isolated" / "skills"

    payload = remote_installer.install_remote_skill(
        identifier=_IDENTIFIER,
        skills_dir=str(isolated),
        runtime="claude,codex",
        force=True,
    )

    assert payload["success"] is True, payload.get("error")
    installs = payload["data"]["installs"]
    assert len(installs) == 1
    assert Path(installs[0]["target_dir"]) == isolated / _SKILL_NAME
    # runtime 指名的 claude / codex 目录都不应被写入
    _assert_no_runtime_dir_touched(fake_home)


def test_runtime_alone_installs_only_into_that_runtime(remote_env):
    """只传 --runtime 时，也只安装到该运行时（确认既有语义符合预期）。"""
    fake_home, _central = remote_env

    payload = remote_installer.install_remote_skill(
        identifier=_IDENTIFIER,
        runtime="codex",
        force=True,
    )

    assert payload["success"] is True, payload.get("error")
    installs = payload["data"]["installs"]
    assert len(installs) == 1
    assert Path(installs[0]["target_dir"]) == fake_home / ".codex" / "skills" / _SKILL_NAME
    assert not (fake_home / ".claude" / "skills" / _SKILL_NAME).exists()


def test_cli_hint_when_skills_dir_and_runtime_both_given(monkeypatch, tmp_path: Path):
    """CLI 层：同传 --skills-dir 与 --runtime 时给出一行提示，且提示走 stderr 不污染 JSON。"""
    from typer.testing import CliRunner

    from opscli.skills.cli import app

    captured: dict = {}

    def _fake_install_remote_skill(**kwargs):
        captured.update(kwargs)
        return {"success": True, "command": "skills install", "data": {}, "error": None}

    monkeypatch.setattr(
        "opscli.skills.commands.cli.install_remote_skill", _fake_install_remote_skill
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "install",
            _IDENTIFIER,
            "--skills-dir",
            str(tmp_path / "skills"),
            "--runtime",
            "claude",
        ],
    )

    assert result.exit_code == 0
    # skills_dir 必须被透传到安装器（修复前它被丢弃）
    assert captured["skills_dir"] == str(tmp_path / "skills")
    # stdout 仍是可解析的纯 JSON，提示不能混进去
    assert json.loads(result.stdout)["success"] is True
    assert "--runtime" in result.output and "被忽略" in result.output
