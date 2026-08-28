import json
from pathlib import Path

from opscli.skills.services.manager import SkillsManager


SKILL_DIR = Path("opscli/skills/templates/ops-yingyan")
SKILL_PATH = SKILL_DIR / "SKILL.md"
VERSION_PATH = SKILL_DIR / "data" / "VERSION.json"
MANIFEST_PATH = Path("opscli/skills/templates/manifest.json")


def test_ops_yingyan_template_identity_is_consistent():
    """目录、frontmatter 和版本文件必须使用同一个 Skill 名称。"""
    text = SKILL_PATH.read_text(encoding="utf-8")
    version = json.loads(VERSION_PATH.read_text(encoding="utf-8"))

    assert text.startswith("---\nname: ops-yingyan\n")
    assert version == {"name": "ops-yingyan", "version": "v1.0.0"}


def test_ops_yingyan_requires_explicit_user_trigger():
    """普通 Amazon 分析不得因为存在鹰眼数据就自动触发。"""
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "仅当用户明确提到“鹰眼”或“PND”" in text
    assert "普通 Amazon" in text
    assert "不得自动路由" in text
    assert "不要主动建议改用鹰眼" in text


def test_ops_yingyan_covers_all_approved_mcp_tools():
    """Skill 只能编排当前配置已审批暴露的四个鹰眼 Tool。"""
    text = SKILL_PATH.read_text(encoding="utf-8")

    expected_tools = {
        "ext_pnd_list_available_datasets",
        "ext_pnd_execute_readonly_sql",
        "ext_pnd_search_similar_terms",
        "ext_pnd_get_report_task_status",
    }
    assert expected_tools == {name for name in expected_tools if name in text}


def test_ops_yingyan_guards_against_broad_or_replayed_sql():
    """目录校验、窄查询和超时停止条件属于稳定行为合同。"""
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "先目录、后 SQL" in text
    assert "index_hints" in text
    assert "禁止 `SELECT *`" in text
    assert "全表 `COUNT(*)`" in text
    assert "前导通配符" in text
    assert "总截止时间为 30 秒" in text
    assert "禁止自动重放相同 Tool 参数或相同 SQL" in text
    assert "0 行不自动放宽" in text


def test_ops_yingyan_is_released_with_packaged_cli():
    """打包版 MCP 已代理鹰眼后，Skill 必须进入所有正式发行产物。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    config = manifest["skills"]["ops-yingyan"]

    assert config["tier"] == "internal"
    assert all(
        config[key] is True
        for key in ("source", "wheel", "binary", "binary_full")
    )
    assert "明确提到鹰眼或 PND" in config["reason"]


def test_ops_yingyan_can_be_installed_from_builtin_templates(tmp_path: Path):
    """内置模板必须能通过正式 SkillsManager 安装到目标目录。"""
    manager = SkillsManager(registry_path=tmp_path / "registry.json")

    result = manager.install(
        "ops-yingyan",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    installed_dir = tmp_path / "skills" / "ops-yingyan"
    assert result.name == "ops-yingyan"
    assert result.to_dict()["version"] == "v1.0.0"
    assert (installed_dir / "SKILL.md").exists()
    assert json.loads(
        (installed_dir / "data" / "VERSION.json").read_text(encoding="utf-8")
    ) == {"name": "ops-yingyan", "version": "v1.0.0"}
