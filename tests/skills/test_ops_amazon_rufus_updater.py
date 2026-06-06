import json
from pathlib import Path

import httpx
import pytest

from opscli.skills.manager import SkillsManager
from opscli.skills.models import SkillRecord, SkillUpgradeResult
from opscli.skills.updater import SkillsUpdater


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

    def fake_httpx_get(url, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return _question_template_response(url)

    monkeypatch.setattr("opscli.skills.sync.updater.httpx.get", fake_httpx_get)

    result = updater.upgrade_ops_amazon_rufus(record)

    assert captured == {
        "url": "http://127.0.0.1:8000/api/opencalw/default-question-templates",
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

    def fake_httpx_get(url, timeout=None, follow_redirects=None):
        # 远端返回空题库时不能覆盖本地有效数据。
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"code": 200, "data": {"items": []}, "msg": "success"},
        )

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
    assert "默认使用 MCP 后端 headless 链路" in docs
    assert "RUFUS_SECRET_NOT_READY" in docs
    assert "headless 后端获取" in docs
    assert "timeout_seconds=180" in docs
    assert "外层请求上限" in docs
    assert "RUFUS_HEADLESS_CAPTURE_ERROR" in docs
    assert "opscli amazon-rufus init" in docs
    assert "opscli amazon-rufus save-state" in docs
    assert "init <COUNTRY> --launch-if-needed -> 用户登录 -> opscli amazon-rufus save-state <COUNTRY> -> amazon_rufus_get" in docs
    assert "保存完成后，重新按原问题来源调用 `amazon_rufus_get`" in docs
    assert "--launch-if-needed" in docs
    assert "--chrome-path" in docs
    assert "Chrome CDP" in docs
    for forbidden in [
        "amazon_rufus_init",
        "amazon_rufus_get_remote",
        "allow_capture_browser_state",
        "--remote-rufus",
        "--new-chrome",
        "用户确认登录后，按原问题来源重新执行 `opscli amazon-rufus get`",
    ]:
        assert forbidden not in docs
