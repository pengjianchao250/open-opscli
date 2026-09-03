"""OPS 应用规范 Skill 契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.skills.manager import SkillsManager
from opscli.skills.packaging import validate_release_manifest


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "opscli" / "skills" / "templates" / "ops-app-build-spec"


def _read(relative_path: str) -> str:
    """按 UTF-8 读取 Skill 文件。"""
    return (SKILL_DIR / relative_path).read_text(encoding="utf-8")


def test_ops_app_build_spec_has_consistent_metadata():
    """目录、主文件与版本文件必须保持一致。"""
    skill = _read("SKILL.md")
    version = json.loads(_read("data/VERSION.json"))

    assert "name: ops-app-build-spec" in skill.split("---", 2)[1]
    assert version == {"name": "ops-app-build-spec", "version": "v0.0.4"}


def test_ops_app_build_spec_routes_real_data_work_to_data_builder():
    """真实业务数据需求必须进入独立规范和数据层构建 Skill。"""
    skill = _read("SKILL.md")
    standard = _read("references/data-access-standard.md")
    content = "\n".join((skill, standard))

    for required in (
        "references/data-access-standard.md",
        "$ops-app-data-builder",
        "页面需要真实业务数据",
        "不选择或猜测数据集、字段、聚合、筛选、第三方场景",
        "前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite",
        "docs/ops-app/data-spec.md",
        "OPSCLI_API_BASE_URL",
        "OPSCLI_API_KEY",
        "未隔离的 viewer 数据",
        "第一阶段不增加运行时数据 YAML",
    ):
        assert required in content


def test_ops_app_build_spec_routes_supported_migrations_and_stops_others():
    """迁移矩阵必须覆盖指定来源并保留不支持边界。"""
    content = _read("SKILL.md") + _read("references/migration-standard.md")

    for required in (
        "Vite + React",
        "Vite + Vue",
        "Next.js + React",
        "普通 HTML/CSS/JS",
        "Vite + Vue 3 + Element Plus",
        "FastAPI + SQLite",
        "当前技术栈不在自动迁移范围，请联系 IT 人员处理。",
    ):
        assert required in content

    for server_feature in (
        "SSR",
        "RSC",
        "ISR",
        "Server Actions",
        "Edge Runtime",
        "Middleware",
    ):
        assert server_feature in content

    assert "Vue 2、其他前端框架、非 FastAPI 后端和任何非 SQLite 数据库" in content
    assert "非 SQLite 且已有业务数据" not in content
    assert "需要时才迁移到 FastAPI + SQLite" not in content
    assert "没有后端时只初始化前端" in content
    assert "不得创建 FastAPI 占位服务" in content


def test_ops_app_build_spec_enforces_template_first_initialization():
    """全新项目必须先创建和拉取模板，再允许 Skill 写入项目文件。"""
    initialization = _read("references/initialization-standard.md")
    skill = _read("SKILL.md")

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
    assert "template_applied=true" in skill
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
        "${OPS_APP_ID}",
        "${OPS_APP_NAME}",
        "listen 8080",
        "access_log /dev/stdout",
        "error_log /dev/stderr warn",
        "resolver 127.0.0.11 valid=30s ipv6=off",
        "set $backend_upstream http://backend:8000",
        "proxy_pass $backend_upstream",
        "location ^~ /ops-app/${OPS_APP_ID}/${OPS_APP_NAME}/",
        "rewrite ^/ops-app/${OPS_APP_ID}/${OPS_APP_NAME}/(.*)$ /$1 last",
        "try_files $uri $uri/ /index.html",
        'Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always',
        'X-Accel-Expires "0" always',
        'Cache-Control "public, no-cache" always',
        "etag off",
        "if_modified_since off",
        "etag on",
        "if_modified_since exact",
    ):
        assert required in template

    assert "immutable" not in template
    assert template.count("max-age=") == 1
    assert "assets/nginx.conf.template" in deployment
    assert "nginx -t" in deployment
    assert "外层公开地址" in deployment
    assert "/usr/share/nginx/html/assets/app.js" in deployment
    assert "不额外创建 `/ops-app/{appId}/{appName}/` 文件夹" in deployment


def test_ops_app_build_spec_uses_one_config_source_for_vite_and_nginx():
    """Vite 与 Nginx 必须复用同一配置读取和路径派生模块。"""
    config = json.loads(_read("assets/ops-app.config"))
    loader = _read("assets/ops-app-config.mjs")
    declarations = _read("assets/ops-app-config.d.mts")
    renderer = _read("assets/render-nginx-config.mjs")
    frontend = _read("references/frontend-standard.md")
    deployment = _read("references/deployment-standard.md")
    content = "\n".join((frontend, deployment))

    assert config == {"schemaVersion": 1, "appId": None, "appName": "example-app"}
    for required in (
        "loadOpsAppConfig",
        "getOpsAppDeployBase",
        "requireAppId",
        "schemaVersion",
        "APP_ID_PATTERN",
        "APP_NAME_PATTERN",
        "getOpsAppImageName",
    ):
        assert required in loader
    assert "getOpsAppImageName" in declarations

    assert 'from "./ops-app-config.mjs"' in renderer
    assert '.replaceAll("${OPS_APP_ID}", config.appId)' in renderer
    assert '.replaceAll("${OPS_APP_NAME}", config.appName)' in renderer
    assert "../deployment/ops-app-config.mjs" in frontend
    assert "node deployment/render-nginx-config.mjs" in deployment
    assert "不得声明 `OPS_APP_ID`、`OPS_APP_NAME`" in deployment
    assert "envsubst" not in content


def test_ops_app_build_spec_has_no_legacy_project_id_contract():
    """Skill 的所有资源必须使用 appId 命名，避免生成两套配置合同。"""
    skill_root = Path(__file__).parents[2] / "opscli" / "skills" / "templates" / "ops-app-build-spec"
    content = "\n".join(path.read_text(encoding="utf-8") for path in skill_root.rglob("*") if path.is_file())

    for legacy in (
        "projectId",
        "OPS_PROJECT_ID",
        "requireProjectId",
        "PROJECT_ID_PATTERN",
        "项目 ID",
    ):
        assert legacy not in content


def test_ops_app_build_spec_defines_compose_and_layering_contracts():
    """部署参考必须覆盖 Compose 生产约束和精确复制顺序。"""
    deployment = _read("references/deployment-standard.md")

    for required in (
        "最新 Compose Specification",
        "build.context",
        "frontend-deps -> frontend-build -> frontend-runtime",
        "backend-deps  -> backend-build  -> backend-runtime",
        "package.json",
        "uv.lock",
        "service_healthy",
        "read_only: true",
        "tmpfs",
        "restart: unless-stopped",
        "init: true",
        "container_name",
        "privileged",
        "network_mode: host",
        "Compose secrets",
        "禁止无边界的 `COPY . .`",
        "Dockerfile 不声明 `VOLUME`",
        "0.0.0.0:${OPS_APP_PORT:-8080}:8080",
        "<appId>-<appName>-frontend",
        "<appId>-<appName>-backend",
        ":sha-<git-sha>",
        "pull_policy: always",
        "镜像 digest",
        "image` 字段由 Skill 调用共享配置模块",
    ):
        assert required in deployment

    assert "Windows" not in deployment
    assert "podman-compose" not in deployment
    assert "127.0.0.11 valid=30s ipv6=off" in deployment


def test_ops_app_build_spec_is_declared_and_installable(tmp_path: Path):
    """模板必须通过清单检查并完整安装 references。"""
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
