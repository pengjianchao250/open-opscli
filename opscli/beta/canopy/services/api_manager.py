"""beta Canopy API 场景执行和落盘。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from opscli.beta.canopy.config import CANOPY_BASE_URL, CanopySettings, load_settings
from opscli.beta.canopy.domain.exceptions import CanopyApiError, CanopyConfigError
from opscli.beta.canopy.domain.models import CanopyScenarioRequest, CanopyScenarioResult
from opscli.beta.canopy.export.xlsx import export_rows_to_xlsx, response_to_export_rows
from opscli.shared.file_uploads import FileUploadClient, FileUploadError


class CanopyApiManager:
    """执行 Canopy API 场景并保存请求、响应和导出数据。"""

    def __init__(
        self,
        *,
        settings: CanopySettings | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id

    async def run(self, request: CanopyScenarioRequest) -> CanopyScenarioResult:
        """执行一个 Canopy API 场景。"""
        export_format = _normalize_export_format(request.export_format)
        if request.timeout_seconds <= 0:
            raise CanopyConfigError("timeout_seconds 必须大于 0")
        if not request.path:
            raise CanopyConfigError("缺少 Canopy API path")

        job_id = request.job_id or _build_job_id(request)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"

        normalized_params = {**request.params, "domain": request.domain}
        _write_json(
            params_path,
            _params_payload(
                request=request,
                job_id=job_id,
                normalized_params=normalized_params,
                export_format=export_format,
            ),
        )

        raw_response = await request_canopy_api(
            path=request.path,
            params=normalized_params,
            api_key=request.api_key,
            timeout_seconds=request.timeout_seconds,
        )
        safe_response = _redact_secret(raw_response, request.api_key)

        raw_payload = {
            "job_id": job_id,
            "scenario": request.scenario,
            "domain": request.domain,
            "method": request.method,
            "url": f"{CANOPY_BASE_URL}{request.path}",
            "request_params": normalized_params,
            "response": safe_response,
        }
        _write_json(raw_path, raw_payload)

        rows = response_to_export_rows(safe_response)
        export = export_rows_to_xlsx(
            rows=rows,
            output_path=root_dir / f"{job_id}.xlsx",
            scenario=request.scenario,
            domain=request.domain,
            params=request.params,
        )
        warnings: list[dict[str, Any]] = []
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            domain=request.domain,
            warnings=warnings,
            jwt=self.jwt,
            session_id=self.session_id,
        )

        result = CanopyScenarioResult(
            job_id=job_id,
            scenario=request.scenario,
            domain=request.domain,
            row_count=len(rows),
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            title=request.title,
            request={
                "method": request.method,
                "url": f"{CANOPY_BASE_URL}{request.path}",
                "params": normalized_params,
                "api_key_placeholder_used": request.api_key_placeholder_used,
                "export_format": export_format,
            },
            export=export,
            data=rows,
            response=safe_response,
            warnings=warnings,
        )
        _write_json(result_path, result.to_dict())
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取已落盘任务状态。"""
        root_dir = self.settings.output_dir / job_id
        result_path = root_dir / "result.json"
        if not result_path.exists():
            raise CanopyConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _build_root_dir(self, request: CanopyScenarioRequest, job_id: str) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id


async def request_canopy_api(
    *,
    path: str,
    params: dict[str, Any],
    api_key: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """执行 Canopy REST 请求，并要求响应为 JSON 对象。"""
    headers = {
        "API-KEY": api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(f"{CANOPY_BASE_URL}{path}", params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise _api_error_from_response(exc.response) from exc
    except httpx.HTTPError as exc:
        raise CanopyApiError(f"Canopy API 请求失败：{exc}") from exc
    except ValueError as exc:
        raise CanopyApiError("Canopy API 响应不是合法 JSON", response_excerpt=str(exc)) from exc

    if not isinstance(data, dict):
        raise ValueError("Canopy API 必须返回 JSON 对象")
    return data


def _normalize_export_format(value: str) -> str:
    """校验用户可见导出格式；beta 当前只允许 xls。"""
    text = (value or "").strip().lower()
    if text in {"", "xls"}:
        return "xls"
    raise CanopyConfigError(f"不支持的导出格式：{value}。beta Canopy 当前仅支持 xls 表格导出。")


def _params_payload(
    *,
    request: CanopyScenarioRequest,
    job_id: str,
    normalized_params: dict[str, Any],
    export_format: str,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "scenario": request.scenario,
        "title": request.title,
        "domain": request.domain,
        "method": request.method,
        "url": f"{CANOPY_BASE_URL}{request.path}",
        "params": request.params,
        "normalized_params": normalized_params,
        "timeout_seconds": request.timeout_seconds,
        "export_format": export_format,
        "api_key_placeholder_used": request.api_key_placeholder_used,
    }


def _api_error_from_response(response: httpx.Response) -> CanopyApiError:
    status_code = response.status_code
    response_payload: dict[str, Any] | None = None
    response_excerpt: str | None = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            response_payload = parsed
            response_excerpt = json.dumps(parsed, ensure_ascii=False)[:2000]
        else:
            response_excerpt = json.dumps(parsed, ensure_ascii=False)[:2000]
    except ValueError:
        response_excerpt = response.text[:2000]
    return CanopyApiError(
        f"Canopy API 返回 HTTP {status_code}",
        status_code=status_code,
        response_excerpt=response_excerpt,
        response_payload=response_payload,
    )


def _build_job_id(request: CanopyScenarioRequest) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    scenario = re.sub(r"[^a-zA-Z0-9_-]+", "-", request.scenario).strip("-") or "canopy"
    return f"canopy-{scenario}-{timestamp}-{uuid4().hex[:8]}"


def _upload_export_if_enabled(
    *,
    export: Any,
    job_id: str,
    scenario: str,
    domain: str,
    warnings: list[dict[str, Any]],
    jwt: str | None = None,
    session_id: str | None = None,
) -> None:
    """复用 OPS 公共上传能力，把本地 Excel 换成可下载的远端 URL。"""
    client = FileUploadClient(jwt=jwt, session_id=session_id)
    if not client.enabled:
        return
    try:
        upload = client.upload(
            export.path,
            purpose="beta_canopy_export",
            folder="beta/canopy/export",
            public="1",
            metadata={
                "job_id": job_id,
                "scenario": scenario,
                "domain": domain,
                "filename": export.filename,
                "format": export.format,
                "mime_type": export.mime_type,
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


def _redact_secret(value: Any, secret: str) -> Any:
    if not secret:
        return value
    if isinstance(value, list):
        return [_redact_secret(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact_secret(item, secret) for key, item in value.items()}
    if isinstance(value, str):
        return value.replace(secret, "<REDACTED>")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
