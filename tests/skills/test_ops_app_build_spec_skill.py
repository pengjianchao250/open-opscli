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
    assert files == [
        "SKILL.md",
        "data/VERSION.json",
        "references/backend-standard.md",
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


def test_ops_app_build_spec_keeps_current_delivery_boundaries():
    """提交规范保留当前 opscli 命令和线上部署边界。"""
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
    installed_files = sorted(path.relative_to(installed).as_posix() for path in installed.rglob("*") if path.is_file())
    assert installed_files == [
        "SKILL.md",
        "data/VERSION.json",
        "references/backend-standard.md",
        "references/data-access-standard.md",
        "references/deployment-standard.md",
        "references/frontend-standard.md",
        "references/migration-standard.md",
    ]
