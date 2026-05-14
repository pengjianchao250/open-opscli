#!/usr/bin/env python3
"""Analysis View 运行入口。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_error(message: str, *, code: str = "VIEW_RUN_ERROR") -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message}}


def _get(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]
    return default


def _load_params(params_text: str | None, params_file: str | None) -> dict[str, Any]:
    if params_text and params_file:
        raise ValueError("--params 和 --params-file 只能使用一种")
    if params_file:
        file_path = Path(params_file).expanduser()
        if not file_path.exists():
            raise ValueError(f"参数文件不存在: {file_path}")
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    elif params_text:
        payload = json.loads(params_text)
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("运行时参数必须是 JSON 对象")
    return payload


def _fetch_view_detail(view_id: str) -> dict[str, Any]:
    try:
        import httpx
        from opscli.auth import AuthClient, OPS_URL
        from opscli.query.domain.exceptions import BadRemoteJsonError, RemoteBusinessError, RemoteHttpError
        from opscli.shared.http import parse_remote_response
    except Exception as exc:
        raise RuntimeError("缺少 opscli 运行环境，请先安装 aukeys-opscli") from exc

    headers, cookies = AuthClient().build_request_auth("ops")
    response = httpx.get(
        f"{OPS_URL.rstrip('/')}/v1/ai/cli-view/{view_id}",
        headers=headers,
        cookies=cookies,
        timeout=20,
    )
    payload = parse_remote_response(
        response,
        http_error_cls=RemoteHttpError,
        business_error_cls=RemoteBusinessError,
        bad_json_error_cls=BadRemoteJsonError,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("视图详情接口返回 data 不是对象")
    return data


def _content(view_detail: dict[str, Any]) -> dict[str, Any]:
    detail = view_detail.get("detail")
    if not isinstance(detail, dict):
        raise ValueError("视图不存在 detail")
    content = detail.get("content")
    if not isinstance(content, dict):
        raise ValueError("视图 detail.content 不是对象")
    return content


def _view_name(view_detail: dict[str, Any], content: dict[str, Any]) -> str:
    card = view_detail.get("card") if isinstance(view_detail.get("card"), dict) else {}
    return str(_get(content, "name", default=None) or _get(card, "view_name", "viewName", default="视图数据"))


def _input_schema(content: dict[str, Any]) -> dict[str, Any]:
    schema = _get(content, "inputSchema", "input_schema", default={})
    return schema if isinstance(schema, dict) else {}


def _required_schema(content: dict[str, Any]) -> dict[str, Any]:
    required = _get(_input_schema(content), "required", default={})
    return required if isinstance(required, dict) else {}


def _source(content: dict[str, Any]) -> dict[str, Any]:
    source = content.get("source")
    if not isinstance(source, dict):
        raise ValueError("视图 source 不是对象")
    return source


def _chart_info(source: dict[str, Any]) -> dict[str, Any]:
    chart_info = _get(source, "chartInfo", "chart_info", default={})
    return chart_info if isinstance(chart_info, dict) else {}


def _chart_uuid(source: dict[str, Any]) -> str:
    chart_info = _chart_info(source)
    chart_uuid = (
        _get(source, "chartId", "chart_id", default=None)
        or _get(chart_info, "chartId", "chart_id", default=None)
    )
    if not chart_uuid:
        raise ValueError("视图未配置 source.chartId/source.chartInfo.chartId")
    return str(chart_uuid)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def _missing_required(content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for field, config in _required_schema(content).items():
        if not isinstance(config, dict):
            config = {}
        if _is_missing(params.get(field)):
            missing.append(
                {
                    "field": field,
                    "type": str(config.get("type") or "string"),
                    "description": str(config.get("description") or field),
                    **({"values": config.get("values")} if config.get("values") else {}),
                }
            )
    return missing


def _field_id(rule: dict[str, Any]) -> str:
    return str(rule.get("fieldId") or rule.get("field_id") or rule.get("field") or "").strip()


def _field_type_from_schema(config: dict[str, Any], fallback: Any = None) -> str:
    value = str(config.get("type") or fallback or "text").lower()
    if value in ("date", "date_range") or "time" in value:
        return "datetime"
    if value in ("enum", "single_select", "singleSelect"):
        return "singleSelect"
    if value in ("number", "currency", "percent"):
        return "number"
    return value if value in ("datetime", "text", "number") else "text"


def _normalize_frontend_rule(rule: dict[str, Any], config: dict[str, Any], value: Any) -> dict[str, Any]:
    next_rule = deepcopy(rule)
    field_id = _field_id(rule)
    field_type = str(next_rule.get("type") or next_rule.get("fieldType") or next_rule.get("field_type") or "")
    if not field_type:
        field_type = _field_type_from_schema(config)
    title = str(next_rule.get("title") or config.get("description") or field_id)
    if field_id:
        next_rule["field"] = field_id
        next_rule["fieldId"] = field_id
    next_rule["title"] = title
    next_rule["originalTitle"] = next_rule.get("originalTitle") or title
    next_rule["type"] = field_type
    next_rule["fieldType"] = field_type
    next_rule["operator"] = rule.get("operator") or next_rule.get("operator") or "equals"
    next_rule["dateOperator"] = rule.get("dateOperator") or rule.get("date_operator") or next_rule.get("dateOperator") or "exact"
    next_rule["filterType"] = rule.get("filterType") or rule.get("filter_type") or next_rule.get("filterType") or "logic"
    next_rule["enumValue"] = rule.get("enumValue") or rule.get("enum_value") or next_rule.get("enumValue") or []
    next_rule["value"] = value
    return next_rule


def _apply_params_to_filter_rule(content: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    source = _source(content)
    chart_info = _chart_info(source)
    filter_rule = deepcopy(_get(chart_info, "filterRule", "filter_rule", default=None))
    if not isinstance(filter_rule, dict):
        filter_rule = {"logic": "and", "rules": []}
    rules = filter_rule.get("rules")
    if not isinstance(rules, list):
        rules = []
        filter_rule["rules"] = rules

    seen: set[str] = set()
    required_schema = _required_schema(content)
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        fid = _field_id(rule)
        if fid and fid in params:
            config = required_schema.get(fid) if isinstance(required_schema.get(fid), dict) else {}
            original_rule = deepcopy(rule)
            rule.clear()
            rule.update(_normalize_frontend_rule(original_rule | {"fieldId": fid}, config, params[fid]))
            seen.add(fid)

    for field in required_schema:
        if field not in params or field in seen:
            continue
        config = required_schema.get(field) if isinstance(required_schema.get(field), dict) else {}
        rules.append(_normalize_frontend_rule({"fieldId": field}, config, params[field]))
    return filter_rule


def _empty_params_for_required(content: dict[str, Any]) -> dict[str, str]:
    """为必填参数生成空值，允许调试时直接运行无筛选视图。"""
    return {field: "" for field in _required_schema(content)}


def _saved_params_from_filter_rule(content: dict[str, Any]) -> dict[str, Any]:
    """从视图保存的 filterRule 中提取默认参数值。"""
    source = _source(content)
    chart_info = _chart_info(source)
    filter_rule = _get(chart_info, "filterRule", "filter_rule", default={})
    if not isinstance(filter_rule, dict):
        return {}

    params: dict[str, Any] = {}
    for rule in filter_rule.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        fid = _field_id(rule)
        if not fid or "value" not in rule:
            continue
        params[fid] = rule.get("value")
    return params


def _skill_root_from_scripts_dir(scripts_dir: Path) -> Path:
    return scripts_dir.resolve().parent


def _find_view_data_script(skills_dir: str | None = None) -> Path:
    current_skill_root = _skill_root_from_scripts_dir(Path(__file__).resolve().parent)
    candidates: list[Path] = []
    if skills_dir:
        candidates.append(Path(skills_dir).expanduser() / "ops-cli-view-data" / "scripts" / "export_view_data.py")
    candidates.extend(
        [
            current_skill_root.parent / "ops-cli-view-data" / "scripts" / "export_view_data.py",
            Path.cwd() / ".claude" / "skills" / "ops-cli-view-data" / "scripts" / "export_view_data.py",
            Path.home() / ".claude" / "skills" / "ops-cli-view-data" / "scripts" / "export_view_data.py",
            Path.home() / ".openclaw" / "skills" / "ops-cli-view-data" / "scripts" / "export_view_data.py",
            Path.home() / ".codex" / "skills" / "ops-cli-view-data" / "scripts" / "export_view_data.py",
            Path.home() / ".config" / "opencode" / "skills" / "ops-cli-view-data" / "scripts" / "export_view_data.py",
            Path(__file__).resolve().parents[2] / "ops-cli-view-data" / "scripts" / "export_view_data.py",
        ]
    )
    for script in candidates:
        if script.exists():
            return script
    raise RuntimeError("未找到 ops-cli-view-data，请先安装该 Skill")


def _run_data_skill(
    script: Path,
    *,
    chart_uuid: str,
    filter_rule_file: Path,
    output: str,
    sheet_name: str,
    skills_dir: str | None,
    pretty: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(script),
        "--chart-uuid",
        chart_uuid,
        "--filter-rule",
        str(filter_rule_file),
        "--output",
        output,
        "--sheet-name",
        sheet_name,
    ]
    if skills_dir:
        command.extend(["--skills-dir", skills_dir])
    if pretty:
        command.append("--pretty")

    result = subprocess.run(command, cwd=str(script.parent), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "ops-cli-view-data 执行失败"
        raise RuntimeError(message)
    payload = json.loads(result.stdout)
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(str(payload.get("error") or payload))
    return payload


def _default_output_path(view_id: str) -> str:
    """生成带时间戳的默认导出文件名，避免重复运行覆盖旧文件。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(Path.cwd() / f"analysis-view-{view_id}-{timestamp}.xlsx")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Analysis View 并导出 Excel")
    parser.add_argument("--view-id", required=True, help="Analysis View 自增 ID")
    parser.add_argument("--params", help="运行时参数 JSON 字符串")
    parser.add_argument("--params-file", help="运行时参数 JSON 文件")
    parser.add_argument("--output", default="", help="Excel 输出路径")
    parser.add_argument("--sheet-name", default="", help="Sheet 名称")
    parser.add_argument("--skills-dir", help="Skill 安装根目录")
    parser.add_argument("--allow-empty-params", action="store_true", help="允许必填参数为空，直接执行视图")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        explicit_params = _load_params(args.params, args.params_file)
        view_detail = _fetch_view_detail(str(args.view_id))
        content = _content(view_detail)
        params = {**_saved_params_from_filter_rule(content), **explicit_params}
        if args.allow_empty_params:
            params = {**_empty_params_for_required(content), **params}
        missing = [] if args.allow_empty_params else _missing_required(content, params)
        view_name = _view_name(view_detail, content)
        if missing:
            result = {
                "success": False,
                "needs_input": True,
                "view_id": args.view_id,
                "view_name": view_name,
                "missing": missing,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
            return

        source = _source(content)
        chart_uuid = _chart_uuid(source)
        filter_rule = _apply_params_to_filter_rule(content, params)
        output = args.output or _default_output_path(str(args.view_id))
        sheet_name = args.sheet_name or view_name[:31] or "视图数据"
        data_script = _find_view_data_script(args.skills_dir)

        with tempfile.TemporaryDirectory(prefix="ops-cli-view-runner-") as tmp:
            filter_rule_file = Path(tmp) / "filter_rule.json"
            filter_rule_file.write_text(json.dumps(filter_rule, ensure_ascii=False, indent=2), encoding="utf-8")
            data_result = _run_data_skill(
                data_script,
                chart_uuid=chart_uuid,
                filter_rule_file=filter_rule_file,
                output=output,
                sheet_name=sheet_name,
                skills_dir=args.skills_dir,
                pretty=args.pretty,
            )

        result = {
            "success": True,
            "view_id": args.view_id,
            "view_name": view_name,
            "chart_uuid": chart_uuid,
            "excel": data_result.get("excel", data_result),
            "data": data_result,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    except Exception as exc:
        print(json.dumps(_json_error(str(exc)), ensure_ascii=False, indent=2 if args.pretty else None), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
