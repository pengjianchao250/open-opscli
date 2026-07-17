import json
import zipfile
from pathlib import Path

from opscli.skills.packaging import (
    collect_skill_datas,
    prune_templates_dir,
    selected_skill_names,
    skill_allowed,
    validate_release_manifest,
)
from scripts.check_skill_release_manifest import skill_names_in_members


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    (skill_dir / "data").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (skill_dir / "data" / "VERSION.json").write_text('{"version":"v1.0.0"}', encoding="utf-8")


def _write_manifest(root: Path) -> None:
    payload = {
        "version": 1,
        "default": {"source": False, "wheel": False, "binary": False, "binary_full": False},
        "skills": {
            "ops-core": {
                "source": True,
                "wheel": True,
                "binary": True,
                "binary_full": True,
                "tier": "core",
                "reason": "core",
            },
            "ops-extra": {
                "source": True,
                "wheel": False,
                "binary": False,
                "binary_full": True,
                "tier": "ops",
                "reason": "extra",
            },
        },
    }
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_selected_skill_names_respects_profile_and_artifact(tmp_path: Path):
    _write_skill(tmp_path, "ops-core")
    _write_skill(tmp_path, "ops-extra")
    _write_manifest(tmp_path)

    assert selected_skill_names(profile="python-release", artifact="wheel", templates_dir=tmp_path) == ["ops-core"]
    assert selected_skill_names(profile="python-release", artifact="sdist", templates_dir=tmp_path) == ["ops-core", "ops-extra"]
    assert selected_skill_names(profile="binary-minimal", artifact="binary", templates_dir=tmp_path) == ["ops-core"]
    assert selected_skill_names(profile="binary-full", artifact="binary", templates_dir=tmp_path) == ["ops-core", "ops-extra"]


def test_prune_templates_dir_removes_disallowed_skills(tmp_path: Path):
    manifest_root = tmp_path / "manifest"
    target_root = tmp_path / "target"
    manifest_root.mkdir()
    target_root.mkdir()
    for name in ("ops-core", "ops-extra"):
        _write_skill(manifest_root, name)
        _write_skill(target_root, name)
    _write_manifest(manifest_root)

    kept = prune_templates_dir(
        target_root,
        profile="python-release",
        artifact="wheel",
        manifest_templates_dir=manifest_root,
    )

    assert kept == ["ops-core"]
    assert (target_root / "ops-core").exists()
    assert not (target_root / "ops-extra").exists()


def test_validate_release_manifest_requires_every_template_declared(tmp_path: Path):
    _write_skill(tmp_path, "ops-core")
    _write_skill(tmp_path, "ops-missing")
    _write_manifest(tmp_path)

    problems = validate_release_manifest(tmp_path)

    assert "模板目录未在 manifest 声明: ops-missing" in problems


def test_skill_allowed_uses_manifest_default_for_unknown_skill(tmp_path: Path):
    _write_skill(tmp_path, "ops-core")
    _write_manifest(tmp_path)

    assert skill_allowed("unknown", profile="python-release", artifact="wheel", templates_dir=tmp_path) is False


def test_collect_skill_datas_keeps_pyinstaller_destination_shape(tmp_path: Path):
    _write_skill(tmp_path, "ops-core")
    _write_skill(tmp_path, "ops-extra")
    _write_manifest(tmp_path)

    datas = collect_skill_datas(profile="binary-minimal", templates_dir=tmp_path)

    assert (str(tmp_path / "ops-core" / "SKILL.md"), "opscli/skills/templates/ops-core") in datas
    assert all("ops-extra" not in source for source, _dest in datas)


def test_skill_names_in_members_handles_wheel_paths(tmp_path: Path):
    wheel = tmp_path / "demo.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("opscli/skills/templates/ops-core/SKILL.md", "")
        zf.writestr("opscli/skills/templates/manifest.json", "{}")

    with zipfile.ZipFile(wheel) as zf:
        assert skill_names_in_members(zf.namelist()) == {"ops-core"}


def test_ops_feedback_query_is_internal_only():
    templates_dir = Path("opscli/skills/templates")

    assert "ops-feedback-query" in selected_skill_names(
        profile="internal",
        artifact="wheel",
        templates_dir=templates_dir,
    )
    for profile, artifact in (
        ("python-release", "wheel"),
        ("python-release", "sdist"),
        ("binary-minimal", "binary"),
        ("binary-full", "binary"),
    ):
        assert "ops-feedback-query" not in selected_skill_names(
            profile=profile,
            artifact=artifact,
            templates_dir=templates_dir,
        )


def test_ops_feedback_query_files_are_not_collected_for_binaries():
    templates_dir = Path("opscli/skills/templates")

    for profile in ("binary-minimal", "binary-full"):
        datas = collect_skill_datas(profile=profile, templates_dir=templates_dir)
        assert all("ops-feedback-query" not in source for source, _destination in datas)
