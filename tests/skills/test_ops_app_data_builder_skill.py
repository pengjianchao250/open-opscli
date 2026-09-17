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
APPLICATION_GUIDE_FILE = SKILL_DIR / "references" / "ops-dataset-application-guide.md"
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
    assert frontmatter["metadata"]["version"] == "0.1.18"
    assert version == {"name": SKILL_NAME, "version": "v0.1.19"}
    assert (SKILL_DIR / "agents" / "openai.yaml").exists()
    assert CONTRACT_FILE.exists()
    assert ROUTING_FILE.exists()
    assert APPLICATION_GUIDE_FILE.exists()


def test_ops_app_data_builder_has_narrow_project_scope():
    """Skill 只处理标准站点数据层，并按能力与对象识别 Dashboard 平台任务。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    for required in (
        "当前工作对象来自标准模板，并已通过 `opscli app create/init` 完成 AppHub 应用和 Git 仓库绑定",
        "只需要一次临时查询或导出",
        "只搭建静态页面、交互或样式",
        "只分析一次真实数据结果，不修改站点",
        "dashboard_session_get_context",
        "dashboard-tools.v2",
        "普通 AppHub 仓库中的看板页面",
        "URL、路由名、页面标题",
        "不要为了触发本 Skill，把单次查询扩展成站点数据工程任务",
    ):
        assert required in text

    for forbidden in (
        "dashboard_editor_",
    ):
        assert forbidden not in text


def test_ops_app_data_builder_requires_standard_template_and_project_identity():
    """数据层生成前必须完成标准模板初始化并校验 binding。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    for required in (
        "### 0. 模板初始化门禁",
        ".opscli/app.json",
        "binding 必须包含有效 `app_id/slug`",
        ".opscli/app.json.app_id == app.yaml.app_id",
        "当前本地分支是 `master`（允许尚无首次提交的 unborn branch）",
        "`origin/master` 存在时可作为远端基线",
        "仅缺少 `origin/master` 不是阻塞条件",
        "首次提交与推送属于源码交付阶段",
        "不得要求用户先提交或推送后才开始数据层开发",
        "只有 binding 而没有模板代码",
        "backend/clients/ops_query_client.py",
        "backend/core/auth.py",
        "backend/services/query_service.py",
        "backend/api/v1/query.py",
        "不兼容旧数据层结构",
        "本 Skill 不自行拉取模板、不兼容旧数据层结构，也不生成替代脚手架",
        "$ops-app-build-spec",
    ):
        assert required in text

    for forbidden in (
        "符合 `ops-app-build-spec` 的已有项目",
        "已有结构不同则复用现有命名",
        "且远端存在 `origin/master`",
        "缺少 `origin/master`，或项目身份不一致",
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


def test_ops_app_data_builder_updates_migration_coverage_matrix() -> None:
    """迁移数据层必须读取动态模块、回写合同证据并通过数据门禁。"""
    text = SKILL_MD.read_text(encoding="utf-8")

    for required in (
        ".opscli/migration/current.json",
        "coverage-matrix.json",
        "dynamic=true",
        "opscli app migrate verify-ui",
        "当前迁移阶段至少是 `data_integration`",
        "data_contract",
        "candidate`、`verified`、`degraded`、`blocked`、`deferred_attachment`",
        "FakeGateway 测试和线上真实查询必须分别记录",
        "unblock_conditions",
        "implementation_status",
        "contract_verified_only",
        "layout_only",
        "全部未阻塞动态项",
        "opscli app migrate export",
        "opscli app migrate verify-data",
    ):
        assert required in text


def test_ops_app_data_builder_requires_real_query_closure() -> None:
    """清晰的真实数据需求必须查询、留证并通过交付校验。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    guide = APPLICATION_GUIDE_FILE.read_text(encoding="utf-8")
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    content = "\n".join((skill, guide, contract))

    for required in (
        "必须实际发起正式合同验证",
        "不得在没有查询尝试的情况下直接生成最终 `blocked` 页面",
        "`verifying`",
        "`degraded`",
        "查询成功但零行仍是 `verified`",
        "docs/ops-app/data-contracts.json",
        "scripts/validate_data_contracts.py",
        "--mode contract",
        "--mode delivery",
        "--project-root",
        "implementation_status=verified",
        "implementation_artifacts",
        "后端 API、service、Pydantic Schema、前端消费者、测试和 OpenAPI",
        "required_business_roles",
        "not_attempted",
        "not_validated",
        "service_error",
        "timeout",
    ):
        assert required in content

    validator = SKILL_DIR / "scripts" / "validate_data_contracts.py"
    assert validator.is_file()


def test_ops_app_data_builder_requires_exact_ops_field_contracts():
    """OPS 运行时代码必须使用已验证的精确字段合同并覆盖相似字段。"""
    content = "\n".join(
        (
            SKILL_MD.read_text(encoding="utf-8"),
            CONTRACT_FILE.read_text(encoding="utf-8"),
            APPLICATION_GUIDE_FILE.read_text(encoding="utf-8"),
        )
    )

    for required in (
        "精确 `dataset_alias`",
        "`table_id`",
        "精确 `field_name`",
        "`global_alias`",
        "关键词打分",
        "`includes`",
        "最相近字段",
        "`validate_fields=true`",
        "前端只调用站点业务 API",
        "asin/parent_asin",
        "order_qty/orders",
        "price/ads_sales_cny",
        "metadata 漂移",
    ):
        assert required in content


def test_ops_app_data_builder_separates_application_routing_from_query_execution():
    """应用层只判定取数模式和合同状态，查询事实仍来自在线元数据。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    guide = APPLICATION_GUIDE_FILE.read_text(encoding="utf-8")
    content = "\n".join((skill, guide))

    for required in (
        "one-off-query",
        "guided-query",
        "viewer-live",
        "viewer-private-persisted",
        "approved-system-sync",
        "reference-only",
        "candidate",
        "verified",
        "blocked",
        "当前在线元数据",
        "查询组件只用于",
        "确定性分页",
        "断点续传",
        "不生成伪实现",
    ):
        assert required in content

    for forbidden in (
        "ops-dataset-source-catalog.json",
        "ops-dataset-field-catalog.json",
        "运营系统数据集.xlsx",
    ):
        assert forbidden not in content


def test_ops_app_data_builder_defines_safe_runtime_source_routing():
    """OPS、Keepa 和 SellerSprite 必须使用各自真实且受支持的运行时边界。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    routing = ROUTING_FILE.read_text(encoding="utf-8")
    guide = APPLICATION_GUIDE_FILE.read_text(encoding="utf-8")
    content = "\n".join((skill, routing, guide))

    for required in (
        "viewer-live",
        "X-Ops-Token",
        "Depends(get_query_gateway)",
        "ViewerQueryGateway",
        "OpsQueryGateway",
        "LocalQueryGateway",
        "app.yaml",
        "opscli.datasets",
        "FakeGateway",
        "OPSCLI_MCP_REST_API_BASE_URL",
        "/api/v1/query/simple",
        "/api/v1/query/metadata",
        "QueryCredentials",
        "get_query_credentials",
        "X-User-Email",
        "X-Session-Id",
        'AuthClient.build_session_headers("ops")',
        'AuthClient.build_request_auth("ops")',
        "https://ops.mcp.xenkee.com",
        "https://mcp.ops.aukeyit.com",
        "纯根域名",
        "请求级 `ThirdPartyApiClient`",
        'base_url.rstrip("/") + path',
        "/api/v1/keepa/run",
        "页面运行时只调用 `POST /api/v1/keepa/run`",
        "/api/v1/seller-sprite/jobs",
        "/api/v1/seller-sprite/listing-analysis/jobs",
        "pending 任务不得重新提交",
        "third_party_async_job",
        "不生成或引用 `opscli.app.sdk.OpsClient`",
        "不兼容旧适配器",
        "不伪造不存在的 SDK 类、导入路径、REST 端点、轮询端点或认证协议",
        "经过批准的 OPS 系统运行时适配器",
        "不得保存或复用访问者 `X-Ops-Token`",
        "UNIQUE(owner_user_id, provider, request_hash)",
    ):
        assert required in content

    assert "OPSCLI_THIRD_PARTY_DATA_API_BASE_URL" not in content
    assert "OPSCLI_THIRD_PARTY_DATA_API_KEY" not in content
    assert "/api/v1/keepa/" + "scenarios" not in content
    assert "OPSCLI_" + "API_BASE_URL" not in content
    assert "OPSCLI_" + "API_KEY" not in content
    assert "OPSCLI_SELLER_SPRITE_" + "E2E_BASE_URL" not in content
    assert "OPSCLI_SELLER_SPRITE_" + "E2E_API_KEY" not in content
    assert "OPSCLI_KEEPA_BASE_URL" not in content
    assert "OPSCLI_SELLER_SPRITE_BASE_URL" not in content


def test_ops_app_data_builder_defines_data_layer_and_sqlite_outputs():
    """Skill 必须交付可审查的数据规范、前后端分层、迁移和测试。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    content = "\n".join((skill, contract))

    for required in (
        "docs/ops-app/data-spec.md",
        "backend/api/v1/",
        "backend/clients/",
        "backend/services/",
        "backend/repositories/",
        "backend/schemas/",
        "migrations/",
        "frontend/src/api/",
        "frontend/src/types/",
        "网络请求在数据库事务外完成",
        "未按用户隔离的 OPS viewer 结果",
        "owner_user_id",
        "third_party_source_snapshot",
        "third_party_async_job",
        "UNIQUE(owner_user_id, provider, request_hash)",
        "XLS/XLSX",
        "第一阶段只生成 Markdown 规范，不新增运行时 YAML",
        "Pydantic Schema 与前端类型的一致性",
        "extract_inner_error()",
        "data.inner_error.message",
        "LIMIT_TOO_LARGE",
        "不超过 `50000`",
    ):
        assert required in content


def test_ops_app_data_builder_requires_exact_third_party_projection_contracts():
    """第三方数据必须固化真实响应形状，并在快照前完成投影校验。"""
    skill = SKILL_MD.read_text(encoding="utf-8")
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    routing = ROUTING_FILE.read_text(encoding="utf-8")
    content = chr(10).join((skill, contract, routing))

    for required in (
        'schema_version: "1.1"',
        "response_shape",
        "shape_evidence",
        "required_business_roles",
        "source_field",
        "source_path",
        "result_field",
        "data_type",
        "validate_before_snapshot",
        "degraded_preserve_snapshot",
        "$.data.data[*]",
        "currentAmazonPrice",
        "currentSalesRank",
        "columns + rows",
        "不生成猜测的生产字段投影器",
    ):
        assert required in content


def test_ops_app_data_builder_contract_example_is_valid_json():
    """数据产品合同示例必须可解析并表达来源、模式和存储边界。"""
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    example = _first_json_example(contract)

    assert example["product_key"] == "seller_sprite_competitor_analysis"
    assert example["source"] == "seller_sprite"
    assert example["verification"]["shape_evidence"] == {
        "records_path": "$.data.result.rows[*]",
        "record_type": "array",
        "observed_fields": ["商品标题", "价格", "月销量"],
    }
    assert example["technical_contract"]["response_shape"] == {
        "records_path": "$.data.result.rows[*]",
        "record_type": "array",
        "columns_path": "$.data.result.columns",
    }
    assert example["technical_contract"]["projection_policy"] == {
        "validate_before_snapshot": True,
        "on_schema_mismatch": "degraded_preserve_snapshot",
    }
    assert example["execution_mode"] == "async-job"
    assert example["source_execution"]["auth"] == "query-credentials"
    assert example["source_execution"]["auth_modes"] == ["viewer", "session", "local"]
    assert example["source_execution"]["success_state"] == "succeeded"
    assert example["task_storage"]["table"] == "third_party_async_job"
    assert example["task_storage"]["active_states"] == ["queued", "running"]
    assert example["task_storage"]["owner_key"] == "owner_user_id"
    assert example["task_storage"]["unique_key"] == ["owner_user_id", "provider", "request_hash"]
    assert example["source_storage"]["storage_scope"] == "user-private"
    assert example["source_storage"]["owner_key"] == "owner_user_id"
    assert example["source_storage"]["unique_key"] == ["owner_user_id", "provider", "request_hash"]
    assert example["result_storage"]["owner_key"] == "owner_user_id"
    assert example["site_api"].startswith("GET /api/")


def test_ops_app_data_builder_requires_project_identity_for_runtime_preview():
    """数据层运行验收必须复用建站 Skill 的项目身份状态。"""
    content = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    for required in (
        "opscli app dev-status <project-root> --json",
        "running=true",
        "identity_verified=true",
        "单独 HTTP 200",
    ):
        assert required in content


def test_ops_app_data_builder_is_discoverable_installable_and_declared(tmp_path: Path):
    """通用 SkillsManager 和发行清单应完整支持新模板。"""
    problems = validate_release_manifest(TEMPLATES_DIR)
    assert not any(SKILL_NAME in problem for problem in problems)

    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
    )
    templates = {item["name"]: item for item in manager.list_templates()}

    assert templates[SKILL_NAME]["version"] == "v0.1.19"
    assert "ops-business-data-orchestrator" not in templates

    result = manager.install(SKILL_NAME, skills_dir=str(tmp_path / "skills"))
    installed_path = Path(result.to_dict()["installed_paths"][0]["path"])

    for relative in (
        "SKILL.md",
        "data/VERSION.json",
        "agents/openai.yaml",
        "references/data-layer-contract.md",
        "references/runtime-source-routing.md",
        "references/ops-dataset-application-guide.md",
        "scripts/validate_data_contracts.py",
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
    """模板不得携带真实身份字段、凭证值、未批准地址或本机路径。"""
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
        "Administrator",
        "/Users/",
        "Bearer ey",
    ):
        assert forbidden not in content

    urls = set(re.findall(r"https://[^\s`<>]+", content))
    assert urls
    allowed_origins = ("https://ops.mcp.xenkee.com", "https://mcp.ops.aukeyit.com")
    assert all(url.startswith(allowed_origins) for url in urls)
