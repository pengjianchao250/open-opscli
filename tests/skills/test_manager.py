"""Skill 安装、跳过及升级编排回归。"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from opscli.skills.exceptions import SkillRemoteError
from opscli.skills.models import SkillRecord, SkillUpgradeResult
from opscli.skills.manager import SkillsManager


def test_install_dataset_fields_template(tmp_path: Path):
    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    result = manager.install(
        "ops-dataset-query",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    assert result.name == "ops-dataset-query"
    assert result.to_dict()["version"] == "v0.0.1"
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
    assert (installed_path / "SKILL.md").exists()
    assert (installed_path / "data" / "VERSION.json").exists()


def test_install_ops_amazon_template(tmp_path: Path):
    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    result = manager.install(
        "ops-amazon",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    assert result.name == "ops-amazon"
    assert result.to_dict()["version"] == "v0.0.1"
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
    assert (installed_path / "SKILL.md").exists()
    assert (installed_path / "data" / "VERSION.json").exists()


def test_install_ops_methods_card_template(tmp_path: Path):
    """确认 methods card Skill 模板能走现有安装链路。"""
    manager = SkillsManager(registry_path=tmp_path / "registry.json")

    result = manager.install(
        "ops-methods-card",
        skills_dir=str(tmp_path / "skills"),
    )

    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
    version_payload = json.loads((installed_path / "data" / "VERSION.json").read_text(encoding="utf-8"))
    assert (installed_path / "SKILL.md").exists()
    assert version_payload["name"] == "ops-methods-card"
    assert not any(
        "__pycache__" in item.parts or item.suffix in {".pyc", ".pyo"}
        for item in installed_path.rglob("*")
    )


def test_install_dataset_fields_template_to_multiple_runtimes(tmp_path: Path):
    # 必须隔离 central_skills_dir：不传时默认写用户真实 ~/.opscli/skills，
    # 会把 upgrade 拉取的真实元数据覆盖成模板占位符（铁律8：测试不依赖真实环境）
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
    )
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".openclaw").mkdir()

    result = manager.install(
        "ops-dataset-query",
        cwd=tmp_path,
        runtime=["claude", "openclaw"],
        force=False,
    )

    payload = result.to_dict()
    assert len(payload["installed_paths"]) == 2
    paths = {item["tool"]: item["path"] for item in payload["installed_paths"]}
    assert ".claude/skills/ops-dataset-query" in paths["claude-code"]
    assert ".openclaw/skills/ops-dataset-query" in paths["openclaw"]


def test_status_includes_remote_summary(tmp_path: Path, monkeypatch):
    manager = SkillsManager()
    record = SkillRecord(
        name="ops-dataset-query",
        version="v1.0.0",
        runtime="custom",
        root=tmp_path / "ops-dataset-query",
        version_file=tmp_path / "ops-dataset-query" / "data" / "VERSION.json",
    )

    monkeypatch.setattr(manager, "list_skills", lambda **kwargs: [record])
    monkeypatch.setattr(
        manager.updater,
        "build_remote_summary",
        lambda skill_name: {
            "skill_name": skill_name,
            "ops_url": "https://ops.example.com/api",
            "manifest_endpoint": "https://ops.example.com/api/v1/data-metrics/datasets/skill/manifest",
            "manifest": {"version": "v1.1.0"},
        },
    )

    result = manager.status(skills_dir=str(tmp_path))

    assert result["remote_summary"]["manifest"]["version"] == "v1.1.0"
    assert result["installed"][0]["remote_version"] == "v1.1.0"
    assert result["installed"][0]["has_update"] is True
    assert result["skills"][0]["installed_paths"][0]["tool"] == "custom"
    assert result["skills"][0]["has_update"] is True


def test_upgrade_updates_all_matching_skill_records(tmp_path: Path, monkeypatch):
    # 注入空注册表路径，避免读取真实 ~/.config/opscli/installed_skills.json 影响测试
    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    record1 = SkillRecord(
        name="ops-dataset-query",
        version="v1.0.0",
        runtime="claude",
        root=tmp_path / ".claude" / "skills" / "ops-dataset-query",
        version_file=tmp_path / ".claude" / "skills" / "ops-dataset-query" / "data" / "VERSION.json",
    )
    record2 = SkillRecord(
        name="ops-dataset-query",
        version="v1.0.0",
        runtime="openclaw",
        root=tmp_path / ".openclaw" / "skills" / "ops-dataset-query",
        version_file=tmp_path / ".openclaw" / "skills" / "ops-dataset-query" / "data" / "VERSION.json",
    )

    monkeypatch.setattr(manager, "list_skills", lambda **kwargs: [record1, record2])
    fake_data = {
        "manifest": {"version": "v1.1.0"},
        "fields_csv": "",
        "datasets_csv": "",
        "dataset_catalog": {},
        "query_metadata": {},
        "field_count": 0,
    }

    monkeypatch.setattr(manager.updater, "fetch_upgrade_data", lambda name, on_step=None: fake_data)
    monkeypatch.setattr(
        manager.updater,
        "apply_upgrade_data",
        lambda record, data, force=False, on_step=None: SkillUpgradeResult(
            name=record.name,
            from_version="v1.0.0",
            to_version="v1.1.0",
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
        ),
    )

    result = manager.upgrade(name="ops-dataset-query", cwd=tmp_path)

    payload = result.to_dict()
    assert len(payload["updated"]) == 1
    assert payload["updated"][0]["tools"] == ["claude-code", "openclaw"]


def test_upgrade_passes_force_to_all_matching_skill_records(tmp_path: Path, monkeypatch):
    # 注入空注册表路径，避免读取真实 ~/.config/opscli/installed_skills.json 影响测试
    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    record1 = SkillRecord(
        name="ops-dataset-query",
        version="v1.0.0",
        runtime="claude",
        root=tmp_path / ".claude" / "skills" / "ops-dataset-query",
        version_file=tmp_path / ".claude" / "skills" / "ops-dataset-query" / "data" / "VERSION.json",
    )
    record2 = SkillRecord(
        name="ops-dataset-query",
        version="v1.0.0",
        runtime="openclaw",
        root=tmp_path / ".openclaw" / "skills" / "ops-dataset-query",
        version_file=tmp_path / ".openclaw" / "skills" / "ops-dataset-query" / "data" / "VERSION.json",
    )
    called_force: list[bool] = []

    monkeypatch.setattr(manager, "list_skills", lambda **kwargs: [record1, record2])

    fake_data = {"manifest": {"version": "v1.0.0"}, "fields_csv": "", "datasets_csv": "", "query_metadata": {}, "field_count": 0}

    def fake_fetch(skill_name, on_step=None):
        return fake_data

    def fake_apply(record, data, force=False, on_step=None):
        called_force.append(force)
        return SkillUpgradeResult(
            name=record.name,
            from_version="v1.0.0",
            to_version="v1.0.0",
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
        )

    monkeypatch.setattr(manager.updater, "fetch_upgrade_data", fake_fetch)
    monkeypatch.setattr(manager.updater, "apply_upgrade_data", fake_apply)

    manager.upgrade(name="ops-dataset-query", cwd=tmp_path, force=True)

    assert called_force == [True, True]


def test_status_wraps_remote_error(tmp_path: Path, monkeypatch):
    manager = SkillsManager()
    monkeypatch.setattr(manager, "list_skills", lambda **kwargs: [])

    def fail(_skill_name: str):
        raise SkillRemoteError("未登录", endpoint="/manifest", status_code=401)

    monkeypatch.setattr(manager.updater, "build_remote_summary", fail)

    payload = manager.status(skills_dir=str(tmp_path))

    assert payload["remote_error"] == {
        "type": "SkillRemoteError",
        "message": "未登录",
        "endpoint": "/manifest",
        "status_code": 401,
    }


def test_install_central_no_ai_tools_uses_central_store(tmp_path: Path):
    """无 AI 工具时，install 应正常写入中央存储，返回 runtime='central'。"""
    # 注入空 detector（两个检测方法均返回空列表），隔离真实 ~/.claude 等目录
    mock_detector = MagicMock()
    mock_detector.detect_available_install_targets.return_value = []
    mock_detector.detect_global_install_targets.return_value = []
    # discover 保留真实行为（list_skills 不是本测试关注点，但需要返回可迭代对象）
    mock_detector.discover.return_value = []

    central = tmp_path / "central"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=central,
        detector=mock_detector,
    )

    result = manager.install("ops-dataset-query", cwd=tmp_path, force=False)

    payload = result.to_dict()
    # 只有一条中央存储记录
    assert len(payload["installed_paths"]) == 1
    assert payload["installed_paths"][0]["tool"] == "中央存储"
    # 中央目录已创建，Skill 文件存在
    assert (central / "ops-dataset-query" / "data" / "VERSION.json").exists()
    assert (central / "ops-dataset-query" / "SKILL.md").exists()
    # central_path 字段指向中央目录
    assert "ops-dataset-query" in payload["central_path"]


def _empty_detector() -> MagicMock:
    """构造无 AI 工具的 detector，隔离真实 ~/.claude 等目录。"""
    mock_detector = MagicMock()
    mock_detector.detect_available_install_targets.return_value = []
    mock_detector.detect_global_install_targets.return_value = []
    mock_detector.discover.return_value = []
    return mock_detector


@pytest.mark.parametrize("version", ["v0.0.0", "v0.0.3", "v9.9.9"])
@pytest.mark.parametrize("central_mode", [False, True])
def test_install_skips_existing_without_writes(tmp_path, version, central_mode, isolate_install_hook):
    """重复安装不改题库、版本或账本，旧版本也不隐式覆盖。"""
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
        detector=_empty_detector(),
    )
    skill_name = "ops-dataset-query"
    root = tmp_path / ("central" if central_mode else "skills")
    data = root / skill_name / "data"
    data.mkdir(parents=True)
    (data / "VERSION.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (data / "question_templates.json").write_text('管理端同步的题库', encoding="utf-8")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in data.iterdir()}

    result = manager.install(skill_name, **({"link_targets": []} if central_mode else {"skills_dir": str(root)}))

    assert result.installs[0].skipped is True
    assert result.installs[0].version == version
    assert result.to_dict()["installed_paths"][0]["skipped"] is True
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in data.iterdir()} == before
    assert not (tmp_path / "registry.json").exists()
    isolate_install_hook.assert_not_called()


def test_install_keeps_existing_targets_and_adds_missing_link(tmp_path, monkeypatch):
    """补装缺失工具时复用中央数据，已有目标连同时间戳保持不变。"""
    import shutil

    manager = SkillsManager(registry_path=tmp_path / "registry.json", central_skills_dir=tmp_path / "central")
    skill_name = "ops-dataset-query"
    central = tmp_path / "central" / skill_name
    existing = tmp_path / "old-tool" / skill_name
    for target in (central, existing):
        (target / "data").mkdir(parents=True)
        (target / "data" / "VERSION.json").write_text('{"version":"v9.9.9"}', encoding="utf-8")
        (target / "SKILL.md").write_text("已安装内容", encoding="utf-8")
    (existing / "data" / "VERSION.json").write_text('{"version":"v1.0.0"}', encoding="utf-8")
    before = (existing / "SKILL.md").stat().st_mtime_ns
    # 用复制模拟 Windows 链接降级，避免测试依赖系统链接权限。
    def copy_link(target, link):
        shutil.copytree(target, link)
        return "copy_fallback"

    monkeypatch.setattr(manager.linker, "_create_link", copy_link)
    result = manager.install(skill_name, link_targets=[("old", existing.parent), ("new", tmp_path / "new-tool")])

    assert [item.skipped for item in result.installs] == [True, False]
    assert [item["version"] for item in result.to_dict()["installed_paths"]] == ["v1.0.0", "v9.9.9"]
    assert (existing / "SKILL.md").stat().st_mtime_ns == before
    assert (tmp_path / "new-tool" / skill_name / "SKILL.md").read_text(encoding="utf-8") == "已安装内容"
    assert json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))[skill_name][0]["runtime"] == "new"


def test_install_skips_existing_target_without_central_copy(tmp_path, isolate_install_hook):
    """已有独立安装时不额外创建中央目录或链接。"""
    manager = SkillsManager(registry_path=tmp_path / "registry.json", central_skills_dir=tmp_path / "central")
    skill_name = "ops-dataset-query"
    target = tmp_path / "tool" / skill_name
    (target / "data").mkdir(parents=True)
    (target / "data" / "VERSION.json").write_text('{"version":"v1.2.3"}', encoding="utf-8")

    result = manager.install(skill_name, link_targets=[("custom", target.parent)])

    assert result.installs[0].skipped is True
    assert not (tmp_path / "central").exists()
    assert not (tmp_path / "registry.json").exists()
    isolate_install_hook.assert_not_called()


@pytest.mark.parametrize("version_json", [None, "broken json", "[]"])
def test_install_skips_skill_without_valid_version(tmp_path, version_json, isolate_install_hook):
    """旧副本版本缺失或损坏也能跳过，不覆盖用户内容。"""
    manager = SkillsManager(registry_path=tmp_path / "registry.json", central_skills_dir=tmp_path / "central")
    target = tmp_path / "skills" / "ops-dataset-query"
    (target / "data").mkdir(parents=True)
    (target / "SKILL.md").write_text("用户维护的 Skill", encoding="utf-8")
    if version_json is not None:
        (target / "data" / "VERSION.json").write_text(version_json, encoding="utf-8")

    result = manager.install("ops-dataset-query", skills_dir=str(target.parent))

    assert result.installs[0].skipped is True
    assert result.installs[0].version == "unknown"
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "用户维护的 Skill"
    isolate_install_hook.assert_not_called()


def test_install_central_force_overwrites_stale_copy(tmp_path: Path):
    """显式 force 才允许用模板覆盖旧版中央副本。"""
    central = tmp_path / "central"
    # 预置一个版本更旧的中央副本（模拟升级 opscli 包前的残留）
    stale_dir = central / "ops-dataset-query" / "data"
    stale_dir.mkdir(parents=True)
    (stale_dir / "VERSION.json").write_text(
        '{"name":"ops-dataset-query","version":"v0.0.0"}', encoding="utf-8"
    )

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=central,
        detector=_empty_detector(),
    )

    # 内置模板的真实版本（动态读取，避免随模板升级而漂移）
    template_version = json.loads(
        (manager.templates_dir / "ops-dataset-query" / "data" / "VERSION.json").read_text(encoding="utf-8")
    )["version"]

    result = manager.install("ops-dataset-query", cwd=tmp_path, force=True)

    # 中央副本已被内置模板覆盖：版本号从 v0.0.0 刷新为模板版本，且模板文件补齐
    payload = json.loads(
        (central / "ops-dataset-query" / "data" / "VERSION.json").read_text(encoding="utf-8")
    )
    assert payload["version"] == template_version
    assert payload["version"] != "v0.0.0"
    assert result.to_dict()["version"] == template_version
    assert (central / "ops-dataset-query" / "SKILL.md").exists()


def test_install_central_force_overwrites_newer_copy(tmp_path: Path):
    """显式 force 保留用发行模板重置新版中央副本的能力。"""
    central = tmp_path / "central"
    # 预置一个版本更高的中央副本（模拟本地残留了更高版本）
    newer_dir = central / "ops-dataset-query" / "data"
    newer_dir.mkdir(parents=True)
    (newer_dir / "VERSION.json").write_text(
        '{"name":"ops-dataset-query","version":"v9.9.9"}', encoding="utf-8"
    )

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=central,
        detector=_empty_detector(),
    )
    template_version = json.loads(
        (manager.templates_dir / "ops-dataset-query" / "data" / "VERSION.json").read_text(encoding="utf-8")
    )["version"]

    manager.install("ops-dataset-query", cwd=tmp_path, force=True)

    # 版本号不一致即覆盖：高版本被降级为模板版本
    payload = json.loads(
        (central / "ops-dataset-query" / "data" / "VERSION.json").read_text(encoding="utf-8")
    )
    assert payload["version"] == template_version
    assert payload["version"] != "v9.9.9"


def test_install_central_reuses_same_version_copy(tmp_path: Path):
    """普通 install（非 force）遇到版本号相同的中央副本时，复用旧副本、不做删除重拷。"""
    central = tmp_path / "central"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=central,
        detector=_empty_detector(),
    )
    template_version = json.loads(
        (manager.templates_dir / "ops-dataset-query" / "data" / "VERSION.json").read_text(encoding="utf-8")
    )["version"]

    # 预置一个与模板同版本的中央副本，并放一个标记文件用于检测是否被 rmtree
    same_dir = central / "ops-dataset-query" / "data"
    same_dir.mkdir(parents=True)
    (same_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": template_version}), encoding="utf-8"
    )
    marker = central / "ops-dataset-query" / "_marker.txt"
    marker.write_text("keep-me", encoding="utf-8")

    manager.install("ops-dataset-query", cwd=tmp_path, force=False)

    # 版本相同 → 未删除重拷，标记文件仍在
    assert marker.exists()


def test_upgrade_central_no_ai_tools_reads_central_store(tmp_path: Path, monkeypatch):
    """无 AI 工具时，upgrade 应从中央存储读取记录并执行升级。"""
    # 先在中央存储写入一个模拟 Skill 目录
    central = tmp_path / "central"
    skill_dir = central / "ops-dataset-query"
    data_dir = skill_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text('{"version":"v1.0.0"}', encoding="utf-8")

    mock_detector = MagicMock()
    mock_detector.discover.return_value = []

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=central,
        detector=mock_detector,
    )

    fake_data = {
        "manifest": {"version": "v1.1.0"},
        "fields_csv": "",
        "datasets_csv": "",
        "dataset_catalog": {},
        "query_metadata": {},
        "field_count": 0,
    }
    monkeypatch.setattr(manager.updater, "fetch_upgrade_data", lambda name, on_step=None: fake_data)
    monkeypatch.setattr(
        manager.updater,
        "apply_upgrade_data",
        lambda record, data, force=False, on_step=None: SkillUpgradeResult(
            name=record.name,
            from_version="v1.0.0",
            to_version="v1.1.0",
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
        ),
    )

    result = manager.upgrade(name="ops-dataset-query", cwd=tmp_path)

    payload = result.to_dict()
    assert len(payload["updated"]) == 1
    assert payload["updated"][0]["from_version"] == "v1.0.0"
    assert payload["updated"][0]["to_version"] == "v1.1.0"
