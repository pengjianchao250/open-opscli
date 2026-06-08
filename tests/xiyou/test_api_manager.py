import asyncio
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential
from opscli.xiyou.domain.exceptions import XiyouConfigError
from opscli.xiyou.domain.models import XiyouRankingRequest
from opscli.xiyou.services import api_manager as api_manager_module
from opscli.xiyou.services.api_manager import (
    XiyouApiManager,
    _count_xlsx_rows,
    _extract_items,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def local_tmp_path():
    path = Path("output") / "test-runs" / f"xiyou-api-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class DummyCredentialProvider:
    def get_default(self):
        return XiyouCredential(authorization="token", cookie="cookie=value")


class DummyApiClient:
    calls = []

    def __init__(self, *, credential, settings):
        self.credential = credential
        self.settings = settings

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post_json(self, url, payload):
        self.calls.append({"url": url, "payload": payload})
        return {
            "code": 200,
            "list": [
                {
                    "product": {
                        "asin": "B00TEST123",
                        "title": "Demo Product",
                        "price": 9.99,
                    },
                    "flow": {"score": 100},
                    "flowRank": 1,
                }
            ],
        }

    async def get_bytes(self, url):
        self.calls.append({"url": url, "method": "GET"})
        return b"xlsx-bytes"


class DummyResourceApiClient(DummyApiClient):
    async def post_json(self, url, payload):
        self.calls.append({"url": url, "payload": payload})
        if url.endswith("/resource/status"):
            return {
                "resourceId": payload["resourceId"],
                "status": "Done",
                "resourceUrl": "https://excel.xydc.com/demo.xlsx?Expires=1\\u0026Signature=s",
            }
        return {"resourceId": "resource-1"}


class DummyUploadClient:
    instances = []

    def __init__(self, *, jwt=None, session_id=None):
        self.jwt = jwt
        self.session_id = session_id
        self.uploads = []
        DummyUploadClient.instances.append(self)

    @property
    def enabled(self):
        return True

    def upload(self, path, *, purpose, folder=None, public=None, metadata=None):
        self.uploads.append(
            {
                "path": path,
                "purpose": purpose,
                "folder": folder,
                "public": public,
                "metadata": metadata,
            }
        )

        class Result:
            url = "https://ops.example.com/download/job-json.json"

        return Result()


def test_manager_writes_job_files_and_json(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ranking",
                provider="xiyou",
                target="asin",
                site="US",
                period="week",
                rank_pattern="flow",
                job_id="job-json",
                export_format="json",
            )
        )
    )

    root_dir = local_tmp_path / "job-json"
    assert result.row_count == 1
    assert result.export is not None
    assert result.export.filename == "job-json.json"
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert DummyApiClient.calls[0]["url"] == "/v2/rankingList/asins"
    assert DummyApiClient.calls[0]["payload"]["biz"]["rankPattern"] == "flow"

    exported = json.loads(Path(result.export.path).read_text(encoding="utf-8"))
    assert exported["target"] == "asin"
    assert exported["rows"][0]["product"]["asin"] == "B00TEST123"


def test_manager_uploads_export_and_returns_download_url(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    DummyUploadClient.instances = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DummyUploadClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(
        settings=settings,
        credential_provider=DummyCredentialProvider(),
        jwt="jwt-token",
        session_id="session-id",
    )

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ranking",
                provider="xiyou",
                target="asin",
                site="US",
                period="week",
                rank_pattern="flow",
                job_id="job-json",
                export_format="json",
            )
        )
    )

    assert result.export is not None
    assert result.export.url == "https://ops.example.com/download/job-json.json"
    assert result.warnings == []
    assert DummyUploadClient.instances[0].jwt == "jwt-token"
    assert DummyUploadClient.instances[0].session_id == "session-id"
    upload = DummyUploadClient.instances[0].uploads[0]
    assert upload["purpose"] == "xiyou_export"
    assert upload["folder"] == "xiyou/exports"
    assert upload["public"] == "1"
    assert upload["metadata"]["job_id"] == "job-json"
    assert upload["metadata"]["target"] == "asin"

    saved = json.loads((local_tmp_path / "job-json" / "result.json").read_text(encoding="utf-8"))
    assert saved["export"]["url"] == "https://ops.example.com/download/job-json.json"


def test_manager_writes_xlsx(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                target="keyword",
                site="US",
                period="week",
                rank_pattern="aba",
                job_id="job-xlsx",
                export_format="xlsx",
            )
        )
    )

    assert result.export is not None
    assert result.export.filename == "job-xlsx.xlsx"
    assert Path(result.export.path).exists()
    assert DummyApiClient.calls[0]["url"] == "/v3/rankingList/searchTerms"
    assert DummyApiClient.calls[0]["payload"]["biz"]["rankPattern"] == "aba"


def test_job_status_reads_existing_result(local_tmp_path: Path):
    root_dir = local_tmp_path / "job-1"
    root_dir.mkdir()
    (root_dir / "result.json").write_text('{"job_id":"job-1","row_count":3}', encoding="utf-8")
    settings = XiyouSettings(output_dir=local_tmp_path)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = manager.job_status("job-1")

    assert result == {"job_id": "job-1", "row_count": 3}


@pytest.mark.parametrize(
    "response",
    [
        {"data": {"items": [{"a": 1}]}},
        {"data": {"list": [{"a": 1}]}},
        {"data": {"records": [{"a": 1}]}},
        {"data": [{"a": 1}]},
        {"biz": {"rows": [{"a": 1}]}},
        {"list": [{"a": 1}]},
    ],
)
def test_extract_items_supports_common_response_shapes(response):
    assert _extract_items(response) == [{"a": 1}]


def test_invalid_function_is_rejected(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError):
        _run(manager.run(XiyouRankingRequest(function="unknown")))


def test_manager_downloads_resource_xlsx(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0G33FZ8XS",
                site="US",
                job_id="job-resource",
                export_format="xlsx",
            )
        )
    )

    root_dir = local_tmp_path / "job-resource"
    assert result.data_mode == "resource_export"
    assert result.dataset == "keywords"
    assert result.resource_id == "resource-1"
    assert result.resource_url == "https://excel.xydc.com/demo.xlsx?Expires=1&Signature=s"
    assert result.export is not None
    assert result.export.filename == "job-resource.xlsx"
    assert Path(result.export.path).read_bytes() == b"xlsx-bytes"
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/asins/research/list/resource"
    assert DummyResourceApiClient.calls[1]["url"] == "/v4/resource/status"
    assert DummyResourceApiClient.calls[2]["method"] == "GET"


def test_manager_writes_resource_json_metadata(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-explorer",
                keyword="tv stand",
                site="US",
                job_id="job-resource-json",
                export_format="json",
            )
        )
    )

    assert result.export is not None
    exported = json.loads(Path(result.export.path).read_text(encoding="utf-8"))
    assert exported["function"] == "keyword-explorer"
    assert exported["dataset"] == "keywords"
    assert exported["resource_id"] == "resource-1"
    assert exported["resource_url"].endswith("Signature=s")



def _build_xlsx_bytes(data_rows: int) -> bytes:
    """生成包含 1 行表头 + data_rows 行数据的 xlsx 字节，供 mock 下载使用。"""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["keyword", "traffic"])
    for index in range(data_rows):
        ws.append([f"kw-{index}", index])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_count_xlsx_rows_returns_data_row_count(tmp_path: Path):
    # 真实 xlsx：表头 1 行 + 数据 5 行，_count_xlsx_rows 应返回 5
    xlsx_path = tmp_path / "sample.xlsx"
    xlsx_path.write_bytes(_build_xlsx_bytes(5))

    assert _count_xlsx_rows(xlsx_path) == 5


def test_count_xlsx_rows_returns_zero_for_corrupt_file(tmp_path: Path):
    # 非标准 xlsx（伪字节）必须返回 0，不能抛异常导致主任务失败
    corrupt_path = tmp_path / "broken.xlsx"
    corrupt_path.write_bytes(b"not-an-xlsx")

    assert _count_xlsx_rows(corrupt_path) == 0


class DummyResourceXlsxClient(DummyResourceApiClient):
    """返回真实 xlsx 字节的 DummyResourceApiClient，用于验证 row_count/warning。"""

    xlsx_bytes: bytes = b""

    async def get_bytes(self, url):
        self.calls.append({"url": url, "method": "GET"})
        return self.__class__.xlsx_bytes


def test_resource_xlsx_populates_row_count_and_warns_on_page_size_mismatch(
    monkeypatch, local_tmp_path: Path
):
    # 模拟西柚返回 5 行全量数据，但调用方仅请求 2 行，应触发 page_size warning
    DummyResourceXlsxClient.calls = []
    DummyResourceXlsxClient.xlsx_bytes = _build_xlsx_bytes(5)
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceXlsxClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0G33FZ8XS",
                site="US",
                page_size=2,
                job_id="job-resource-warn",
                export_format="xlsx",
            )
        )
    )

    assert result.row_count == 5
    # 仅校验 resource_export 阶段的 warning，避免环境内 file_upload 失败导致干扰
    resource_warnings = [w for w in result.warnings if w.get("stage") == "resource_export"]
    assert len(resource_warnings) == 1
    warning = resource_warnings[0]
    assert "page_size=2" in warning["message"]
    assert "5 行" in warning["message"]


def test_resource_xlsx_no_warning_when_page_size_not_exceeded(
    monkeypatch, local_tmp_path: Path
):
    # 默认 page_size=50，xlsx 仅 3 行时不应追加 page_size 相关 warning
    DummyResourceXlsxClient.calls = []
    DummyResourceXlsxClient.xlsx_bytes = _build_xlsx_bytes(3)
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceXlsxClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0G33FZ8XS",
                site="US",
                job_id="job-resource-ok",
                export_format="xlsx",
            )
        )
    )

    assert result.row_count == 3
    assert all(w.get("stage") != "resource_export" for w in result.warnings)
