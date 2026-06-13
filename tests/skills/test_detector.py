from pathlib import Path

from opscli.skills.detector import SkillDetector
from opscli.skills.discovery import detector as detector_module


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


def test_runtime_all_targets_all_supported_global_dirs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # 模拟 Windows 并构造一个 AuWork 数字用户目录，验证 all 同时覆盖 auwork
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    (tmp_path / ".auwork" / "1001").mkdir(parents=True)

    targets = SkillDetector().detect_install_targets(preferred_runtimes=["all"])

    assert targets == [
        ("claude",    tmp_path / ".claude" / "skills"),
        ("openclaw",  tmp_path / ".openclaw" / "skills"),
        ("codex",     tmp_path / ".codex" / "skills"),
        ("opencode",  tmp_path / ".config" / "opencode" / "skills"),
        ("workbuddy", tmp_path / ".workbuddy" / "skills"),
        ("trae-cn",   tmp_path / ".trae-cn" / "skills"),
        ("agents",    tmp_path / ".agents" / "skills"),
        ("auwork",    tmp_path / ".auwork" / "1001" / "skills"),
    ]


def _make_auwork_dir(tmp_path: Path, *names: str) -> None:
    """在临时 home 下构造 ~/.auwork/{name}/ 目录，便于 AuWork 用例复用。"""
    for name in names:
        (tmp_path / ".auwork" / name).mkdir(parents=True, exist_ok=True)


def test_auwork_targets_expand_all_numeric_dirs(monkeypatch, tmp_path: Path):
    """Windows 下 ~/.auwork 多个纯数字目录应全部展开，并按名称排序。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    _make_auwork_dir(tmp_path, "1002", "1001")

    targets = SkillDetector()._auwork_targets()

    assert targets == [
        ("auwork", tmp_path / ".auwork" / "1001" / "skills"),
        ("auwork", tmp_path / ".auwork" / "1002" / "skills"),
    ]


def test_auwork_targets_ignore_non_numeric_dirs(monkeypatch, tmp_path: Path):
    """非纯数字命名的子目录应被过滤。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    _make_auwork_dir(tmp_path, "1001", "temp", ".cache", "user01")

    targets = SkillDetector()._auwork_targets()

    assert targets == [("auwork", tmp_path / ".auwork" / "1001" / "skills")]


def test_auwork_targets_empty_on_non_windows(monkeypatch, tmp_path: Path):
    """非 Windows 平台恒返回空列表，不影响 mac/linux。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "darwin")
    _make_auwork_dir(tmp_path, "1001")

    assert SkillDetector()._auwork_targets() == []


def test_auwork_targets_empty_when_no_numeric_dir(monkeypatch, tmp_path: Path):
    """~/.auwork 存在但无纯数字子目录时返回空（验证"跳过"语义）。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    _make_auwork_dir(tmp_path, "temp")

    assert SkillDetector()._auwork_targets() == []


def test_detect_install_targets_explicit_auwork_expands(monkeypatch, tmp_path: Path):
    """显式 --runtime auwork 应展开为全部纯数字目录目标。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    _make_auwork_dir(tmp_path, "1001", "1002")

    targets = SkillDetector().detect_install_targets(preferred_runtimes=["auwork"])

    assert targets == [
        ("auwork", tmp_path / ".auwork" / "1001" / "skills"),
        ("auwork", tmp_path / ".auwork" / "1002" / "skills"),
    ]


def test_detect_all_targets_include_auwork_on_windows(monkeypatch, tmp_path: Path):
    """--runtime all 在 Windows 上应包含 AuWork 目标。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    _make_auwork_dir(tmp_path, "1001")

    targets = SkillDetector().detect_all_install_targets()

    assert ("auwork", tmp_path / ".auwork" / "1001" / "skills") in targets


def test_discover_finds_auwork_skill(monkeypatch, tmp_path: Path):
    """安装到 AuWork 用户目录的 Skill 应被 discover 扫描到且 runtime=auwork。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    data_dir = tmp_path / ".auwork" / "1001" / "skills" / "ops-auth" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text('{"version":"v1.0.0"}', encoding="utf-8")

    records = SkillDetector().discover()
    auwork_records = [r for r in records if "auwork" in str(r.root).lower()]

    assert len(auwork_records) == 1
    assert auwork_records[0].name == "ops-auth"
    assert auwork_records[0].runtime == "auwork"
