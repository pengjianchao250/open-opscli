"""OPS 应用模板开发 Skill 契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.skills.packaging import validate_release_manifest
from opscli.skills.services.manager import SkillsManager


ROOT = Path(__file__).parents[2]
SKILL_DIR = ROOT / "opscli" / "skills" / "templates" / "ops-app-build-spec"


def _read(relative_path: str) -> str:
    """按 UTF-8 读取 Skill 文件。"""
    return (SKILL_DIR / relative_path).read_text(encoding="utf-8")


def test_ops_app_build_spec_has_consistent_scope():
    """Skill 只携带动态规范，不再打包项目资产。"""
    skill = _read("SKILL.md")
    version = json.loads(_read("data/VERSION.json"))
    files = sorted(path.relative_to(SKILL_DIR).as_posix() for path in SKILL_DIR.rglob("*") if path.is_file())

    assert "name: ops-app-build-spec" in skill.split("---", 2)[1]
    assert version == {"name": "ops-app-build-spec", "version": "v0.0.4"}


def test_ops_app_build_spec_routes_real_data_work_to_data_builder():
    """真实业务数据需求必须进入独立规范和数据层构建 Skill。"""
    skill = _read("SKILL.md")
    standard = _read("references/data-access-standard.md")
    content = "\n".join((skill, standard))

    for required in (
        "references/data-access-standard.md",
        "references/deployment-standard.md",
        "references/frontend-standard.md",
        "references/migration-standard.md",
    ]
    assert not (SKILL_DIR / "assets").exists()


def test_ops_app_build_spec_clones_and_recognizes_the_template():
    """新项目克隆模板，已绑定业务远端的项目按合同识别。"""
    skill = _read("SKILL.md")

    for required in (
        "http://10.1.13.143:3000/aukeys-admin/template",
        "git clone --branch main --single-branch",
        "不能只根据 remote 判断",
        "app.yaml",
        "backend/app.py",
        "合同缺失时读取迁移规范",
    ):
        assert required in skill

    assert "create-vue" not in skill
    assert "assets/app.yaml" not in skill


def test_ops_app_build_spec_separates_template_and_release_updated_rules():
    """项目实现规则归模板，动态限制归当前 Skill。"""
    skill = _read("SKILL.md")

    for required in (
        "模板项目负责目录结构、具体开发命令、依赖版本、数据库实现和本地运行说明",
        "当前 Skill 负责跨项目最低开发规范",
        "前后端底线、取数、凭证、安全、AppHub 平台和源码交付限制以当前 Skill 为准",
        "前后端参考只保留跨项目强制规则",
        "references/frontend-standard.md",
        "references/backend-standard.md",
    ):
        assert required in skill

    assert "references/initialization-standard.md" not in skill


def test_ops_app_build_spec_keeps_concise_frontend_rules():
    """前端只保留模板之上的跨项目底线。"""
    frontend = _read("references/frontend-standard.md")

    for required in (
        "Vue 3、Vite、Element Plus、Axios、Pinia 和 Vue Router",
        "功能图标不得用 emoji 代替",
        "loading、空数据、失败和成功状态",
        "pending/disabled 防重复机制",
        "浏览器只使用相对 URL",
        "HTTP 200 仍可能是业务失败",
        "前端不得保存密钥、JWT、Cookie",
        "data-access-standard.md",
    ):
        assert required in frontend


def test_ops_app_build_spec_keeps_concise_backend_rules():
    """后端只保留模板之上的跨项目底线。"""
    backend = _read("references/backend-standard.md")

    for required in (
        "backend/app.py",
        "路由只处理鉴权、参数校验和协议转换",
        "response_model",
        "无权限和资源不存在统一返回 404",
        "列表接口必须分页并显式排序",
        "async 路径不得直接执行阻塞 IO",
        "service 只 `flush`",
        "数据库迁移步骤只按目标项目文档执行",
    ):
        assert required in backend


def test_ops_app_build_spec_keeps_data_access_constraints():
    """真实取数限制必须保留并随 opscli 发版更新。"""
    skill = _read("SKILL.md")
    data_access = _read("references/data-access-standard.md")
    content = skill + data_access

    for required in (
        "$ops-app-data-builder",
        "前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite",
        "前端不得持有 API Key、JWT、Cookie",
        "不选择或猜测数据集、字段、聚合、筛选",
        "默认按访问者实时取数",
        "Mock、测试替身和本地回退不得被描述成线上真实接入",
    ):
        assert required in content


def test_ops_app_build_spec_keeps_only_generic_migration_rules():
    """迁移保留通用流程，不复制数据库实现细节。"""
    migration = _read("references/migration-standard.md")

    for required in (
        "先判断现有项目是否已满足模板合同",
        "保留源项目",
        "只迁移业务代码与必要配置",
        "取数能力按当前 `data-access-standard.md` 重新核对",
        "无法确认行为等价时停止",
    ):
        assert required in migration

    for duplicated_detail in ("alembic upgrade head", "migrations/versions", "data/app.db"):
        assert duplicated_detail not in migration


def test_ops_app_build_spec_enforces_template_first_initialization():
    """全新项目必须先创建和拉取模板，再允许 Skill 写入项目文件。"""
    initialization = _read("references/initialization-standard.md")
    skill = _read("SKILL.md")

    for intent in ("新建站点", "新建看板", "从零开发运营数据应用"):
        assert intent in skill

    for required in (
        "模板先行初始化规范",
        'opscli app create "<站点显示名称>" --path <项目根目录>',
        "opscli app init <项目根目录>",
        "template_applied=true",
        "模板是唯一基线",
        "不得提前写入 `assessment.md`",
        "不运行 `pnpm create vue`",
        ".opscli/app.json.app_id",
        ".opscli/app.json.slug",
        "ops-app.config.appId",
        "ops-app.config.appName",
        "模板缺少 `ops-app.config`",
        "已有项目边界",
    ):
        assert required in initialization

    assert "references/initialization-standard.md" in skill
    assert "### 0. 新项目模板门禁" in skill
    assert "本 Skill 作为统一建站入口" in skill
    assert "template_applied=true" in skill
    assert "不进入后续写文件步骤" in skill
    assert "pnpm create vue@latest frontend" not in initialization


def test_ops_app_build_spec_keeps_app_id_and_deployment_gates():
    """首次发布、路径和 Compose 产物必须形成同一合同。"""
    skill = _read("SKILL.md")
    frontend = _read("references/frontend-standard.md")
    deployment = _read("references/deployment-standard.md")
    content = "\n".join((skill, frontend, deployment))

    for required in (
        "ops-app.config",
        '"appId": null',
        "/ops-app/{appId}/{appName}/",
        "deployment/Dockerfile",
        "deployment/compose.yaml",
        "deployment/nginx.conf.template",
        "deployment/ops-app-config.mjs",
        "deployment/render-nginx-config.mjs",
        "frontend-runtime",
        "backend-runtime",
        "精确 `COPY` 分层",
        "BuildKit 缓存",
        "Dockerfile 不声明 `VOLUME`",
        "Nginx 以非 root 用户监听 `8080`",
        "根目录 `.dockerignore`",
        "docker compose -f deployment/compose.yaml config",
        "SQLite 使用持久卷",
    ):
        assert required in content

    assert "URL 安全单路径段" in content
    assert "禁止 `/`" in content
    assert ".opscli/app.json.app_id" in content
    assert ".opscli/app.json.slug" in content
    assert "不在首次发布阶段重新注册应用" in content
    assert "opscli app push <root> --message <summary>" in content
    assert "不启动容器" in content
    assert "全新 opscli app 必须在模板项目上改造" in content


def test_ops_app_build_spec_provides_required_nginx_template():
    """项目内 Nginx 必须使用固定路径、回退和缓存合同。"""
    template = _read("assets/nginx.conf.template")
    deployment = _read("references/deployment-standard.md")

    for required in (
        "apiVersion: apps.aukeys/v1",
        'python: "3.12"',
        "uvicorn backend.app:app --host 0.0.0.0 --port 8000",
        "opscli app create",
        "opscli app init",
        "opscli app push",
        "整体暂存当前项目改动",
        "业务代码推回统一模板仓库",
        "push 成功只表示源码到达远端",
        "不得报告“部署成功”",
        "ops-feedback",
    ):
        assert required in deployment

    assert "python -m opscli.app.migrate" not in deployment
    assert "nginx.conf.template" not in deployment


def test_ops_app_build_spec_is_declared_and_installable(tmp_path: Path):
    """精简后的动态规范必须通过正式安装流程。"""
    problems = validate_release_manifest(ROOT / "opscli" / "skills" / "templates")
    assert not any("ops-app-build-spec" in problem for problem in problems)

    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    templates = {item["name"]: item for item in manager.list_templates()}
    assert templates["ops-app-build-spec"]["version"] == "v0.0.4"

    result = manager.install("ops-app-build-spec", skills_dir=str(tmp_path / "skills"))
    installed = Path(result.to_dict()["installed_paths"][0]["path"])
    assert (installed / "SKILL.md").exists()
    assert (installed / "references" / "frontend-standard.md").exists()
    assert (installed / "references" / "initialization-standard.md").exists()
    assert (installed / "references" / "backend-standard.md").exists()
    assert (installed / "references" / "data-access-standard.md").exists()
    assert (installed / "references" / "migration-standard.md").exists()
    assert (installed / "references" / "deployment-standard.md").exists()
    assert (installed / "assets" / "nginx.conf.template").exists()
    assert (installed / "assets" / ".dockerignore").exists()
    assert (installed / "assets" / "ops-app.config").exists()
    assert (installed / "assets" / "ops-app-config.mjs").exists()
    assert (installed / "assets" / "ops-app-config.d.mts").exists()
    assert (installed / "assets" / "render-nginx-config.mjs").exists()
    assert (installed / "references" / "sqlite-standard.md").exists()
    assert (installed / "references" / "backend-redlines.md").exists()
    assert (installed / "references" / "opscli-integration-standard.md").exists()
    assert (installed / "assets" / "backend" / "AGENTS.md").exists()
    assert (installed / "assets" / "backend" / "CLAUDE.md").exists()
    assert len(list((installed / "assets" / "backend" / "docs" / "开发指南").glob("*.md"))) == 6


BACKEND_DOCS = (
    "FastAPI后端开发通用规范.md",
    "SQLite数据库使用通用规范.md",
    "OPSCLI_SDK调用规范.md",
    "OPSCLI_SDK使用文档.md",
    "OPSCLI_API调用规范.md",
    "OPSCLI_API使用文档.md",
)


def test_ops_app_build_spec_backend_references_follow_spec_contracts():
    """后端 references 必须保持 AppHub 运行合同，并正确指向补充规范文档。"""
    backend = _read("references/backend-standard.md")
    sqlite = _read("references/sqlite-standard.md")
    redlines = _read("references/backend-redlines.md")
    integration = _read("references/opscli-integration-standard.md")
    skill = _read("SKILL.md")

    # AppHub 运行合同：单进程托管、平台健康路由、APP_DB_PATH、requirements.txt
    for required in (
        "backend/app.py",
        "/__apphub_healthz",
        "APP_DB_PATH",
        "requirements.txt",
        "sqlite-standard.md",
        "opscli-integration-standard.md",
        "backend-redlines.md",
        "assets/backend/",
    ):
        assert required in backend, required
    # 补充文档与 AppHub 合同冲突时必须声明以 backend/deployment 规范为准
    assert "以本文与 `deployment-standard.md` 为准" in backend

    for required in (
        "journal_mode",
        "foreign_keys",
        "busy_timeout",
        "BEGIN IMMEDIATE",
        "sqlite+aiosqlite",
        "NullPool",
        "render_as_batch",
        "VACUUM INTO",
        "backup(",
        "INTEGER",
        "只能有一个写事务",
    ):
        assert required in sqlite, required

    assert "唯一入口" in redlines
    assert "--autogenerate" in redlines
    assert "alembic_version" in redlines
    assert "polarisUserToken" in integration
    assert "X-Session-Id" in integration
    assert "get_me(session_id=" in integration
    assert "set_explicit_credentials" in integration
    assert "userEmail" in integration

    for reference in (
        "references/sqlite-standard.md",
        "references/backend-redlines.md",
        "references/opscli-integration-standard.md",
    ):
        assert reference in skill
    assert "`assets/backend/`" in skill
    assert "以 `backend-standard.md` 与 `deployment-standard.md` 为准" in skill


def test_ops_app_build_spec_backend_templates_are_filled_or_marked():
    """AGENTS 模板路径必须已固定，CLAUDE 模板只保留项目特化占位符。"""
    agents = _read("assets/backend/AGENTS.md")
    claude = _read("assets/backend/CLAUDE.md")

    assert "〈" not in agents
    for doc in BACKEND_DOCS:
        assert f"docs/开发指南/{doc}" in agents, doc
    assert "docs/API规范/openapi.json" in agents

    assert "loguru" not in claude
    assert "backend/" in claude
    assert "uv run uvicorn app.main:app" in claude
    assert "sqlite+aiosqlite" in claude
    assert "BEGIN IMMEDIATE" in claude
    assert "render_as_batch" in claude
    assert "### 4.8 opscli 接入" in claude
    assert "polarisUserToken" in claude
    assert "docs/CHANGELOG.md" in claude
    assert "〈docs/" not in claude
    assert "Numeric/DECIMAL" not in claude
    # 项目特化占位符必须保留，供落地时填写
    for placeholder in (
        "〈一句话说明这个服务是做什么的〉",
        "### 3.4 〈项目特有的关键机制〉",
        "## 十二、〈项目特有约定〉",
    ):
        assert placeholder in claude, placeholder

    for doc in BACKEND_DOCS:
        assert (SKILL_DIR / "assets" / "backend" / "docs" / "开发指南" / doc).is_file(), doc


def test_ops_app_build_spec_bundled_opscli_docs_match_repo_docs():
    """打包进 Skill 的 OPSCLI 文档除头部链接改写外必须与仓库文档一致，防止漂移。"""
    pairs = {
        "OPSCLI_SDK调用规范.md": ROOT / "docs" / "spec" / "SDK调用规范.md",
        "OPSCLI_SDK使用文档.md": ROOT / "docs" / "guide" / "SDK使用文档.md",
        "OPSCLI_API调用规范.md": ROOT / "docs" / "spec" / "API调用规范.md",
        "OPSCLI_API使用文档.md": ROOT / "docs" / "guide" / "API使用文档.md",
    }
    # 头部 6 行是文档引言，其中相对链接被改写为同目录文件名
    header_lines = 6
    for bundled_name, source in pairs.items():
        bundled = (SKILL_DIR / "assets" / "backend" / "docs" / "开发指南" / bundled_name).read_text(encoding="utf-8")
        original = source.read_text(encoding="utf-8")
        assert bundled.splitlines()[header_lines:] == original.splitlines()[header_lines:], bundled_name
        assert "](../" not in bundled, bundled_name
