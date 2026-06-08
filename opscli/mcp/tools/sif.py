"""Sif MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg


async def sif_spec_must_read() -> dict:
    """Read the built-in Sif MCP usage spec."""
    spec_path = Path(__file__).resolve().parents[2] / "skills" / "templates" / "ops-sif" / "SKILL_MCP.md"
    if not spec_path.exists():
        spec_path = Path(__file__).resolve().parents[2] / "skills" / "templates" / "ops-sif" / "SKILL.md"
    if not spec_path.exists():
        return _err(
            FileNotFoundError(f"Sif MCP 规范文档不存在：{spec_path}"),
            tool="MCP -> sif_spec_must_read()",
        )
    try:
        return _ok({"spec": spec_path.read_text(encoding="utf-8"), "source": str(spec_path)})
    except Exception as exc:
        return _err(exc, tool="MCP -> sif_spec_must_read()")


async def sif_scenarios() -> dict:
    """List supported Sif MCP features and sections."""
    try:
        from opscli.sif.services import SifServiceManager

        return _ok(SifServiceManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP -> sif_scenarios()")


async def sif_accounts(
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """List configured Sif account summaries without passwords."""
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    try:
        from opscli.sif.services import SifServiceManager

        return _ok(SifServiceManager(jwt=jw, session_id=sid).accounts())
    except Exception as exc:
        return _err(exc, tool="MCP -> sif_accounts(...)")


async def sif_run(
    feature: str,
    asin: str = "",
    site: str = "US",
    sections: list[str] | str | None = None,
    asins: list[str] | str | None = None,
    time_piece_type: str | None = None,
    time_piece_value: str | None = None,
    my_asin: str | None = None,
    page_num: int = 1,
    page_size: int | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    timeout: float = 60.0,
    params: dict[str, Any] | str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """Run a Sif feature and return generated XLSX export links."""
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    call_params = {
        "feature": feature,
        "asin": asin,
        "site": site,
        "sections": sections,
        "time_piece_type": time_piece_type,
        "time_piece_value": time_piece_value,
        "page_num": page_num,
        "page_size": page_size,
        "job_id": job_id,
    }
    try:
        from opscli.sif.domain.models import SifRunRequest
        from opscli.sif.services import SifServiceManager
        from opscli.sif.services.manager import decorate_download_payload

        parsed_params = _parse_json_arg(params, dict) or {}
        parsed_asins = _parse_list_arg(asins)
        asin_value = asin.strip() if isinstance(asin, str) else ""
        if parsed_asins:
            asin_value = ",".join(parsed_asins)
        parsed_sections = _parse_list_arg(sections)
        request = SifRunRequest(
            feature=feature,
            asin=asin_value,
            site=site,
            asins=parsed_asins,
            time_piece_type=time_piece_type or _default_time_piece_type(feature),
            time_piece_value=str(time_piece_value or _default_time_piece_value(feature)),
            sections=parsed_sections,
            my_asin=my_asin,
            page_num=page_num,
            page_size=page_size,
            output_dir=output_dir,
            job_id=job_id,
            timeout=timeout,
            params=parsed_params,
        )
        result = SifServiceManager(jwt=jw, session_id=sid).run(request)
        return _ok(decorate_download_payload(result.to_dict()))
    except Exception as exc:
        return _err(exc, tool="MCP -> sif_run(...)", call_params=call_params)


async def sif_job_status(
    job_id: str,
    output_dir: str | None = None,
) -> dict:
    """Read a Sif job result."""
    try:
        from opscli.sif.services import SifServiceManager
        from opscli.sif.services.manager import decorate_download_payload

        return _ok(decorate_download_payload(SifServiceManager().job_status(job_id, output_dir=output_dir)))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP -> sif_job_status(...)",
            call_params={"job_id": job_id, "output_dir": output_dir},
        )


async def sif_export(
    job_id: str,
    export_key: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Return one or all Sif export file links for a job."""
    try:
        from opscli.sif.services import SifServiceManager
        from opscli.sif.services.manager import decorate_download_payload

        payload = SifServiceManager().export(job_id, export_key=export_key, output_dir=output_dir)
        return _ok(_decorate_export_response(payload, decorate_download_payload))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP -> sif_export(...)",
            call_params={"job_id": job_id, "export_key": export_key, "output_dir": output_dir},
        )


def _parse_list_arg(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = _parse_json_arg(text, list)
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _decorate_export_response(payload: dict[str, Any], decorate_download_payload) -> dict[str, Any]:
    if isinstance(payload.get("exports"), dict):
        return decorate_download_payload(payload)
    wrapper = {"exports": {"export": payload}}
    decorate_download_payload(wrapper)
    return wrapper["exports"]["export"]


def _default_time_piece_type(feature: str) -> str:
    return "latelyDay"


def _default_time_piece_value(feature: str) -> str:
    normalized = (feature or "").strip().lower()
    if normalized in {"查销量", "sales"}:
        return "30"
    return "7"


_ALL_TOOLS = [
    sif_spec_must_read,
    sif_scenarios,
    sif_accounts,
    sif_run,
    sif_job_status,
    sif_export,
]


def register(mcp) -> None:
    """Register Sif tools on a FastMCP instance."""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
