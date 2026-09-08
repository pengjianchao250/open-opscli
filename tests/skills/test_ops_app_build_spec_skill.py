"""OPS 应用模板开发 Skill 契约测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from opscli.skills.packaging import validate_release_manifest
from opscli.skills.services.manager import SkillsManager


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "opscli" / "skills" / "templates" / "ops-app-build-spec"


def _read(relative_path: str) -> str:
    """按 UTF-8 读取 Skill 文件。"""
    return (SKILL_DIR / relative_path).read_text(encoding="utf-8")


def _rewrite_bundled_links(content: str, replacements: dict[str, str]) -> str:
    """只改写复制到同目录后失效的文档链接。"""
    for source, target in replacements.items():
        content = content.replace(source, target)
    return content


def test_ops_app_build_spec_has_consistent_metadata() -> None:
    """Skill 名称、版本和后端规范入口必须一致。"""
    skill = _read("SKILL.md")
    version = json.loads(_read("data/VERSION.json"))

    assert "name: ops-app-build-spec" in skill.split("---", 2)[1]
    assert version == {"name": "ops-app-build-spec", "version": "v0.0.13"}
    assert not (SKILL_DIR / "references" / "backend-standard.md").exists()


def test_ops_app_build_spec_entry_references_resolve() -> None:
    """入口引用必须随 Skill 存在，防止残留旧资产路径。"""
    references = re.findall(r"(?:references|assets)/[\w/.-]+\.(?:md|py)", _read("SKILL.md"))
    assert references
    for relative_path in references:
        assert (SKILL_DIR / relative_path).is_file(), relative_path


def test_ops_app_build_spec_routes_backend_contracts_to_redlines() -> None:
    """主入口维护阅读路由，数据细则允许放在对应参考文件中。"""
    skill = _read("SKILL.md")

    for required in (
        "references/data-access-standard.md",
        "references/deployment-standard.md",
        "references/frontend-standard.md",
        "references/migration-standard.md",
        "$ops-app-data-builder",
        "页面需要真实业务数据",
        "不选择或猜测数据集、字段、聚合、筛选、第三方场景",
        "前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite",
        "docs/ops-app/data-spec.md",
        "以后端实现为事实源",
        "生成的 OpenAPI 和实际路由共同定义前后端合同",
        "修改前端请求、错误处理或前后端共享类型",
        "修改 FastAPI API、服务、任务或配置",
        "references/backend-redlines.md",
        "无论新项目还是已绑定项目",
        "不得用前端兼容分支掩盖后端合同漂移",
    ):
        assert required in skill

    assert "references/backend-standard.md" not in skill
    data_access = _read("references/data-access-standard.md")
    for required in (
        "OPSCLI_API_BASE_URL", "OPSCLI_API_KEY", "owner_user_id", "pending `job_id`",
        "XLS/XLSX", "第一阶段不增加运行时数据 YAML",
    ):
        assert required in data_access


def test_ops_app_build_spec_clones_detaches_and_recognizes_template() -> None:
    """新项目必须安全克隆、脱离模板 Git，再创建并初始化 AppHub 应用。"""
    skill = _read("SKILL.md")

    for required in (
        "http://10.1.13.143:3000/aukeys-admin/template",
        "分支：`master`",
        'python "<skill-directory>/scripts/clone_template.py" "<project-directory>"',
        "成功后立即删除项目根目录 `.git` 并验证其不存在",
        'opscli app create "<app-name>" --path "<project-directory>" --json',
        'opscli app init "<project-directory>" --json',
        "clone 并脱离模板 Git 元数据、`create` 和 `init` 是开始开发前连续执行的必需步骤",
        "origin` 不指向统一模板仓库",
        "不能只根据 remote 判断",
        "app.yaml",
        "backend/app.py",
        "docs/apphub-contract.md",
        "合同缺失时读取迁移规范",
    ):
        assert required in skill

    for obsolete in ("create-vue", "assets/app.yaml", "ops-app.config"):
        assert obsolete not in skill

    assert ".opscli/app.json.slug == app.yaml.name" in skill
    deployment = _read("references/deployment-standard.md")
    assert ".gitignore` 必须忽略 `.opscli/" in deployment
    assert "app_id`、仓库、Owner 和 Git 信息只保留在本地 binding" in deployment

    assert skill.index('python "<skill-directory>/scripts/clone_template.py"') < skill.index(
        'opscli app create "<app-name>" --path "<project-directory>" --json'
    )
    assert skill.index(
        'opscli app create "<app-name>" --path "<project-directory>" --json'
    ) < skill.index('opscli app init "<project-directory>" --json')
    assert skill.index('opscli app init "<project-directory>" --json') < skill.index(
        "开发前读取目标项目的"
    )


def test_ops_app_build_spec_frontend_follows_backend_contract() -> None:
    """前端只能消费后端路由、Schema 和 OpenAPI。"""
    frontend = _read("references/frontend-standard.md")

    for required in (
        "API 合同以后端为准",
        "backend-redlines.md",
        "Pydantic Schema 和生成的 OpenAPI",
        "前端不得维护第二套口径",
        "具体端点及字段仍从目标项目后端合同读取",
        "是否存在 HTTP 200 内的业务失败，只按目标项目合同判断",
        "先由后端更新路由、Schema、相关测试和 OpenAPI",
        "不新增前端兼容分支掩盖漂移",
        "应用代码不得读取、复制或持久化平台密钥、JWT、Cookie",
    ):
        assert required in frontend


def test_ops_app_build_spec_backend_redlines_use_current_apphub_design() -> None:
    """后端红线必须包含当前 AppHub 基线并移除旧设计。"""
    redlines = _read("references/backend-redlines.md")

    for required in (
        "普通后端开发、前后端合同变更和后端评审的强制入口",
        "backend/app.py",
        "docs/apphub-contract.md",
        "Pydantic Schema 和生成的 OpenAPI",
        "路由只做鉴权、参数校验、协议转换和事务收口",
        "单个 FastAPI 进程托管 API 和前端构建产物",
        "目标项目现有依赖清单",
        "AppHub SQLite 应用保持单写实例",
        "viewer、session 或 local 网关",
        "用户未授权时",
        "--autogenerate",
        "alembic_version",
    ):
        assert required in redlines

    for obsolete in (
        "backend/docs/开发指南/",
        "Compose 固定单副本",
        "必须写进 `pyproject.toml`",
        "服务端一律显式传入 `session_id` / `jwt`",
        "AI开发通用规范",
    ):
        assert obsolete not in redlines


def test_ops_app_build_spec_active_references_do_not_restore_legacy_deployment() -> None:
    """强制读取的 references 不得重新引入旧双服务合同。"""
    content = "\n".join(
        _read(relative_path)
        for relative_path in (
            "references/backend-redlines.md",
            "references/frontend-standard.md",
            "references/sqlite-standard.md",
            "references/opscli-integration-standard.md",
            "references/data-access-standard.md",
            "references/deployment-standard.md",
        )
    )

    for obsolete in (
        "Compose 中 SQLite 服务固定单副本",
        "Compose 管理的持久卷",
        "app/main.py",
        "ops-app.config",
        "/ops-app/{appId}/{appName}/",
    ):
        assert obsolete not in content


def test_ops_app_build_spec_keeps_data_access_constraints() -> None:
    """真实取数必须保留后端代理和凭证隔离边界。"""
    content = _read("SKILL.md") + _read("references/data-access-standard.md")

    for required in (
        "$ops-app-data-builder",
        "前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite",
        "前端不得持有 API Key、JWT、Cookie",
        "不选择或猜测数据集、字段、聚合、筛选",
        "默认按访问者实时取数",
        "Mock、测试替身和本地回退不得被描述成线上真实接入",
    ):
        assert required in content


def test_ops_app_build_spec_opscli_integration_uses_project_gateways() -> None:
    """opscli 接入必须支持项目网关并按请求隔离凭证。"""
    integration = _read("references/opscli-integration-standard.md")

    for required in (
        "viewer、session、local",
        "X-Ops-Token",
        "X-Session-Id",
        "LOCAL_AUTH_FALLBACK_ENABLED",
        "每个请求构造",
        "asyncio.to_thread",
        "跨请求缓存凭证",
        "userEmail",
    ):
        assert required in integration

    for obsolete in ("polarisUserToken", "ops-app.config", "/ops-app/{appId}/{appName}/"):
        assert obsolete not in integration


def test_ops_app_build_spec_keeps_generic_migration_rules() -> None:
    """迁移规范只负责迁移流程，不复制实现细节。"""
    migration = _read("references/migration-standard.md")

    for required in (
        "先判断现有项目是否已满足模板合同",
        "保留源项目",
        "只迁移业务代码与必要配置",
        "取数能力按当前 `data-access-standard.md` 重新核对",
        "无法确认行为等价时停止",
        "assets/backend/",
    ):
        assert required in migration

    for duplicated_detail in ("alembic upgrade head", "migrations/versions", "data/app.db"):
        assert duplicated_detail not in migration


def test_ops_app_build_spec_keeps_current_deployment_contract() -> None:
    """源码交付必须保持当前 AppHub 单应用合同。"""
    deployment = _read("references/deployment-standard.md")

    for required in (
        "apiVersion: apps.aukeys/v1",
        "backend/app.py",
        "uvicorn backend.app:app --host 0.0.0.0 --port 8000",
        "单应用进程合同",
        "opscli app create",
        "opscli app init",
        "opscli app push",
        "统一模板仓库的 `master` 分支",
        "HEAD:master",
        "远端 `master`",
        "整体暂存当前项目改动",
        "push 成功只表示源码到达远端",
        "不提供 release 命令",
        "不创建 release、不查询版本、不消费发布事件",
        "不得报告“已发布”或“部署成功”",
        "ops-feedback",
        "不重新引入已废弃的 `opscli.app.migrate`、Nginx 双服务",
        ".opscli/app.json.slug == app.yaml.name",
        ".opscli/app.json` 不得被 Git 跟踪或暂存",
    ):
        assert required in deployment

    for obsolete in (
        "python -m opscli.app.migrate",
        "ops-app.config",
        "opscli app release",
        "services.sqlite: true",
        "runtime: fastapi",
        "entrypoint: backend/app.py",
    ):
        assert obsolete not in deployment


def test_ops_app_build_spec_backend_template_is_project_entry() -> None:
    """迁移用后端模板只保留项目合同和特化入口。"""
    agents = _read("assets/backend/AGENTS.md")
    claude = _read("assets/backend/CLAUDE.md")

    for required in (
        "项目规范入口：`CLAUDE.md`",
        "../docs/开发指南/FastAPI后端开发通用规范.md",
        "../docs/openapi.json",
        "docs/apphub-contract.md",
    ):
        assert required in agents

    for required in (
        "只保存 AppHub 合同和项目特有约定",
        "backend/app.py",
        "backend/main.py",
        "/__apphub_healthz",
        "APP_DB_PATH",
        "生成的 `docs/openapi.json`",
        "当前 Skill 的 `backend-redlines.md` 是跨项目强制红线",
        "前端不得单独维护另一套 API 协议",
        "viewer、session、local 或其他网关模式",
        "项目特有约定",
    ):
        assert required in claude

    for obsolete in (
        "app/main.py",
        "ops-app.config",
        "前端 Nginx",
        "Compose healthcheck",
        "uv run uvicorn app.main:app",
        "polarisUserToken",
        "docs/API规范/openapi.json",
    ):
        assert obsolete not in claude

def test_ops_app_build_spec_is_declared_and_installable(tmp_path: Path) -> None:
    """Skill 必须通过正式清单检查并完整安装。"""
    problems = validate_release_manifest(ROOT / "opscli" / "skills" / "templates")
    assert not any("ops-app-build-spec" in problem for problem in problems)

    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    templates = {item["name"]: item for item in manager.list_templates()}
    assert templates["ops-app-build-spec"]["version"] == "v0.0.13"

    result = manager.install("ops-app-build-spec", skills_dir=str(tmp_path / "skills"))
    installed = Path(result.to_dict()["installed_paths"][0]["path"])
    for relative_path in (
        "SKILL.md",
        "references/frontend-standard.md",
        "references/backend-redlines.md",
        "references/sqlite-standard.md",
        "references/opscli-integration-standard.md",
        "references/data-access-standard.md",
        "references/migration-standard.md",
        "references/deployment-standard.md",
        "scripts/clone_template.py",
        "assets/backend/AGENTS.md",
        "assets/backend/CLAUDE.md",
    ):
        assert (installed / relative_path).exists(), relative_path

    assert not (installed / "references" / "backend-standard.md").exists()


def test_ops_app_build_spec_bundled_opscli_docs_match_repo_docs() -> None:
    """Skill 内 OPSCLI 文档正文必须与仓库权威文档一致。"""
    pairs = {
        "OPSCLI_SDK调用规范.md": (
            ROOT / "docs" / "spec" / "SDK调用规范.md",
            {"../guide/SDK使用文档.md": "OPSCLI_SDK使用文档.md"},
        ),
        "OPSCLI_SDK使用文档.md": (
            ROOT / "docs" / "guide" / "SDK使用文档.md",
            {
                "CLI 用法见 [认证模块使用指南](认证模块使用指南.md)。": "CLI 用法见 opscli 仓库 `docs/guide/认证模块使用指南.md`。",
                "../spec/SDK调用规范.md": "OPSCLI_SDK调用规范.md",
            },
        ),
        "OPSCLI_API调用规范.md": (
            ROOT / "docs" / "spec" / "API调用规范.md",
            {
                "../guide/API使用文档.md": "OPSCLI_API使用文档.md",
                "SDK调用规范.md": "OPSCLI_SDK调用规范.md",
            },
        ),
        "OPSCLI_API使用文档.md": (
            ROOT / "docs" / "guide" / "API使用文档.md",
            {
                "../spec/API调用规范.md": "OPSCLI_API调用规范.md",
                "SDK使用文档.md": "OPSCLI_SDK使用文档.md",
            },
        ),
    }
    for bundled_name, (source, replacements) in pairs.items():
        bundled = _read(f"assets/backend/docs/开发指南/{bundled_name}")
        original = source.read_text(encoding="utf-8")
        assert bundled == _rewrite_bundled_links(original, replacements), bundled_name
