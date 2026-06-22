import json
from pathlib import Path

import httpx
import pytest

from opscli.config import __version__
from opscli.skills.manager import SkillsManager
from opscli.skills.models import SkillRecord, SkillUpgradeResult
from opscli.skills.updater import SkillsUpdater


class DummyAuthClient:
    def build_request_auth(self, alias: str):
        assert alias == "ops"
        return {"Authorization": "Bearer jwt-token"}, {"polarisUserToken": "session-123"}


def _question_template_response(url: str) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("GET", url),
        json={
            "code": 200,
            "data": {
                "items": [
                    {
                        "id": 56,
                        "description": "??",
                        "preferred_version_index": 0,
                        "questions": [{"id": 3172, "text": "??1", "position": 1}],
                        "created_at": "2026-04-28T09:25:05",
                        "updated_at": "2026-04-28T09:25:12",
                    }
                ]
            },
            "msg": "success",
        },
    )


def test_upgrade_ops_amazon_rufus_writes_merged_question_templates(tmp_path: Path, monkeypatch):
    skill_root = tmp_path / "ops-amazon-rufus"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        '{"name":"ops-amazon-rufus","version":"v0.0.0"}',
        encoding="utf-8",
    )

    record = SkillRecord(
        name="ops-amazon-rufus",
        version="v0.0.0",
        runtime="codex",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    updater = SkillsUpdater()
    captured = {}

    def fake_httpx_get(url, headers=None, cookies=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return _question_template_response(url)

    monkeypatch.setattr("opscli.skills.sync.updater.OPS_URL", "https://ops.example.com/api")
    monkeypatch.setattr("opscli.skills.sync.updater.AuthClient", lambda: DummyAuthClient())
    monkeypatch.setattr("opscli.skills.sync.updater.httpx.get", fake_httpx_get)

    result = updater.upgrade_ops_amazon_rufus(record)

    assert captured == {
        "url": "https://ops.example.com/api/opencalw/default-question-templates",
        "headers": {"Authorization": "Bearer jwt-token", "X-Opscli-Version": __version__},
        "cookies": {"polarisUserToken": "session-123"},
        "timeout": 20,
        "follow_redirects": True,
    }
    assert result.updated is True
    assert result.to_version == "v0.0.1"
    assert json.loads((data_dir / "question_templates.json").read_text(encoding="utf-8")) == {
        "items": [
            {
                "id": 56,
                "description": "??",
                "preferred_version_index": 0,
                "questions": [{"id": 3172, "text": "??1", "position": 1}],
                "created_at": "2026-04-28T09:25:05",
                "updated_at": "2026-04-28T09:25:12",
            }
        ]
    }
    assert not (data_dir / "runner_config.json").exists()
    assert not (data_dir / "marketplaces.json").exists()
    assert not (data_dir / "questions").exists()


def test_upgrade_ops_amazon_rufus_uses_fixed_question_template_path(
    tmp_path: Path,
    monkeypatch,
):
    skill_root = tmp_path / "ops-amazon-rufus"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        '{"name":"ops-amazon-rufus","version":"v0.0.0"}',
        encoding="utf-8",
    )
    record = SkillRecord(
        name="ops-amazon-rufus",
        version="v0.0.0",
        runtime="codex",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    captured = {}

    def fake_httpx_get(url, headers=None, cookies=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return _question_template_response(url)

    monkeypatch.setattr("opscli.skills.sync.updater.OPS_URL", "https://ops.example.com/api")
    monkeypatch.setattr("opscli.skills.sync.updater.AuthClient", lambda: DummyAuthClient())
    monkeypatch.setattr("opscli.skills.sync.updater.httpx.get", fake_httpx_get)

    result = SkillsUpdater().upgrade_ops_amazon_rufus(record)

    assert captured == {
        "url": "https://ops.example.com/api/opencalw/default-question-templates",
        "headers": {"Authorization": "Bearer jwt-token", "X-Opscli-Version": __version__},
        "cookies": {"polarisUserToken": "session-123"},
        "timeout": 20,
        "follow_redirects": True,
    }
    assert result.field_count == 1


def test_upgrade_ops_amazon_rufus_rejects_empty_question_templates(tmp_path: Path, monkeypatch):
    skill_root = tmp_path / "ops-amazon-rufus"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)

    record = SkillRecord(
        name="ops-amazon-rufus",
        version="v0.0.0",
        runtime="codex",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    updater = SkillsUpdater()

    def fake_httpx_get(url, headers=None, cookies=None, timeout=None, follow_redirects=None):
        # 远端返回空题库时不能覆盖本地有效数据。
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"code": 200, "data": {"items": []}, "msg": "success"},
        )

    monkeypatch.setattr("opscli.skills.sync.updater.OPS_URL", "https://ops.example.com/api")
    monkeypatch.setattr("opscli.skills.sync.updater.AuthClient", lambda: DummyAuthClient())
    monkeypatch.setattr("opscli.skills.sync.updater.httpx.get", fake_httpx_get)

    from opscli.skills.domain.exceptions import SkillRemoteError

    with pytest.raises(SkillRemoteError) as exc:
        updater.upgrade_ops_amazon_rufus(record)

    assert "Rufus 默认题库为空" in str(exc.value)


def test_upgrade_dispatches_ops_amazon_rufus(tmp_path: Path, monkeypatch):
    manager = SkillsManager()
    record = SkillRecord(
        name="ops-amazon-rufus",
        version="v0.0.0",
        runtime="codex",
        root=tmp_path / "ops-amazon-rufus",
        version_file=tmp_path / "ops-amazon-rufus" / "data" / "VERSION.json",
    )
    monkeypatch.setattr(manager, "list_skills", lambda **kwargs: [record])
    monkeypatch.setattr(
        manager.updater,
        "upgrade_ops_amazon_rufus",
        lambda target, force=False: SkillUpgradeResult(
            name=target.name,
            from_version="v0.0.0",
            to_version="v0.0.1",
            runtime=target.runtime,
            target_dir=target.root,
            updated=True,
            field_count=1,
        ),
    )

    result = manager.upgrade(name="ops-amazon-rufus", cwd=tmp_path)

    payload = result.to_dict()
    assert payload["updated"][0]["name"] == "ops-amazon-rufus"
    assert payload["updated"][0]["field_count"] == 1


def test_ops_amazon_rufus_template_json_files_do_not_have_bom():
    template_dir = Path("opscli/skills/templates/ops-amazon-rufus/data")

    for path in [template_dir / "VERSION.json", template_dir / "question_templates.json"]:
        assert path.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_ops_amazon_rufus_template_uses_mcp_boundary():
    template_dir = Path("opscli/skills/templates/ops-amazon-rufus")

    assert list(template_dir.rglob("*.py")) == []
    assert (template_dir / "references" / "rufus-mcp-workflow.md").exists()

    skill_text = (template_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "references/rufus-mcp-workflow.md" in skill_text
    assert "question?, questions?" not in skill_text
    assert "检测到当前 Amazon 未登录或登录态不可用" not in skill_text

    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            template_dir / "SKILL.md",
            template_dir / "README.md",
            template_dir / "references" / "question-templates.md",
            template_dir / "references" / "rufus-mcp-workflow.md",
        ]
    )
    assert "opscli/mcp/tools/amazon_rufus.py" in docs
    assert "Rufus 运行期以 MCP Tool 优先编排" in docs
    assert "MCP-first" in docs
    assert "amazon_rufus_remote_consent_status" in docs
    assert "amazon_rufus_remote_consent_set" in docs
    assert "amazon_rufus_login_status" in docs
    assert "amazon_rufus_watch_login" in docs
    assert "amazon_rufus_logout" in docs
    assert "amazon_rufus_get" in docs
    assert "amazon_rufus_platform_cookie_save" in docs
    assert "amazon_rufus_platform_cookie_get" in docs
    assert "amazon_rufus_curl_save" in docs
    assert "RUFUS_SECRET_NOT_READY" in docs
    assert "headless 后端获取" in docs
    assert "timeout_seconds=180" in docs
    assert "外层请求上限" in docs
    assert "RUFUS_HEADLESS_CAPTURE_ERROR" in docs
    assert "amazon_rufus_logout -> amazon_rufus_watch_login -> amazon_rufus_get" in docs
    assert "#nav-tools" in docs
    assert "sso-state-main" in docs
    assert "at-main" in docs
    assert "identifícate" in docs
    assert "amazon_rufus_watch_login(asin=\"B0TEST1234\", country=\"US\", close_browser=true)" in docs
    assert "用户无需在 Agent 会话中额外回复“已登录”" in docs
    assert "请求种子" in docs
    assert "OPS 平台 Cookie 接口 content" in docs
    assert "旧 `browser-state-<COUNTRY>.bin`" in docs
    assert "browser-state-<COUNTRY>.json` 和 `.browser-state-key` 不再作为默认读写源" in docs
    assert "保存完成后，重新按原问题来源调用 `amazon_rufus_get`" in docs
    assert "发起 Rufus 获取前" in docs
    assert "can_get_backend" in docs
    assert "没有可用亚马逊 Rufus 登录态" in docs
    assert "请明确回复“允许”或“拒绝”" in docs
    assert "不建议在该 Amazon 账号中绑定信用卡" in docs
    assert "只有以下两种情况允许 CLI fallback" in docs
    assert "必需 MCP Tool 不可用" in docs
    assert "用户拒绝保存并复用该站点亚马逊 Rufus 登录态" in docs
    assert "状态为 `denied` 时进入 CLI fallback" in docs
    assert "拒绝远程授权" in docs
    assert "opscli amazon-rufus login-status" in docs
    assert "opscli amazon-rufus watch-login" in docs
    assert "opscli amazon-rufus get-backend" in docs
    assert "其他错误不允许 CLI fallback" in docs
    assert "MCP 登录采集" in docs
    assert "chrome_path" in docs
    assert "Chrome CDP" in docs
    assert "浏览器 cURL 命令态" in docs
    assert "旧 `curl_data` 或仅 `storage_state`" in docs
    assert "cURL 命令" in docs
    for forbidden in [
        "amazon_rufus_init",
        "amazon_rufus_get_remote",
        "allow_capture_browser_state",
        "--remote-rufus",
        "--new-chrome",
        "session-id=",
        "session-token=",
        "--cookie ",
        "curl '",
        "curl \"",
        "payload_template",
        "完整 curl",
        "curl 等价",
        "mock",
        "Copy-as-CURL",
        "Copy-as-cURL",
        "opscli amazon-rufus curl save",
        "opscli amazon-rufus cookie save",
        "opscli amazon-rufus cookie status",
        "init <COUNTRY> --launch-if-needed -> 用户登录",
        "opscli amazon-rufus save-state <COUNTRY>",
        "用户确认登录后，按原问题来源重新执行 `opscli amazon-rufus get`",
        "opscli amazon-rufus logout",
        "opscli amazon-rufus remote-consent",
        "本地加密状态",
        "本地加密浏览器状态",
        "加密请求种子",
        "直接走 CDP",
        "拒绝则走 CDP",
    ]:
        assert forbidden not in docs


def test_ops_amazon_rufus_docs_require_fresh_report_path():
    """约束 Agent 只读取本次 Rufus 获取返回的最新报告路径。"""
    skill_dirs = [
        Path("opscli/skills/templates/ops-amazon-rufus"),
        Path(".agents/skills/ops-amazon-rufus"),
    ]

    for skill_dir in skill_dirs:
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        readme_text = (skill_dir / "README.md").read_text(encoding="utf-8")
        workflow_text = (skill_dir / "references" / "rufus-mcp-workflow.md").read_text(encoding="utf-8")

        assert "本次工具返回的 `report_path`" in skill_text
        assert "不得返回历史 ASIN 报告" in readme_text
        assert "报告新鲜度约束" in workflow_text
        assert "禁止仅凭 ASIN" in workflow_text
        assert "本次 `report_path`" in workflow_text


def test_ops_amazon_rufus_docs_route_platform_cookie_auth_to_watch_login():
    """OPS 平台 Cookie 鉴权失败按新规则进入 MCP 登录采集。"""
    skill_dirs = [
        Path("opscli/skills/templates/ops-amazon-rufus"),
        Path(".agents/skills/ops-amazon-rufus"),
    ]

    for skill_dir in skill_dirs:
        docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                skill_dir / "SKILL.md",
                skill_dir / "README.md",
                skill_dir / "references" / "rufus-mcp-workflow.md",
            ]
        )

        assert "RUFUS_PLATFORM_COOKIE_AUTH_ERROR" in docs
        assert "OPS 平台 Cookie 鉴权错误" in docs
        assert "401" in docs
        assert "amazon_rufus_watch_login(asin, country, close_browser=true)" in docs
        assert "本分支不允许 CLI fallback" in docs
        assert "本轮不得执行 `amazon_rufus_logout`、`amazon_rufus_watch_login` 或重复 `amazon_rufus_get`" not in docs
        assert "先通过 MCP auth 工具修复 OPS/MCP 鉴权" not in docs


def test_ops_amazon_rufus_docs_require_answer_quality_rewrite_retry():
    """Rufus 回答无效时必须按 Skill 规则改写问题并有限重试。"""
    skill_dirs = [
        Path("opscli/skills/templates/ops-amazon-rufus"),
        Path(".agents/skills/ops-amazon-rufus"),
    ]

    for skill_dir in skill_dirs:
        docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                skill_dir / "SKILL.md",
                skill_dir / "README.md",
                skill_dir / "references" / "rufus-mcp-workflow.md",
            ]
        )

        assert "回答质量判断" in docs
        assert "answer_rewrite_attempts_by_question" in docs
        assert "每个问题最多 5 次" in docs
        assert "按问题分别记录" in docs
        assert "同一个 Rufus 对话" in docs
        assert "多问题" in docs
        assert "开启一个子 agent" in docs
        assert "重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。" in docs
        assert "answer_count=0" in docs
        assert "拒答" in docs
        assert "商品详情" in docs
        assert "按改写后的完整问题来源重新调用 `amazon_rufus_get`" in docs
        assert "整个回答质量重试过程最多 5 次" not in docs


def test_ops_amazon_rufus_docs_limit_watch_login_once_per_skill_call():
    """同一次 Skill 调用内所有登录采集入口共享 watch_login 单次触发状态。"""
    skill_dirs = [
        Path("opscli/skills/templates/ops-amazon-rufus"),
        Path(".agents/skills/ops-amazon-rufus"),
    ]

    for skill_dir in skill_dirs:
        docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                skill_dir / "SKILL.md",
                skill_dir / "README.md",
                skill_dir / "references" / "rufus-mcp-workflow.md",
            ]
        )

        assert "watch_login_attempted=false" in docs
        assert "watch_login_attempted=true" in docs
        assert "同一次 Skill 调用最多触发一次 `watch_login`" in docs
        assert "任何分支准备调用 `amazon_rufus_watch_login`" in docs
        assert "如果 `watch_login_attempted=true`，不得再次调用 `amazon_rufus_watch_login`" in docs
