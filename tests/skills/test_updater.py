from pathlib import Path

import httpx
import pytest

from opscli.skills.exceptions import SkillRemoteError
from opscli.skills.models import SkillRecord
from opscli.skills.updater import SkillsUpdater


def test_compare_versions():
    updater = SkillsUpdater()

    assert updater.compare_versions("v0.0.0", "v0.0.1") < 0
    assert updater.compare_versions("v1.2.0", "v1.2.0") == 0
    assert updater.compare_versions("v1.3.0", "v1.2.9") > 0


def test_upgrade_ops_dataset_query_writes_files(tmp_path: Path, monkeypatch):
    skill_root = tmp_path / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text('{"name":"ops-dataset-query","version":"v0.0.0"}', encoding="utf-8")
    (data_dir / "dataset_fields.csv").write_text("a\n", encoding="utf-8")
    (data_dir / "datasets.csv").write_text("b\n", encoding="utf-8")
    (data_dir / "query_metadata.json").write_text('{"datasets":[],"fields":[]}', encoding="utf-8")

    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.0.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    updater = SkillsUpdater()

    monkeypatch.setattr(updater, "fetch_manifest", lambda skill_name: {"version": "v1.0.0"})

    class DummyResponse:
        def __init__(self, text: str = "", data: dict | None = None):
            self.text = text
            self._data = data or {}

        def json(self):
            return self._data

    def fake_get(endpoint: str):
        if endpoint == updater.FIELDS_ENDPOINT:
            return DummyResponse("field_header,global_alias\nfield_value,ga_field_value\n")
        if endpoint == updater.DATASETS_ENDPOINT:
            return DummyResponse("dataset_header\ndataset_value\n")
        if endpoint == updater.QUERY_METADATA_ENDPOINT:
            return DummyResponse(data={"data": {"datasets": [{"table_id": 1}], "fields": [{"field_name": "price"}]}})
        raise AssertionError(endpoint)

    monkeypatch.setattr(updater, "_get", fake_get)

    result = updater.upgrade_ops_dataset_query(record)

    assert result.updated is True
    assert result.to_version == "v1.0.0"
    assert '"version": "v1.0.0"' in (data_dir / "VERSION.json").read_text(encoding="utf-8")
    assert "ga_field_value" in (data_dir / "dataset_fields.csv").read_text(encoding="utf-8")
    assert "dataset_value" in (data_dir / "datasets.csv").read_text(encoding="utf-8")
    assert '"table_id": 1' in (data_dir / "query_metadata.json").read_text(encoding="utf-8")


def test_get_wraps_404_as_human_error(monkeypatch):
    updater = SkillsUpdater()

    monkeypatch.setattr(
        "opscli.skills.sync.updater.AuthClient.build_request_auth",
        lambda self, alias: (
            {"Authorization": "Bearer token"},
            {"polarisUserToken": "session-123", "opscliDeviceCode": "dc-abc"},
        ),
    )

    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code=404, request=request)

    def fake_get(*args, **kwargs):
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr("opscli.skills.sync.updater.httpx.get", fake_get)

    with pytest.raises(SkillRemoteError) as exc:
        updater._get(updater.MANIFEST_ENDPOINT)

    assert "未部署" in str(exc.value)
    assert updater.MANIFEST_ENDPOINT in str(exc.value)


def test_get_sends_unified_auth_headers_and_cookies(monkeypatch):
    updater = SkillsUpdater()
    captured = {}

    monkeypatch.setattr(
        "opscli.skills.sync.updater.AuthClient.build_request_auth",
        lambda self, alias: (
            {"Authorization": "Bearer token"},
            {"polarisUserToken": "session-123", "opscliDeviceCode": "dc-abc"},
        ),
    )

    def fake_get(url, headers=None, cookies=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return httpx.Response(200, request=httpx.Request("GET", url), json={"code": 200, "data": {}})

    monkeypatch.setattr("opscli.skills.sync.updater.httpx.get", fake_get)

    updater._get(updater.MANIFEST_ENDPOINT)

    assert captured["url"].endswith(updater.MANIFEST_ENDPOINT)
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["cookies"]["opscliDeviceCode"] == "dc-abc"
    assert captured["timeout"] == 20
    assert captured["follow_redirects"] is True


def test_parse_json_response_rejects_invalid_payload():
    updater = SkillsUpdater()
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code=200, request=request, text="not-json")

    with pytest.raises(SkillRemoteError) as exc:
        updater._parse_json_response(response, endpoint=updater.MANIFEST_ENDPOINT)

    assert "无法解析的 JSON" in str(exc.value)


def test_parse_json_response_rejects_business_error_payload():
    updater = SkillsUpdater()
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(
        status_code=200,
        request=request,
        json={"code": 404, "msg": "尚未发布任何版本，请管理员先执行 publish", "data": []},
    )

    with pytest.raises(SkillRemoteError) as exc:
        updater._parse_json_response(response, endpoint=updater.MANIFEST_ENDPOINT)

    assert "远端 Skill 数据尚未发布" in str(exc.value)


def test_skill_remote_error_to_dict():
    error = SkillRemoteError(
        "远端失败",
        endpoint="/v1/test",
        status_code=503,
    )

    assert error.to_dict() == {
        "type": "SkillRemoteError",
        "message": "远端失败",
        "endpoint": "/v1/test",
        "status_code": 503,
    }
