"""新品计算器 JSON payload 辅助函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_file(path: str | Path) -> dict[str, Any]:
    """读取 JSON 对象文件。"""
    file_path = Path(path)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON 文件必须是对象格式。")
    return data


def write_json_file(path: str | Path, payload: dict[str, Any]) -> None:
    """以稳定格式写入 JSON 对象文件。"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_query_payload(
    *,
    country: str | None,
    platforms: list[int] | None,
    hs_code_id: int | None,
    department: str | None,
    reference: str,
    reference_value: str | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """构造 queryCost 第一阶段请求参数。"""
    if payload is not None:
        source = dict(payload)
        result = {
            "country_code": source.get("country_code"),
            "platforms": source.get("platforms", []),
            "hs_code_id": source.get("hs_code_id"),
            "department": source.get("department"),
            "reference": source.get("reference", "NONE"),
            "reference_value": source.get("reference_value"),
        }
    else:
        result = {
            "country_code": country,
            "platforms": platforms or [],
            "hs_code_id": hs_code_id,
            "department": department,
            "reference": reference,
            "reference_value": reference_value,
        }
    missing = [key for key in ("country_code", "platforms", "hs_code_id") if not result.get(key)]
    if missing:
        raise ValueError("缺少第一阶段必填参数：" + "、".join(missing))
    return result
