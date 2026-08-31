"""业务取数编排 Skill 模板契约测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from opscli.skills.manager import SkillsManager
from opscli.skills.packaging import selected_skill_names


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "opscli" / "skills" / "templates"
SKILL_NAME = "ops-business-data-orchestrator"
SKILL_DIR = TEMPLATES_DIR / SKILL_NAME
SKILL_MD = SKILL_DIR / "SKILL.md"
VERSION_FILE = SKILL_DIR / "data" / "VERSION.json"
CONTRACT_FILE = SKILL_DIR / "references" / "orchestration-contract.md"
MANIFEST_FILE = TEMPLATES_DIR / "manifest.json"


def _frontmatter() -> dict:
    """读取 SKILL.md 的 YAML frontmatter。"""
    content = SKILL_MD.read_text(encoding="utf-8")
    return yaml.safe_load(content.split("---", 2)[1])


def _first_json_example(text: str) -> dict:
    """解析文档中的第一个 JSON 代码块。"""
    match = re.search(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


def test_business_data_orchestrator_metadata_is_consistent():
    """模板名称、版本、UI 元数据和引用文件必须完整一致。"""
    frontmatter = _frontmatter()
    version = json.loads(VERSION_FILE.read_text(encoding="utf-8"))

    assert frontmatter["name"] == SKILL_NAME
    assert frontmatter["version"] == "0.0.1"
    assert version == {"name": SKILL_NAME, "version": "v0.0.1"}
    assert (SKILL_DIR / "agents" / "openai.yaml").exists()
    assert CONTRACT_FILE.exists()


def test_business_data_orchestrator_keeps_codex_only_scope():
    """新 Skill 只负责编排 Codex 复合取数，不接管 Dashboard 页面能力。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    for required in (
        "当前运行环境是 Codex",
        "不要求存在 Dashboard 页面上下文",
        "不读取、分析、创建或修改当前看板",
        "用户要求创建、修改或删除当前看板图表",
        "用户要求分析当前已绑定仪表盘",
        "为看板准备数据",
    ):
        assert required in text

    for forbidden in (
        "dashboard_editor_",
        "dashboard_session_get_context(",
        "dashboard-tools.v2",
    ):
        assert forbidden not in text


def test_business_data_orchestrator_routes_without_copying_query_rules():
    """单查询、复合需求和纠错必须路由到正确的现有 Skill。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "单个查询且信息完整：直接使用 `$ops-dataset-query`" in text
    assert "单个查询但关键范围、指标或维度不清晰：直接使用 `$ops-query-wizard`" in text
    assert "仅将对应问题及其查询上下文交给 `$ops-query-wizard` 纠错" in text
    assert "不得为了触发本 Skill，把一个单查询人为拆成多个问题" in text
    assert "不直接调用 `opscli query`" in text
    assert "不选择或猜测数据集、字段、聚合、公式、筛选值和查询参数" in text


def test_business_data_orchestrator_preserves_partial_results_and_stops():
    """部分失败时保留成功结果，回答原始目标后停止扩展。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "保留已成功的问题结果" in text
    assert "只纠正该问题；其他成功结果保持不变" in text
    assert "完成原始业务目标后立即停止" in text
    assert "没有真实查询结果时，不生成数值、结论或伪造的结果摘要" in text


def test_business_data_orchestrator_contract_example_is_valid_json():
    """编排契约中的任务结构必须是可解析的有效 JSON。"""
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    example = _first_json_example(contract)

    assert example["business_goal"]
    assert example["questions"][0]["question_key"] == "inventory_overview"
    assert example["questions"][0]["status"] == "pending"
    assert "Dashboard 页面 ID" in contract


def test_business_data_orchestrator_is_discoverable_and_installable(tmp_path: Path):
    """通用 SkillsManager 应能发现并完整安装新模板。"""
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
    )
    templates = {item["name"]: item for item in manager.list_templates()}

    assert templates[SKILL_NAME]["version"] == "v0.0.1"
    result = manager.install(SKILL_NAME, skills_dir=str(tmp_path / "skills"))
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])

    for relative in (
        "SKILL.md",
        "data/VERSION.json",
        "agents/openai.yaml",
        "references/orchestration-contract.md",
    ):
        assert (installed_path / relative).exists()

    assert not any(
        "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
        for path in installed_path.rglob("*")
    )


def test_business_data_orchestrator_follows_release_profile_matrix():
    """内部 Codex Skill 应进入源码、wheel 和两类二进制产物。"""
    profile_artifacts = (
        ("python-release", "sdist"),
        ("python-release", "wheel"),
        ("binary-minimal", "binary"),
        ("binary-full", "binary"),
    )

    for profile, artifact in profile_artifacts:
        assert SKILL_NAME in selected_skill_names(
            profile=profile,
            artifact=artifact,
            templates_dir=TEMPLATES_DIR,
        )

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    entry = manifest["skills"][SKILL_NAME]
    assert entry["tier"] == "internal"
    assert all(entry[key] for key in ("source", "wheel", "binary", "binary_full"))


def test_business_data_orchestrator_does_not_embed_sensitive_or_local_values():
    """模板不得携带凭证、真实页面标识、网络客户端或本机路径。"""
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SKILL_DIR.rglob("*")
        if path.suffix in {".md", ".yaml", ".json"}
    )

    for forbidden in (
        "userEmail",
        "query.from.table",
        "query.from.permission",
        "Authorization:",
        "http://",
        "https://",
        "Administrator",
        "/Users/",
    ):
        assert forbidden not in content
