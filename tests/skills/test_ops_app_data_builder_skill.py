"""OPS 应用数据层构建 Skill 模板契约测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from opscli.skills.manager import SkillsManager
from opscli.skills.packaging import selected_skill_names, validate_release_manifest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "opscli" / "skills" / "templates"
SKILL_NAME = "ops-app-data-builder"
SKILL_DIR = TEMPLATES_DIR / SKILL_NAME
SKILL_MD = SKILL_DIR / "SKILL.md"
VERSION_FILE = SKILL_DIR / "data" / "VERSION.json"
CONTRACT_FILE = SKILL_DIR / "references" / "data-layer-contract.md"
ROUTING_FILE = SKILL_DIR / "references" / "runtime-source-routing.md"
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


def test_ops_app_data_builder_metadata_is_consistent():
    """模板名称、版本、UI 元数据和引用文件必须完整一致。"""
    frontmatter = _frontmatter()
    version = json.loads(VERSION_FILE.read_text(encoding="utf-8"))

    assert frontmatter["name"] == SKILL_NAME
    assert frontmatter["metadata"]["version"] == "0.1.0"
    assert version == {"name": SKILL_NAME, "version": "v0.1.0"}
    assert (SKILL_DIR / "agents" / "openai.yaml").exists()
    assert CONTRACT_FILE.exists()
    assert ROUTING_FILE.exists()


def test_ops_app_data_builder_has_narrow_project_scope():
    """Skill 只处理标准站点数据层，不接管临时查询、普通页面或 Dashboard。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    for required in (
        "当前工作对象是通过 opscli app 创建或符合 `ops-app-build-spec` 的站点",
        "只需要一次临时查询或导出",
        "只搭建静态页面、交互或样式",
        "只分析一次真实数据结果，不修改站点",
        "创建、修改或分析当前 Dashboard 页面",
        "不要为了触发本 Skill，把单次查询扩展成站点数据工程任务",
    ):
        assert required in text

    for forbidden in (
        "dashboard_session_get_context(",
        "dashboard_editor_",
        "dashboard-tools.v2",
    ):
        assert forbidden not in text


def test_ops_app_data_builder_routes_contract_validation_to_existing_skills():
    """数据集、字段和第三方场景必须由现有查询 Skill 验证。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    for required in (
        "$ops-dataset-query",
        "$ops-query-wizard",
        "$ops-keepa",
        "$ops-seller-sprite",
        "不凭记忆选择数据集、字段、聚合、公式、筛选枚举或第三方场景参数",
        "只获取足以验证合同的少量样本",
    ):
        assert required in text


def test_ops_app_data_builder_defines_safe_runtime_source_routing():
    """OPS、Keepa 和 SellerSprite 必须使用各自真实且受支持的运行时边界。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    routing = ROUTING_FILE.read_text(encoding="utf-8")
    content = "\n".join((skill, routing))

    for required in (
        "viewer-live",
        "x-ops-token",
        "不得仅根据名称生成未经验证的导入和方法调用",
        "OPSCLI_API_BASE_URL",
        "OPSCLI_API_KEY",
        "/api/v1/keepa/scenarios",
        "/api/v1/keepa/run",
        "正式文档只声明 Keepa scenarios 和 run",
        "默认状态为 `blocked` 或 `mock-only`",
        "不修改 `opscli/app/sdk`",
        "不伪造不存在的 SDK 类、导入路径、REST 端点、轮询端点或认证协议",
    ):
        assert required in content


def test_ops_app_data_builder_defines_data_layer_and_sqlite_outputs():
    """Skill 必须交付可审查的数据规范、前后端分层、迁移和测试。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    content = "\n".join((skill, contract))

    for required in (
        "docs/ops-app/data-spec.md",
        "backend/app/clients/",
        "backend/app/services/",
        "backend/app/repositories/",
        "backend/app/schemas/",
        "frontend/src/api/",
        "frontend/src/types/",
        "网络请求在数据库事务外完成",
        "未按用户隔离的 OPS viewer 结果",
        "第一阶段只生成 Markdown 规范，不新增运行时 YAML",
        "Pydantic Schema 与前端类型的一致性",
    ):
        assert required in content


def test_ops_app_data_builder_contract_example_is_valid_json():
    """数据产品合同示例必须可解析并表达来源、模式和存储边界。"""
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    example = _first_json_example(contract)

    assert example["product_key"] == "inventory_risk"
    assert example["source"] == "ops"
    assert example["execution_mode"] == "viewer-live"
    assert example["site_api"].startswith("GET /api/")
    assert example["storage"] is None


def test_ops_app_data_builder_is_discoverable_installable_and_declared(tmp_path: Path):
    """通用 SkillsManager 和发行清单应完整支持新模板。"""
    problems = validate_release_manifest(TEMPLATES_DIR)
    assert not any(SKILL_NAME in problem for problem in problems)

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
    )
    templates = {item["name"]: item for item in manager.list_templates()}

    assert templates[SKILL_NAME]["version"] == "v0.1.0"
    assert "ops-business-data-orchestrator" not in templates

    result = manager.install(SKILL_NAME, skills_dir=str(tmp_path / "skills"))
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])

    for relative in (
        "SKILL.md",
        "data/VERSION.json",
        "agents/openai.yaml",
        "references/data-layer-contract.md",
        "references/runtime-source-routing.md",
    ):
        assert (installed_path / relative).exists()

    assert not any(
        "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
        for path in installed_path.rglob("*")
    )


def test_ops_app_data_builder_follows_release_profile_matrix():
    """内部建站 Skill 应进入源码、wheel 和两类二进制产物。"""
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
    assert "ops-business-data-orchestrator" not in manifest["skills"]


def test_ops_app_data_builder_does_not_embed_sensitive_or_local_values():
    """模板不得携带真实身份字段、凭证值、真实地址或本机路径。"""
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SKILL_DIR.rglob("*")
        if path.suffix in {".md", ".yaml", ".json"}
    )

    for forbidden in (
        "userEmail",
        "query.from.table",
        "query.from.permission",
        "http://",
        "https://",
        "Administrator",
        "/Users/",
        "Bearer ey",
    ):
        assert forbidden not in content
