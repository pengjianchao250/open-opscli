from pathlib import Path

from opscli.skills.detector import SkillDetector


def test_discover_skills_from_explicit_dir(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "ops-dataset-query" / "data"
    skill_dir.mkdir(parents=True)
    (skill_dir / "VERSION.json").write_text('{"version":"v1.2.3"}', encoding="utf-8")

    detector = SkillDetector()
    all_records = detector.discover(skills_dir=str(tmp_path / "skills"))

    # 过滤出仅属于显式指定目录的记录（home 目录可能有全局安装的 Skills，排除干扰）
    explicit_dir = tmp_path / "skills"
    records = [r for r in all_records if str(r.root).startswith(str(explicit_dir))]

    assert len(records) == 1
    assert records[0].name == "ops-dataset-query"
    assert records[0].version == "v1.2.3"

