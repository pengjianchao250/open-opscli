"""西柚洞察接口直连任务编排。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.xiyou.api.client import XiyouApiClient
from opscli.xiyou.api.scenarios import get_scenario, list_scenarios
from opscli.xiyou.config import DEFAULT_PROVIDER, XiyouSettings, load_settings
from opscli.xiyou.credentials import XiyouCredentialProvider
from opscli.xiyou.domain.exceptions import XiyouConfigError
from opscli.xiyou.domain.models import XiyouExportResult, XiyouRankingRequest, XiyouRankingResult
from opscli.xiyou.export.xlsx import export_rows_to_xlsx


class XiyouApiManager:
    """执行西柚洞察接口场景并落盘任务结果。"""

    def __init__(
        self,
        *,
        settings: XiyouSettings | None = None,
        credential_provider: XiyouCredentialProvider | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.credential_provider = credential_provider or XiyouCredentialProvider(self.settings)

    def scenarios(self) -> list[dict[str, Any]]:
        """列出支持的接口场景。"""
        return [
            {
                "function": "ranking",
                "provider": DEFAULT_PROVIDER,
                "targets": list_scenarios(),
                "periods": ["week", "month"],
                "sites": ["US", "DE", "UK", "CA", "FR"],
            }
        ]

    async def run(self, request: XiyouRankingRequest) -> XiyouRankingResult:
        """执行排行榜接口场景。"""
        self._validate_request(request)
        scenario = get_scenario(request.target)
        rank_pattern = scenario.normalize_rank_pattern(request.rank_pattern)
        job_id = request.job_id or _build_job_id(request.function)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        site = (request.site or self.settings.default_site).upper()
        period = request.period or self.settings.default_period
        page_size = request.page_size or self.settings.page_size
        payload = scenario.build_payload(
            site=site,
            period=period,
            rank_pattern=rank_pattern,
            query=request.query,
            page=request.page,
            page_size=page_size,
        )

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"
        _write_json(
            params_path,
            {
                "request": request.to_dict(),
                "endpoint": scenario.endpoint,
                "payload": payload,
            },
        )

        credential = self.credential_provider.get_default()
        async with XiyouApiClient(credential=credential, settings=self.settings) as client:
            response = await client.post_json(scenario.endpoint, payload)

        raw = {
            "job_id": job_id,
            "function": request.function,
            "provider": request.provider,
            "target": request.target,
            "endpoint": scenario.endpoint,
            "payload": payload,
            "response": response,
        }
        _write_json(raw_path, raw)

        rows = _extract_items(response)
        export_format = _normalize_export_format(request.export_format)
        if export_format == "xlsx":
            export = export_rows_to_xlsx(
                rows=rows,
                output_path=root_dir / f"{job_id}.xlsx",
                target=request.target,
                site=site,
                period=period,
            )
        else:
            export = _export_rows_to_json(
                output_path=root_dir / f"{job_id}.json",
                job_id=job_id,
                request=request,
                site=site,
                period=period,
                rank_pattern=rank_pattern,
                rows=rows,
            )

        result = XiyouRankingResult(
            job_id=job_id,
            function=request.function,
            provider=request.provider,
            target=request.target,
            site=site,
            period=period,
            rank_pattern=rank_pattern,
            row_count=len(rows),
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            export=export,
            data=rows,
            warnings=[],
        )
        _write_json(result_path, result.to_dict())
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取已落盘任务状态。"""
        root_dir = self.settings.output_dir / job_id
        result_path = root_dir / "result.json"
        if not result_path.exists():
            raise XiyouConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _validate_request(self, request: XiyouRankingRequest) -> None:
        if (request.function or "").lower() != "ranking":
            raise XiyouConfigError("opscli xiyou run 目前仅支持功能：ranking")
        if (request.provider or DEFAULT_PROVIDER).lower() != DEFAULT_PROVIDER:
            raise XiyouConfigError("opscli xiyou run 目前仅支持 provider：xiyou")
        if request.period not in {"week", "month"}:
            raise XiyouConfigError("period 仅支持：week, month")
        if request.page <= 0:
            raise XiyouConfigError("page 必须为正整数")
        if request.page_size <= 0:
            raise XiyouConfigError("page_size 必须为正整数")

    def _build_root_dir(self, request: XiyouRankingRequest, job_id: str) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id


def _extract_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    """从常见响应结构中提取 rows。"""
    candidates: list[Any] = []
    if isinstance(response, dict):
        data = response.get("data")
        biz = response.get("biz")
        candidates.extend([response.get(key) for key in ["list", "items", "records", "rows", "data"]])
        candidates.extend([data, biz])
        if isinstance(data, dict):
            candidates.extend(data.get(key) for key in ["items", "list", "records", "rows", "data"])
        if isinstance(biz, dict):
            candidates.extend(biz.get(key) for key in ["items", "list", "records", "rows", "data"])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _build_job_id(function: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"xiyou-{function}-{timestamp}-{suffix}"


def _normalize_export_format(value: str) -> str:
    text = (value or "json").lower()
    if text in {"xls", "xlsx"}:
        return "xlsx"
    if text == "json":
        return "json"
    raise XiyouConfigError(f"不支持的导出格式：{value}")


def _export_rows_to_json(
    *,
    output_path: Path,
    job_id: str,
    request: XiyouRankingRequest,
    site: str,
    period: str,
    rank_pattern: str,
    rows: list[dict[str, Any]],
) -> XiyouExportResult:
    payload = {
        "job_id": job_id,
        "function": request.function,
        "provider": request.provider,
        "target": request.target,
        "site": site,
        "period": period,
        "rank_pattern": rank_pattern,
        "row_count": len(rows),
        "rows": rows,
        "warnings": [],
    }
    _write_json(output_path, payload)
    resolved_output = output_path.resolve()
    return XiyouExportResult(
        path=str(resolved_output),
        filename=resolved_output.name,
        url=resolved_output.as_uri(),
        format="json",
        mime_type="application/json",
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
