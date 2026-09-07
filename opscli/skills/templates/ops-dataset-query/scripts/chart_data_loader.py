"""图表数据加载工具 — CLI / MCP 共用。

提供从文件、opscli 命令获取图表数据和 dataComparison 环比数据的统一接口，
供 chart_map、chart_analyze、excel_export 等脚本复用。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import core


def load_chart_data_from_file(input_path: str) -> tuple[list[dict], str | None, dict | None]:
    """从文件加载 chart 数据（CLI / MCP 共用）。

    支持多种输入格式：
    - chart run 输出格式：{"data": {"queries": [...], "chart_uuid": "...", "merged": {...}}}
    - 普通 query build --run 输出格式：{"data": {"result": {...}}}
    - 直接 chart bundle：{"queries": [...]}
    - 直接 queries 数组：[{...}, ...]

    Args:
        input_path: JSON 文件路径

    Returns:
        (queries, chart_uuid, merged_data)
        - queries: 各 query 的数据列表（含 result）
        - chart_uuid: 图表 UUID
        - merged_data: 合并后的行数据
    """
    with open(input_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    if isinstance(content, dict) and "data" in content:
        data = content["data"]
        if isinstance(data, dict) and "queries" in data:
            # chart run 输出格式
            return data["queries"], data.get("chart_uuid"), data.get("merged")
        elif isinstance(data, dict) and "result" in data:
            # 普通 query build --run 输出格式
            rows = data["result"].get("data", [])
            return [{"index": 0, "result": data["result"]}], None, {"rows": rows}
    elif isinstance(content, dict) and "queries" in content:
        # 直接 chart bundle
        return content["queries"], content.get("chart_uuid"), content.get("merged")
    elif isinstance(content, list):
        # 直接 queries 数组
        return content, None, None

    return [], None, None


def load_chart_data_from_uuid(uuid_str: str, *, run: bool = True) -> tuple[list[dict], str | None, dict | None]:
    """通过 opscli 命令获取 chart 数据（仅 CLI 模式使用）。

    Args:
        uuid_str: 图表 UUID
        run: 是否同时执行查询（默认 True）

    Returns:
        (queries, chart_uuid, merged_data)
    """
    cmd = ["opscli", "query", "chart", "--uuid", uuid_str, "--pretty"]
    if run:
        cmd.append("--run")

    result = subprocess.run(
        cmd, capture_output=True, check=False, **core.utf8_subprocess_kwargs()
    )
    if result.returncode != 0:
        print(f"opscli 调用失败: {result.stderr}", file=sys.stderr)
        raise SystemExit(1)

    content = json.loads(result.stdout)
    chart_data = content.get("data", {})
    queries = chart_data.get("queries", [])
    chart_uuid = chart_data.get("chart_uuid")
    merged = chart_data.get("merged", {})
    return queries, chart_uuid, merged


def load_chart_data(
    uuid_str: str | None,
    input_path: str | None,
) -> tuple[list[dict], str | None, dict | None]:
    """统一入口：根据参数选择从 UUID 或文件加载图表数据。

    Args:
        uuid_str: 图表 UUID（CLI 模式）
        input_path: JSON 文件路径（CLI / MCP 均可）

    Returns:
        (queries, chart_uuid, merged_data)
    """
    if uuid_str:
        return load_chart_data_from_uuid(uuid_str)
    elif input_path:
        return load_chart_data_from_file(input_path)
    return [], None, None


def load_dc_data(dc_input: str | None) -> list[dict] | None:
    """加载 dataComparison 环比结果（CLI / MCP 共用）。

    Args:
        dc_input: DC 结果 JSON 文件路径

    Returns:
        行数据列表，或 None
    """
    if not dc_input:
        return None
    with open(dc_input, "r", encoding="utf-8") as f:
        content = json.load(f)
    # 兼容 opscli / MCP 输出包装格式
    if isinstance(content, dict) and "data" in content:
        data = content["data"]
        if isinstance(data, dict) and "result" in data:
            return data["result"].get("data", [])
        if isinstance(data, list):
            return data
    if isinstance(content, list):
        return content
    return None
