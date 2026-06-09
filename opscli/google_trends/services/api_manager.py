"""Google Trends 场景执行和落盘。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.google_trends.api.client import GoogleTrendsApiClient
from opscli.google_trends.api.scenarios import get_scenario, list_scenarios
from opscli.google_trends.config import GoogleTrendsSettings, load_settings
from opscli.google_trends.domain.exceptions import GoogleTrendsConfigError
from opscli.google_trends.domain.models import (
    GoogleTrendsExportResult,
    GoogleTrendsScenarioRequest,
    GoogleTrendsScenarioResult,
)
from opscli.google_trends.export.xlsx import export_rows_to_xlsx
from opscli.shared.file_uploads import FileUploadClient, FileUploadError


class GoogleTrendsApiManager:
    """执行 Google Trends 场景并保存请求和响应数据。"""

    def __init__(
        self,
        *,
        settings: GoogleTrendsSettings | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id

    def scenarios(self) -> list[dict[str, Any]]:
        """列出支持的接口场景。"""
        return list_scenarios()

    async def run(self, request: GoogleTrendsScenarioRequest) -> GoogleTrendsScenarioResult:
        """执行一个 Google Trends 场景。"""
        scenario = get_scenario(request.scenario)
        geo = _normalize_geo_for_job(request.geo)
        job_id = request.job_id or _build_job_id(request, geo)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"

        normalized_params = scenario.build_params(params=request.params, geo=geo)
        effective_geo = normalized_params.get("geo") if "geo" in normalized_params else geo
        warnings: list[dict[str, Any]] = []

        _write_json(
            params_path,
            {
                "request": request.to_dict(),
                "scenario": scenario.to_public_dict(),
                "normalized_params": normalized_params,
                "settings": self.settings.to_public_dict(),
            },
        )

        client = GoogleTrendsApiClient(settings=self.settings, hl=request.hl, tz=request.tz)
        raw_response = await asyncio.to_thread(client.run, request.scenario, normalized_params)
        raw_payload = {
            "job_id": job_id,
            "scenario": request.scenario,
            "geo": effective_geo,
            "method": scenario.method,
            "request_params": normalized_params,
            "response": raw_response,
            "warnings": warnings,
        }
        _write_json(raw_path, raw_payload)

        data = extract_rows(request.scenario, raw_response)
        export_format = _normalize_export_format(request.export_format)
        if export_format == "xlsx":
            export = export_rows_to_xlsx(
                rows=data,
                output_path=root_dir / f"{job_id}.xlsx",
                scenario=request.scenario,
                geo=str(effective_geo),
                params=request.params,
            )
        else:
            export = _export_raw_to_json(
                output_path=root_dir / f"{job_id}.json",
                job_id=job_id,
                scenario=request.scenario,
                geo=str(effective_geo),
                request_params=normalized_params,
                raw_response=raw_response,
                rows=data,
                warnings=warnings,
            )
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            geo=str(effective_geo),
            warnings=warnings,
            jwt=self.jwt,
            session_id=self.session_id,
        )

        result = GoogleTrendsScenarioResult(
            job_id=job_id,
            scenario=request.scenario,
            geo=str(effective_geo),
            row_count=len(data),
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            export=export,
            data=data,
            warnings=warnings,
        )
        _write_json(result_path, result.to_dict())
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取已落盘任务状态。"""
        root_dir = self.settings.output_dir / job_id
        result_path = root_dir / "result.json"
        if not result_path.exists():
            raise GoogleTrendsConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _build_root_dir(self, request: GoogleTrendsScenarioRequest, job_id: str) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id


def extract_rows(scenario: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从 Google Trends 原始响应中提取主要结果列表。"""
    if not isinstance(payload, dict):
        return []
    if scenario in {"related-queries", "related-topics"}:
        return _extract_related_rows(payload)
    records = payload.get("records")
    if not isinstance(records, list):
        return []
    if scenario in {"trending-searches", "realtime-trending"}:
        return [_normalize_trending_row(row, index) for index, row in enumerate(records, start=1)]
    return [_normalize_row(row) for row in records]


def _extract_related_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for keyword, groups in payload.items():
        if not isinstance(groups, dict):
            continue
        for group_name, records in groups.items():
            if not isinstance(records, list):
                continue
            for record in records:
                row = _normalize_row(record)
                row.setdefault("keyword", keyword)
                row.setdefault("type", group_name)
                rows.append(row)
    return rows


def _normalize_trending_row(row: Any, rank: int) -> dict[str, Any]:
    data = _normalize_row(row)
    data["rank"] = rank
    term = data.get("search_term") or data.get("title") or data.get("query") or data.get("0") or data.get(0)
    if term is None:
        for key, value in data.items():
            if key not in {"rank", "traffic"} and not isinstance(value, (dict, list)):
                term = value
                break
    if term is not None:
        data["search_term"] = str(term)
    return data


def _normalize_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return {"value": row}


def _build_job_id(request: GoogleTrendsScenarioRequest, geo: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    parts = ["GoogleTrends", _scenario_label(request.scenario), _sanitize_filename_part(geo or "GLOBAL")]
    target = _build_target_label(request.params)
    if target:
        parts.append(target)
    parts.append(timestamp)
    parts.append(suffix)
    return "-".join(part for part in parts if part)


def _scenario_label(scenario: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", scenario) if part)


def _build_target_label(params: dict[str, Any] | None) -> str:
    if not isinstance(params, dict):
        return ""
    value = params.get("keyword") or _first(params.get("keywords")) or _first(params.get("kw_list")) or params.get("pn")
    return _sanitize_filename_part(value)


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def _sanitize_filename_part(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = text.replace(" ", "-")
    text = re.sub(r"[^A-Za-z0-9\-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:64]


def _normalize_geo_for_job(value: str) -> str:
    if value is None:
        return "US"
    text = str(value).strip()
    return text.upper() if text else ""


def _normalize_export_format(value: str) -> str:
    text = (value or "").strip().lower()
    if text in {"", "xls", "xlsx"}:
        return "xlsx"
    if text == "json":
        return "json"
    raise GoogleTrendsConfigError(f"不支持的导出格式：{value}")


def _export_raw_to_json(
    *,
    output_path: Path,
    job_id: str,
    scenario: str,
    geo: str,
    request_params: dict[str, Any],
    raw_response: dict[str, Any],
    rows: list[Any],
    warnings: list[dict[str, Any]],
) -> GoogleTrendsExportResult:
    payload = {
        "job_id": job_id,
        "scenario": scenario,
        "geo": geo,
        "request_params": request_params,
        "row_count": len(rows),
        "rows": rows,
        "raw_response": raw_response,
        "warnings": warnings,
    }
    _write_json(output_path, payload)
    resolved = output_path.resolve()
    return GoogleTrendsExportResult(
        path=str(resolved),
        filename=resolved.name,
        url=resolved.as_uri(),
        format="json",
        mime_type="application/json",
    )


def _upload_export_if_enabled(
    *,
    export: GoogleTrendsExportResult,
    job_id: str,
    scenario: str,
    geo: str,
    warnings: list[dict[str, Any]],
    jwt: str | None = None,
    session_id: str | None = None,
) -> None:
    client = FileUploadClient(jwt=jwt, session_id=session_id)
    if not client.enabled:
        return
    try:
        upload = client.upload(
            export.path,
            purpose="google_trends_export",
            folder="google_trends/exports",
            public="1",
            metadata={
                "job_id": job_id,
                "scenario": scenario,
                "geo": geo,
                "filename": export.filename,
            },
        )
        export.url = upload.url
    except FileUploadError as exc:
        warnings.append(
            {
                "stage": "file_upload",
                "message": "导出文件上传失败，已保留服务端本地文件",
                "error": exc.to_dict(),
            }
        )
    except Exception as exc:
        warnings.append(
            {
                "stage": "file_upload",
                "message": "导出文件上传失败，已保留服务端本地文件",
                "error": {
                    "code": type(exc).__name__,
                    "message": str(exc),
                },
            }
        )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
