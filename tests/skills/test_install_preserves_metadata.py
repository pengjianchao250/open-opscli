"""install 覆盖安装时保留运行时元数据的回归测试。

线上事故形态：`opscli skills install ops-dataset-query` 会把用户通过
`opscli skills upgrade` 从远端拉取的真实元数据（近 600KB、数千字段）
换成内置模板里的占位符（CSV 仅表头、JSON 空集合）。

触发面比 `--force` 更宽：模板版本与 upgrade 写入的数据版本属于两套版本空间、
永远不相等，`_template_version_differs()` 每次都为真，因此普通 install 同样会
走到 rmtree。次生后果是模板 VERSION.json 的 data_state=placeholder 覆盖过去后，
规划器的 _data_state_ready() 判定未就绪，整个 Skill 直接不可用。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.skills.services.manager import SkillsManager

# 真实元数据的最小可辨识形态：datasets.csv 含表头之外的数据行
_REAL_DATASETS_CSV = "table_id,dataset_alias,dataset_name\n1,ds_real,真实数据集\n"
_PLACEHOLDER_DATASETS_CSV = "table_id,dataset_alias,dataset_name\n"


def _make_template(root: Path, *, data_state: str = "placeholder") -> Path:
    """构造一个内置模板：data/ 为占位符，scripts/ 与 SKILL.md 为模板权威内容。"""
    template = root / "templates" / "ops-dataset-query"
    (template / "data").mkdir(parents=True)
    (template / "scripts").mkdir(parents=True)

    data = template / "data"
    (data / "datasets.csv").write_text(_PLACEHOLDER_DATASETS_CSV, encoding="utf-8")
    (data / "dataset_fields.csv").write_text("table_id,field_name\n", encoding="utf-8")
    (data / "query_metadata.json").write_text('{"datasets": [], "fields": []}', encoding="utf-8")
    (data / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "1.3.15", "data_state": data_state}),
        encoding="utf-8",
    )
    # 模板权威内容：新版本必须覆盖到安装目录
    (template / "scripts" / "query_plan.py").write_text("# 新版规划器\n", encoding="utf-8")
    (template / "SKILL.md").write_text("# ops-dataset-query\n", encoding="utf-8")
    return template


def _make_upgraded_install(target: Path) -> None:
    """构造一个已 upgrade 过的安装目录：data/ 持有真实元数据、旧版脚本。"""
    (target / "data").mkdir(parents=True)
    (target / "scripts").mkdir(parents=True)

    data = target / "data"
    (data / "datasets.csv").write_text(_REAL_DATASETS_CSV, encoding="utf-8")
    (data / "dataset_fields.csv").write_text("table_id,field_name\n1,real_field\n", encoding="utf-8")
    (data / "query_metadata.json").write_text('{"datasets": [{"id": 1}]}', encoding="utf-8")
    # upgrade 写入的 VERSION.json 只有 name+version，没有 data_state
    (data / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.1.23"}), encoding="utf-8"
    )
    (target / "scripts" / "query_plan.py").write_text("# 旧版规划器\n", encoding="utf-8")


def _make_manager(tmp_path: Path) -> SkillsManager:
    """构造隔离到 tmp_path 的 SkillsManager，不触碰真实 ~/.opscli 与注册表。

    templates_dir 是实例属性（默认取发行包内置模板目录），测试里改指向
    tmp_path 下的伪模板，以便控制 data_state 与占位符内容。
    """
    instance = SkillsManager(
        central_skills_dir=tmp_path / "central",
        registry_path=tmp_path / "installed_skills.json",
    )
    instance.templates_dir = tmp_path / "templates"
    return instance


@pytest.fixture
def manager(tmp_path: Path) -> SkillsManager:
    """默认场景：模板 data/ 为占位符（ops-dataset-query 的真实形态）。"""
    _make_template(tmp_path)
    return _make_manager(tmp_path)


def test_install_preserves_real_metadata(manager: SkillsManager, tmp_path: Path):
    """真实元数据必须存活（旧复制模式 --skills-dir）。"""
    target_root = tmp_path / "skills"
    target = target_root / "ops-dataset-query"
    _make_upgraded_install(target)

    result = manager.install("ops-dataset-query", skills_dir=str(target_root), force=True)

    data = target / "data"
    assert data.joinpath("datasets.csv").read_text(encoding="utf-8") == _REAL_DATASETS_CSV
    assert "real_field" in data.joinpath("dataset_fields.csv").read_text(encoding="utf-8")
    assert '"id": 1' in data.joinpath("query_metadata.json").read_text(encoding="utf-8")
    # VERSION.json 也必须保留：模板的 data_state=placeholder 覆盖过去会让规划器全量 blocked
    version = json.loads(data.joinpath("VERSION.json").read_text(encoding="utf-8"))
    assert version["version"] == "v1.1.23"
    assert "data_state" not in version
    assert result.installs[0].preserved_data_files == 4


def test_install_still_updates_template_owned_files(manager: SkillsManager, tmp_path: Path):
    """保留元数据不能顺带把模板权威内容也冻住：脚本必须更新到新版。"""
    target_root = tmp_path / "skills"
    target = target_root / "ops-dataset-query"
    _make_upgraded_install(target)

    manager.install("ops-dataset-query", skills_dir=str(target_root), force=True)

    assert "新版规划器" in (target / "scripts" / "query_plan.py").read_text(encoding="utf-8")


def test_placeholder_install_is_not_preserved(manager: SkillsManager, tmp_path: Path):
    """已有安装也只是占位符时无需保留，保持原有整体覆盖语义。"""
    target_root = tmp_path / "skills"
    target = target_root / "ops-dataset-query"
    (target / "data").mkdir(parents=True)
    (target / "data" / "datasets.csv").write_text(_PLACEHOLDER_DATASETS_CSV, encoding="utf-8")

    result = manager.install("ops-dataset-query", skills_dir=str(target_root), force=True)

    assert result.installs[0].preserved_data_files == 0


def test_template_with_ready_data_overwrites_install(tmp_path: Path):
    """模板声明 data_state=ready 时数据随包发布，必须覆盖而非保留旧数据。"""
    _make_template(tmp_path, data_state="ready")
    manager = _make_manager(tmp_path)
    target_root = tmp_path / "skills"
    target = target_root / "ops-dataset-query"
    _make_upgraded_install(target)

    result = manager.install("ops-dataset-query", skills_dir=str(target_root), force=True)

    assert (target / "data" / "datasets.csv").read_text(encoding="utf-8") == _PLACEHOLDER_DATASETS_CSV
    assert result.installs[0].preserved_data_files == 0


def test_central_install_preserves_real_metadata(manager: SkillsManager, tmp_path: Path):
    """中央存储模式（默认路径）同样必须保留——实际踩坑的就是这条路径。"""
    central = tmp_path / "central" / "ops-dataset-query"
    _make_upgraded_install(central)

    result = manager.install("ops-dataset-query", link_targets=[], cwd=tmp_path)

    assert (central / "data" / "datasets.csv").read_text(encoding="utf-8") == _REAL_DATASETS_CSV
    assert "新版规划器" in (central / "scripts" / "query_plan.py").read_text(encoding="utf-8")
    assert result.installs[0].preserved_data_files == 4
