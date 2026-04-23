from pathlib import Path

from opscli.skills.exceptions import SkillRemoteError
from opscli.skills.models import SkillRecord, SkillUpgradeResult
from opscli.skills.manager import SkillsManager


def test_install_dataset_fields_template(tmp_path: Path):
    manager = SkillsManager()
    result = manager.install(
        "ops-dataset-query",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    assert result.name == "ops-dataset-query"
    assert result.to_dict()["version"] == "v0.0.0"
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
    assert (installed_path / "SKILL.md").exists()
    assert (installed_path / "data" / "VERSION.json").exists()


def test_install_ops_amazon_template(tmp_path: Path):
    manager = SkillsManager()
    result = manager.install(
        "ops-amazon",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    assert result.name == "ops-amazon"
    assert result.to_dict()["version"] == "v0.1.0"
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
    assert (installed_path / "SKILL.md").exists()
    assert (installed_path / "data" / "VERSION.json").exists()


def test_install_dataset_fields_template_to_multiple_runtimes(tmp_path: Path):
    manager = SkillsManager()
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
    manager = SkillsManager()
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
    monkeypatch.setattr(
        manager.updater,
        "upgrade_ops_dataset_query",
        lambda record, force=False: SkillUpgradeResult(
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
    manager = SkillsManager()
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

    def fake_upgrade(record, force=False):
        called_force.append(force)
        return SkillUpgradeResult(
            name=record.name,
            from_version="v1.0.0",
            to_version="v1.0.0",
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
        )

    monkeypatch.setattr(manager.updater, "upgrade_ops_dataset_query", fake_upgrade)

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
