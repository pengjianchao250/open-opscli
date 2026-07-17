"""Scrape.do API 场景执行和落盘。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.scrape_do.accounts import ScrapeDoCredentialProvider
from opscli.scrape_do.api.client import ScrapeDoApiClient
from opscli.scrape_do.api.scenarios import get_scenario, list_scenarios
from opscli.scrape_do.config import ScrapeDoSettings, load_settings
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError
from opscli.scrape_do.domain.models import ScrapeDoScenarioRequest, ScrapeDoScenarioResult
from opscli.scrape_do.export.xlsx import export_rows_to_xlsx, extract_rows
from opscli.shared.file_uploads import FileUploadClient, FileUploadError


class ScrapeDoApiManager:
    """执行 Scrape.do API 场景并保存请求和响应数据。"""

    def __init__(
        self,
        *,
        settings: ScrapeDoSettings | None = None,
        api_key_provider: ScrapeDoCredentialProvider | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id
        self.api_key_provider = api_key_provider or ScrapeDoCredentialProvider()
        self._job_roots: dict[str, Path] = {}

    def scenarios(self) -> list[dict[str, Any]]:
        """列出支持的接口场景。"""
        return list_scenarios()

    async def run(self, request: ScrapeDoScenarioRequest) -> ScrapeDoScenarioResult:
        """执行一个 Scrape.do 场景。"""
        export_format = _normalize_export_format(request.export_format)
        scenario = get_scenario(request.scenario)
        site = _normalize_site(request.site)
        job_id = _sanitize_job_id(request.job_id) if request.job_id else _build_job_id(request, site)
        root_dir = self._build_root_dir(request, job_id)
        self._job_roots[job_id] = root_dir
        root_dir.mkdir(parents=True, exist_ok=True)
        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"

        credential = self.api_key_provider.get_default()
        normalized_params = scenario.build_params(params=request.params, site=site, token=credential.token)
        safe_params = _sanitize_persisted(normalized_params)
        warnings: list[dict[str, Any]] = []

        _write_json(
            params_path,
            {
                "job_id": job_id,
                "request": _safe_request_dict(request),
                "scenario": scenario.to_public_dict(),
                "site": site,
                "normalized_params": safe_params,
                "account": credential.to_public_dict(),
                "settings": self.settings.to_public_dict(),
                "export_format": export_format,
            },
        )

        timeout = request.timeout_seconds or self.settings.timeout_seconds
        async with ScrapeDoApiClient(timeout_seconds=timeout) as client:
            response = await client.get_json(scenario.endpoint, normalized_params)

        raw_payload = {
            "job_id": job_id,
            "scenario": request.scenario,
            "site": site,
            "endpoint": scenario.endpoint,
            "request_url": response.safe_url,
            "request_params": safe_params,
            "response": _sanitize_persisted(response.payload),
            "billing": response.billing,
            "warnings": warnings,
        }
        _write_json(raw_path, raw_payload)

        rows = extract_rows(request.scenario, response.payload)
        rows = [{"site": site, **row} for row in rows]
        export = export_rows_to_xlsx(
            rows=rows,
            output_path=root_dir / f"{job_id}.xlsx",
            scenario=request.scenario,
            site=site,
            params=request.params,
            raw_payload=raw_payload["response"],
        )
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            warnings=warnings,
            jwt=self.jwt,
            session_id=self.session_id,
        )

        result = ScrapeDoScenarioResult(
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            row_count=len(rows),
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            export=export,
            data=rows,
            request={"method": "GET", "endpoint": scenario.endpoint, "params": safe_params, "export_format": export_format},
            billing=response.billing,
            warnings=warnings,
        )
        _write_json(result_path, _sanitize_persisted(result.to_dict()))
        self._write_job_index(job_id, root_dir)
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取已落盘任务状态。"""
        root_dir = self._resolve_job_root(job_id)
        result_path = root_dir / "result.json"
        if not result_path.exists():
            raise ScrapeDoConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _build_root_dir(self, request: ScrapeDoScenarioRequest, job_id: str) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id

    def _resolve_job_root(self, job_id: str) -> Path:
        if job_id in self._job_roots:
            return self._job_roots[job_id]
        index_path = self.settings.output_dir / f"{job_id}.index.json"
        if index_path.exists():
            try:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
                root_dir = payload.get("root_dir")
                if root_dir:
                    return Path(root_dir)
            except (OSError, ValueError, TypeError):
                pass
        return self.settings.output_dir / job_id

    def _write_job_index(self, job_id: str, root_dir: Path) -> None:
        if root_dir.parent == self.settings.output_dir:
            return
        _write_json(self.settings.output_dir / f"{job_id}.index.json", {"job_id": job_id, "root_dir": str(root_dir)})


def _normalize_export_format(value: str) -> str:
    text = (value or "").strip().lower()
    if text in {"", "xls", "xlsx"}:
        return "xls"
    raise ScrapeDoConfigError(f"不支持的导出格式：{value}。Scrape.do 当前仅支持 xls/xlsx 表格导出。")


def _normalize_site(value: Any) -> str:
    text = str(value or "US").strip().upper()
    return "GB" if text == "UK" else text or "US"


def _build_job_id(request: ScrapeDoScenarioRequest, site: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    target = _target_label(request.params)
    parts = ["ScrapeDo", _scenario_label(request.scenario), site, target, timestamp, suffix]
    return "-".join(part for part in parts if part)


def _sanitize_job_id(value: Any) -> str:
    text = _sanitize_filename_part(value)
    if not text:
        raise ScrapeDoConfigError("job_id 不能为空")
    return text


def _scenario_label(scenario: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", scenario) if part)


def _target_label(params: dict[str, Any] | None) -> str:
    if not isinstance(params, dict):
        return ""
    value = params.get("asin") or params.get("keyword")
    if value is None:
        return ""
    return _sanitize_filename_part(value)[:64]


def _sanitize_filename_part(value: Any) -> str:
    text = str(value or "").strip().replace(" ", "-")
    text = re.sub(r"[^A-Za-z0-9\-]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def _safe_request_dict(request: ScrapeDoScenarioRequest) -> dict[str, Any]:
    payload = request.to_dict()
    payload["params"] = _sanitize_persisted(payload.get("params"))
    return payload


def _sanitize_persisted(value: Any) -> Any:
    return _strip_sensitive(_strip_html(value))


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "_").lower()
        if _is_sensitive_field(normalized):
            continue
        result[key] = _strip_sensitive(item)
    return result


def _is_sensitive_field(normalized_key: str) -> bool:
    return (
        normalized_key in {"token", "api_key", "authorization"}
        or normalized_key.endswith("_token")
        or "token" in normalized_key
        or "secret" in normalized_key
    )


def _strip_html(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_html(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _strip_html(item)
        for key, item in value.items()
        if not _is_html_field(key)
    }


def _is_html_field(key: Any) -> bool:
    normalized = str(key).replace("-", "_").lower()
    if normalized in {"html", "raw_html", "source_html", "html_content"}:
        return True
    return "html" in normalized


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _upload_export_if_enabled(
    *,
    export,
    job_id: str,
    scenario: str,
    site: str,
    warnings: list[dict[str, Any]],
    jwt: str | None,
    session_id: str | None,
) -> None:
    client = FileUploadClient(jwt=jwt, session_id=session_id)
    if not client.enabled:
        return
    try:
        uploaded = client.upload(
            Path(export.path),
            purpose="scrape_do_export",
            folder="scrape-do/exports",
            metadata={"job_id": job_id, "scenario": scenario, "site": site},
        )
    except FileUploadError as exc:
        warnings.append({"stage": "file_upload", "message": "导出文件上传失败，已保留服务端本地文件", "error": str(exc)})
        return
    export.url = uploaded.url
