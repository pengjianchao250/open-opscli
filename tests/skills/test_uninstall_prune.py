"""下架 Skill 自动清理（prune）与完整卸载（uninstall）的回归测试。

覆盖业务场景：打包版安装了 N 个 Skill，新版发行包下架其中 1 个后，
业务电脑执行 `skills install`（或 self-update 自动执行）应把下架的
Skill 从工具目录链接、中央存储、注册表三处完整移除，且不误伤
仍在发行包内的 Skill、技能广场安装的 Skill 和用户自装内容。

全部用例通过 OPSCLI_BUILTIN_TEMPLATES_DIR / 构造参数注入临时目录，
不读写真实 ~/.opscli、~/.claude（铁律8）。
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opscli.skills.cli import app as skills_app
from opscli.skills.services.manager import SkillsManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_usage_hook(monkeypatch):
    """屏蔽 install 触发的真实 Hook 注入（不写 ~/.opscli/hooks、~/.claude）。"""
    monkeypatch.setattr(
        "opscli.skills.hooks.settings_injector.ensure_skill_usage_hook",
        lambda: None,
    )


class _IsolatedDetector:
    """不扫描真实用户目录的探测器替身：只报告显式给定的目标。"""

    def __init__(self, targets: list[tuple[str, Path]] | None = None) -> None:
        self._targets = list(targets or [])

    def discover(self, skills_dir: str | None = None, cwd: Path | None = None):
        return []

    def detect_global_install_targets(self) -> list[tuple[str, Path]]:
        return list(self._targets)

    def detect_install_targets(
        self, cwd: Path | None = None, preferred_runtimes: list[str] | None = None
    ) -> list[tuple[str, Path]]:
        return list(self._targets)

    def detect_available_install_targets(self, cwd: Path | None = None) -> list[tuple[str, Path]]:
        return list(self._targets)

    def _auwork_targets(self) -> list[tuple[str, Path]]:
        return []


def _write_template_skill(root: Path, name: str, version: str = "v1.0.0") -> None:
    skill_dir = root / name
    (skill_dir / "data").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n\n测试 Skill {name}\n", encoding="utf-8")
    (skill_dir / "data" / "VERSION.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )


def _write_manifest(root: Path, names: list[str]) -> None:
    payload = {
        "version": 1,
        "default": {"source": False, "wheel": False, "binary": False, "binary_full": False},
        "skills": {
            name: {
                "source": True, "wheel": True, "binary": True, "binary_full": True,
                "tier": "ops", "reason": "测试条目",
            }
            for name in names
        },
    }
    (root / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_manager(
    tmp_path: Path,
    detector: _IsolatedDetector | None = None,
) -> SkillsManager:
    """构造完全隔离的 SkillsManager：模板、中央存储、注册表均在 tmp_path 下。"""
    return SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=detector or _IsolatedDetector(),
    )


# ── 注册表来源标记 ────────────────────────────────────────────────────────────


def test_install_records_builtin_source(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_manifest(templates, ["ops-keep"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    manager.install("ops-keep", link_targets=[("claude", tmp_path / "claude-skills")], force=True)

    entries = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))["ops-keep"]
    assert entries, "安装后注册表应有记录"
    assert all(entry.get("source") == "builtin" for entry in entries)


def test_remote_source_install_path_is_tracked_as_remote(tmp_path: Path, monkeypatch):
    """技能广场安装（复用 _install_central，source=remote）不能被下架清理误伤。"""
    templates = tmp_path / "templates"
    templates.mkdir()
    # 模板目录不含 ops-market：模拟广场独有 Skill，当前发行包没有它
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    # 模拟 remote_installer 的调用方式：把内容拷到临时目录再走 _install_central
    remote_template = tmp_path / "remote-src" / "ops-market"
    remote_template.parent.mkdir(parents=True, exist_ok=True)
    _write_template_skill(remote_template.parent, "ops-market", version="v9.9.9")
    manager._install_central(
        "ops-market",
        template_dir=remote_template,
        link_targets=[("claude", tmp_path / "claude-skills")],
        cwd=tmp_path,
        runtime=None,
        force=True,
        source="remote",
    )

    entries = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))["ops-market"]
    assert all(entry.get("source") == "remote" for entry in entries)
    # 模板目录不含该 Skill（模拟广场独有），下架判定必须跳过它
    assert manager.list_delisted_skills() == []


# ── uninstall 原语 ───────────────────────────────────────────────────────────


def test_uninstall_removes_links_central_and_registry(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_manifest(templates, ["ops-keep"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    claude_skills = tmp_path / "claude-skills"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    manager.install("ops-keep", link_targets=[("claude", claude_skills)], force=True)
    assert (claude_skills / "ops-keep").exists()
    assert (tmp_path / "central" / "ops-keep").exists()

    result = manager.uninstall("ops-keep")

    assert result["central_removed"] is True
    assert result["registry_cleared"] is True
    assert not (claude_skills / "ops-keep").exists()
    assert not (tmp_path / "central" / "ops-keep").exists()
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert "ops-keep" not in registry


def test_uninstall_dry_run_touches_nothing(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_manifest(templates, ["ops-keep"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    claude_skills = tmp_path / "claude-skills"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    manager.install("ops-keep", link_targets=[("claude", claude_skills)], force=True)

    result = manager.uninstall("ops-keep", dry_run=True)

    assert result["dry_run"] is True
    assert (claude_skills / "ops-keep").exists()
    assert (tmp_path / "central" / "ops-keep").exists()
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert "ops-keep" in registry


def test_uninstall_unknown_skill_raises(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    try:
        manager.uninstall("ops-not-installed")
    except ValueError as exc:
        assert "未找到已安装 Skill" in str(exc)
    else:
        raise AssertionError("卸载不存在的 Skill 应报错")


def test_uninstall_cleans_skills_dir_copy(tmp_path: Path, monkeypatch):
    """--skills-dir 复制模式的安装副本也应被 uninstall 清理。"""
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    custom_dir = tmp_path / "isolated-skills"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    manager.install("ops-keep", skills_dir=str(custom_dir), force=True)
    assert (custom_dir / "ops-keep").exists()

    result = manager.uninstall("ops-keep", skills_dir=str(custom_dir))

    assert str(custom_dir / "ops-keep") in result["removed_links"]
    assert not (custom_dir / "ops-keep").exists()


# ── 下架判定规则 ─────────────────────────────────────────────────────────────


def test_list_delisted_skills_applies_provenance_rules(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    # 新版发行包：只剩 ops-keep；ops-gone / ops-legacy 已下架
    _write_template_skill(templates, "ops-keep")
    _write_manifest(templates, ["ops-keep", "ops-gone", "ops-legacy"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    registry_path = tmp_path / "registry.json"
    registry = {
        # 仍在新包 → 不清理
        "ops-keep": [{"target_dir": "/tmp/x/ops-keep", "runtime": "claude", "source": "builtin"}],
        # builtin 安装 + 新包已无 → 清理
        "ops-gone": [{"target_dir": "/tmp/x/ops-gone", "runtime": "claude", "source": "builtin"}],
        # 广场安装 + 新包已无 → 不清理
        "ops-market": [{"target_dir": "/tmp/x/ops-market", "runtime": "claude", "source": "remote"}],
        # 旧版本注册表无 source + manifest 声明过（下架保留条目）→ 清理
        "ops-legacy": [{"target_dir": "/tmp/x/ops-legacy", "runtime": "claude"}],
        # 旧版本注册表无 source + manifest 从未声明（用户自装）→ 不清理
        "ops-user-owned": [{"target_dir": "/tmp/x/ops-user-owned", "runtime": "claude"}],
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    manager = SkillsManager(
        registry_path=registry_path,
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )

    assert manager.list_delisted_skills() == ["ops-gone", "ops-legacy"]


def test_list_delisted_skills_without_manifest_keeps_legacy_entries(tmp_path: Path, monkeypatch):
    """发行包缺 manifest 时，无 source 的存量记录一律不动（宁漏勿错删）。"""
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    # 不写 manifest.json
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"ops-legacy": [{"target_dir": "/tmp/x/ops-legacy", "runtime": "claude"}]}),
        encoding="utf-8",
    )
    manager = SkillsManager(
        registry_path=registry_path,
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )

    assert manager.list_delisted_skills() == []


# ── 完整业务场景：升级发行包后 install 自动对齐 ─────────────────────────────


def test_prune_aligns_local_installs_with_new_package(tmp_path: Path, monkeypatch):
    """核心场景：旧包装了 2 个 → 新包下架 1 个 → prune 后本地只剩新包内的 Skill。"""
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_template_skill(templates, "ops-gone")
    _write_manifest(templates, ["ops-keep", "ops-gone"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    claude_skills = tmp_path / "claude-skills"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    for name in ("ops-keep", "ops-gone"):
        manager.install(name, link_targets=[("claude", claude_skills)], force=True)
    assert (claude_skills / "ops-gone").exists()

    # 模拟新版发行包：模板目录移除 ops-gone，manifest 条目按惯例保留
    import shutil

    shutil.rmtree(templates / "ops-gone")
    _write_manifest(templates, ["ops-keep", "ops-gone"])

    # manager 在构造时缓存了 templates_dir，需重建以读到新目录状态
    manager2 = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    result = manager2.prune_delisted_skills()

    assert [item["name"] for item in result["pruned"]] == ["ops-gone"]
    assert result["failed"] == []
    # 下架 Skill 三处全清
    assert not (claude_skills / "ops-gone").exists()
    assert not (tmp_path / "central" / "ops-gone").exists()
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert "ops-gone" not in registry
    # 保留 Skill 原封不动
    assert (claude_skills / "ops-keep").exists()
    assert (tmp_path / "central" / "ops-keep").exists()
    assert "ops-keep" in registry


def test_prune_dry_run_reports_without_removing(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_template_skill(templates, "ops-gone")
    _write_manifest(templates, ["ops-keep", "ops-gone"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    claude_skills = tmp_path / "claude-skills"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    manager.install("ops-gone", link_targets=[("claude", claude_skills)], force=True)

    import shutil

    shutil.rmtree(templates / "ops-gone")

    manager2 = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(),
    )
    result = manager2.prune_delisted_skills(dry_run=True)

    assert [item["name"] for item in result["pruned"]] == ["ops-gone"]
    assert (claude_skills / "ops-gone").exists()
    assert (tmp_path / "central" / "ops-gone").exists()


def test_central_only_install_is_registry_recorded(tmp_path: Path, monkeypatch):
    """无 AI 工具场景：仅落中央存储的安装也要有注册表记录，供后续清理识别归属。"""
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_manifest(templates, ["ops-keep"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_IsolatedDetector(targets=[]),
    )
    manager.install("ops-keep", link_targets=[], force=True)

    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert registry["ops-keep"][0]["runtime"] == "central"
    assert registry["ops-keep"][0]["source"] == "builtin"


# ── CLI 层：install 自动清理 + uninstall / prune 命令 ────────────────────────


def test_batch_install_auto_prunes_delisted_skill(tmp_path: Path, monkeypatch):
    """端到端核心场景：业务电脑先装满旧包，升级发行包后再 install 即自动移除下架 Skill。"""
    import shutil

    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_template_skill(templates, "ops-gone")
    _write_manifest(templates, ["ops-keep", "ops-gone"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    tool_skills = tmp_path / "tool-skills"
    detector = _IsolatedDetector(targets=[("claude", tool_skills)])

    def _build_manager() -> SkillsManager:
        return SkillsManager(
            registry_path=tmp_path / "registry.json",
            central_skills_dir=tmp_path / "central",
            detector=detector,
        )

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", _build_manager)

    # 第一次批量安装：旧包的 2 个 Skill 全部装上
    result = runner.invoke(skills_app, ["install", "--yes", "--verbose"])
    assert result.exit_code == 0, result.output
    assert (tool_skills / "ops-keep").exists()
    assert (tool_skills / "ops-gone").exists()

    # 模拟升级后的新发行包：模板目录移除 ops-gone，manifest 条目按惯例保留
    shutil.rmtree(templates / "ops-gone")

    # 再次批量安装（self-update 升级后自动执行的就是这条命令）
    result = runner.invoke(skills_app, ["install", "--yes"])
    assert result.exit_code == 0, result.output
    # 交互模式 stdout 混有 TUI 表格输出，不能整体 json.loads；
    # 用输出文本 + 落盘状态双重确认清理动作已发生
    assert "已清理下架 Skill" in result.output
    assert "ops-gone" in result.output
    # 下架 Skill 三处全清，保留 Skill 不受影响
    assert not (tool_skills / "ops-gone").exists()
    assert not (tmp_path / "central" / "ops-gone").exists()
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert "ops-gone" not in registry
    assert (tool_skills / "ops-keep").exists()
    assert (tmp_path / "central" / "ops-keep").exists()


def test_prune_command_reports_aligned_state_and_cleans(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-gone")
    _write_manifest(templates, ["ops-gone"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    tool_skills = tmp_path / "tool-skills"
    manager_holder: dict[str, SkillsManager] = {}

    def _build_manager() -> SkillsManager:
        manager = SkillsManager(
            registry_path=tmp_path / "registry.json",
            central_skills_dir=tmp_path / "central",
            detector=_IsolatedDetector(targets=[("claude", tool_skills)]),
        )
        manager_holder["m"] = manager
        return manager

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", _build_manager)

    # 对齐状态：没装任何东西时 prune 报告"已对齐"
    result = runner.invoke(skills_app, ["prune"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["pruned"] == []

    # 装一个再下架：prune 命令完整移除
    manager_holder["m"].install("ops-gone", link_targets=[("claude", tool_skills)], force=True)
    import shutil

    shutil.rmtree(templates / "ops-gone")

    result = runner.invoke(skills_app, ["prune", "--pretty"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["name"] for item in payload["data"]["pruned"]] == ["ops-gone"]
    assert not (tool_skills / "ops-gone").exists()

    # dry-run：手工构造一个下架记录（模板已删无法再 install），验证只报告不删除
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    registry["ops-ghost"] = [{"target_dir": str(tool_skills / "ops-ghost"), "runtime": "claude", "source": "builtin"}]
    (tmp_path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")

    result = runner.invoke(skills_app, ["prune", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["name"] for item in payload["data"]["pruned"]] == ["ops-ghost"]
    assert payload["data"]["dry_run"] is True


def test_uninstall_command_removes_everything(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    templates.mkdir()
    _write_template_skill(templates, "ops-keep")
    _write_manifest(templates, ["ops-keep"])
    monkeypatch.setenv("OPSCLI_BUILTIN_TEMPLATES_DIR", str(templates))

    tool_skills = tmp_path / "tool-skills"
    detector = _IsolatedDetector(targets=[("claude", tool_skills)])

    def _build_manager() -> SkillsManager:
        return SkillsManager(
            registry_path=tmp_path / "registry.json",
            central_skills_dir=tmp_path / "central",
            detector=detector,
        )

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", _build_manager)

    built = _build_manager()
    built.install("ops-keep", link_targets=[("claude", tool_skills)], force=True)

    result = runner.invoke(skills_app, ["uninstall", "ops-keep"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["central_removed"] is True
    assert payload["data"]["registry_cleared"] is True
    assert not (tool_skills / "ops-keep").exists()
    assert not (tmp_path / "central" / "ops-keep").exists()

    # 卸载不存在的 Skill：报错且退出码非 0
    result = runner.invoke(skills_app, ["uninstall", "ops-missing"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
