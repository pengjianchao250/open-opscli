"""西柚 Skill 的入口合同、版本与安装资源校验。"""

import json
import re
from pathlib import Path

from opscli.skills.services.manager import SkillsManager


SKILL_DIR = Path("opscli/skills/templates/ops-xiyou")
SKILL_PATH = SKILL_DIR / "SKILL.md"
VERSION_PATH = SKILL_DIR / "data" / "VERSION.json"
MANIFEST_PATH = Path("opscli/skills/templates/manifest.json")


def test_ops_xiyou_template_identity_is_consistent():
    text = SKILL_PATH.read_text(encoding="utf-8")
    version = json.loads(VERSION_PATH.read_text(encoding="utf-8"))

    assert text.startswith("---\nname: ops-xiyou\n")
    assert f"mcp-version: {version['version']}" in text
    assert version == {"name": "ops-xiyou", "version": "v2.0.1"}


def test_ops_xiyou_requires_explicit_trigger_and_discloses_credit():
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "只有满足以下任一条件才调用西柚查询工具" in text
    assert "普通 Amazon" in text
    assert "不得自动路由到西柚" in text
    assert "消耗西柚 Credit" in text
    assert "xydc_openapi" in text
    assert "旧 xydc MCP" in text


def test_ops_xiyou_covers_only_registered_openapi_tools():
    """Skill 中公开工具引用必须与实际注册集合一致。"""
    from opscli.mcp.tools.xydc import _ALL_TOOLS

    text = SKILL_PATH.read_text(encoding="utf-8")
    assert set(re.findall(r"ext_xydc_[a-z_]+", text)) == {tool.__name__ for tool in _ALL_TOOLS}
    assert "source=xydc_openapi" in text
    assert "cost_credits" in text


def test_ops_xiyou_documents_provider_rotation_and_retry_boundary():
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "额度账户不可用" in text
    assert "API Key" in text
    assert "切换下一个 `xydc_openapi` MySQL 账号" in text
    assert "禁止自动重放相同参数" in text
    assert "空数组、0 流量、0 排名结果" in text


def test_ops_xiyou_is_released_as_experimental():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    config = manifest["skills"]["ops-xiyou"]

    assert config["tier"] == "experimental"
    assert all(
        config[key] is True
        for key in ("source", "wheel", "binary", "binary_full")
    )
    assert "西柚 OpenAPI v2" in config["reason"]


def test_ops_xiyou_can_be_installed_from_builtin_templates(tmp_path: Path):
    manager = SkillsManager(registry_path=tmp_path / "registry.json")

    result = manager.install(
        "ops-xiyou",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    installed_dir = tmp_path / "skills" / "ops-xiyou"
    assert result.name == "ops-xiyou"
    assert result.to_dict()["version"] == "v2.0.1"
    assert (installed_dir / "SKILL.md").exists()
    assert json.loads(
        (installed_dir / "data" / "VERSION.json").read_text(encoding="utf-8")
    ) == {"name": "ops-xiyou", "version": "v2.0.1"}
    for filename in ("趋势参数与可用日期.md", "接口参数与返回口径.md", "历史订单与类目排名.md"):
        reference = Path("references") / filename
        assert (installed_dir / reference).read_bytes() == (SKILL_DIR / reference).read_bytes()
