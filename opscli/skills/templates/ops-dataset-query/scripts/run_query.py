#!/usr/bin/env python3
"""一体化正式查询执行器：执行前静态校验 → 执行 → 排序兜底 → 披露 + 证据合同一次输出。

为什么需要（e2e 实测三类问题的收口）：
1. dataComparison 漏传主周期、占位符未替换、公式字段带普通聚合等构造错误
   靠提示词约束不稳定——执行前用代码硬校验，任一不过直接拒绝并给中文修正指引；
2. 已知服务端缺陷：orderBy 在部分形态下被静默吞掉、返回自然序切片，
   TopN 会「拿错行还披露自洽」——执行后做单调性校验，不生效时本地重排/加量重查兜底，
   并强制在披露中声明 order_fallback_applied；
3. 大结果两次过模型上下文（stdout 全量 + 管道回传 evidence）——全量结果落盘，
   stdout 只输出预览 + 披露 + 内嵌证据合同，单次输出限幅。

用法（规划器 ready 后的唯一执行入口）：
  python3 scripts/run_query.py --table-id 2 --json "$QUERY_JSON" --plan-file query-plan.json
  python3 scripts/run_query.py --table-id 2 --json-file payload.json --plan-file query-plan.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import core
import evidence_contract
import plan_integrity

# stdout 输出限幅：预览+披露+证据合同的总字节数护栏
MAX_STDOUT_BYTES = 8000
# 排序兜底重查时 limit 的放大倍数与硬上限
ORDER_REQUERY_MULTIPLIER = 3
ORDER_REQUERY_LIMIT_CAP = 5000
# 服务端默认分页补齐的硬上限：不传 limit 时服务端只回默认页（实测 20 行），
# 而合同里的 total_count 是全量行数——两者不一致时必须补齐，否则模型会把
# 「首页」当成「全量」写进结论（实测：38 行的结果被报成「共 20 个，未截断」）
AUTO_COMPLETE_LIMIT_CAP = 5000
# opscli 执行超时（秒）
EXEC_TIMEOUT_SECONDS = 300.0

# 占位符残留特征：$大写变量 或 <占位> 形态
PLACEHOLDER_RE = re.compile(r"\$[A-Z_]{3,}|<[^>]{1,40}>")


class PrecheckError(ValueError):
    """执行前校验失败：携带面向模型的中文修正指引。"""


def _parse_payload(raw: str) -> dict:
    """解析 payload JSON，失败时给出可执行的修正指引。"""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PrecheckError(f"payload 不是合法 JSON（{error.msg}，位置 {error.pos}）：修正 JSON 后重试。") from error
    if not isinstance(payload, dict):
        raise PrecheckError("payload 必须是 JSON 对象。")
    return payload


def _normalize_order_by(payload: dict) -> list[dict]:
    """归一 orderBy 形态：direction(DESC/ASC) 与 desc(bool/字符串) 两种写法统一。

    已验证可生效形态为 {"field","direction":"DESC|ASC"}；文档存在 {"field","desc"} 旧形态，
    这里统一改写为 direction 形态，消除「形状被服务端吞掉」的投喂面。
    """
    order_by = payload.get("orderBy")
    if not order_by:
        return []
    if not isinstance(order_by, list):
        raise PrecheckError('orderBy 必须是数组，形如 [{"field":"<结果alias>","direction":"DESC"}]。')
    normalized = []
    for item in order_by:
        if not isinstance(item, dict) or not item.get("field"):
            raise PrecheckError('orderBy 每项必须含 field，形如 [{"field":"<结果alias>","direction":"DESC"}]。')
        direction = item.get("direction")
        if direction is None and "desc" in item:
            raw = item.get("desc")
            desc = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("true", "desc", "1")
            direction = "DESC" if desc else "ASC"
        direction = str(direction or "ASC").upper()
        if direction not in ("ASC", "DESC"):
            raise PrecheckError(f"orderBy.direction 只能是 ASC/DESC，收到 {direction!r}。")
        normalized.append({"field": item["field"], "direction": direction})
    payload["orderBy"] = normalized
    return normalized


# filter_config 操作符 → 简化查询操作符（与规划器 query_template 预填映射一致）
_DEFAULT_FILTER_OP_MAP = {
    "equals": "=", "notEquals": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
}


def _apply_default_filters(payload: dict, defaults: list[dict]) -> list[str]:
    """生成数据集默认条件的中文披露说明（服务端权威注入，本函数只负责披露对齐，不改 payload）。

    架构背景（QA 评审结论 5）：服务端是默认条件注入的唯一权威方，日期预设值
    （如 beforeYesterday / thisQuarter）只由服务端在执行时刻解析成真实日期，
    客户端预注入会把字面量字符串写入 filters，服务端 AND 合并后永不匹配日期列
    → 配置了日期默认条件的数据集恒返回 0 行。

    本函数保留对用户的透明性披露（覆盖语义，2026-07 评审定稿）：
    - 用户没传该字段 → 提示服务端将自动应用数据集默认条件
    - 用户传了该字段（任意条件） → 提示用户条件将覆盖默认值
    - filter_agg != none 的度量 having 条件 → 提示服务端将按聚合后过滤应用
    - 日期预设值 → 原样展示，注明"服务端解析为执行日"

    旧"AND 冲突同时生效结果可能为空"语义已废弃：服务端改为覆盖语义，
    用户对某字段传了任意条件 → 服务端用用户的，不注入默认。

    payload 不被修改。返回中文披露行列表。
    """
    notes: list[str] = []
    # 读取用户已有 filters（只读，不写入）
    filters = payload.get("filters") or []
    for default in defaults or []:
        # filter_agg != none 的度量条件由服务端 having 兜底
        if default.get("filter_agg", "none") != "none":
            value_text = "、".join(str(v) for v in (default.get("values") or []))
            label = default.get("label_zh") or default.get("field_name", "")
            notes.append(f"服务端将按聚合后过滤应用默认条件：{label} = {value_text}（having）")
            continue
        op = _DEFAULT_FILTER_OP_MAP.get(default.get("operator", "equals"))
        if op is None:
            # isEmpty/isNotEmpty 等暂不支持的操作符：服务端兜底，仅披露
            continue
        field = default["field_name"]
        values = default.get("values") or []
        if not values:
            continue
        # 找出用户 payload 中已有的同字段条件（兼容 "table.field" 形式的 field 名）
        user_conditions = [f for f in filters if isinstance(f, dict)
                           and str(f.get("field", "")).split(".")[-1] == field]
        label = default.get("label_zh") or field
        # 日期预设值（如 beforeYesterday/thisQuarter）原样展示，注明服务端解析
        date_preset_keywords = {
            "beforeYesterday", "yesterday", "today", "thisWeek", "lastWeek",
            "thisMonth", "lastMonth", "thisQuarter", "lastQuarter", "thisYear", "lastYear",
        }
        value_texts = []
        for v in values:
            if str(v) in date_preset_keywords:
                value_texts.append(f"{v}（服务端解析为执行日）")
            else:
                value_texts.append(str(v))
        value_text = "、".join(value_texts)

        if default.get("type") == "optional":
            # optional 类型：用户已有同字段条件时，服务端用用户的（覆盖语义），不披露
            if user_conditions:
                continue
            # optional 且用户无该字段：服务端将应用默认
            notes.append(f"服务端将自动应用可选默认条件：{label} = {value_text}")
        elif user_conditions:
            # 覆盖语义：用户传了该字段的任意条件，服务端用用户的、不注入默认
            notes.append(f"你已为 {label} 指定条件，将覆盖数据集默认值（默认 {value_text}）")
        else:
            # required 且用户无该字段：服务端将自动应用默认条件
            notes.append(f"服务端将自动应用数据集默认条件：{label} = {value_text}（{default.get('type', 'required')}）")
    return notes


def _precheck(payload: dict) -> None:
    """执行前静态校验：把 simple-query-guide 的「执行前检查」从提示词变成代码。"""
    blob = json.dumps(payload, ensure_ascii=False)
    leftovers = PLACEHOLDER_RE.findall(blob)
    if leftovers:
        raise PrecheckError(f"payload 含未替换占位符 {leftovers[:3]}：全部替换为本次规划器真实值后重试。")
    if payload.get("dataComparison"):
        comparison = payload["dataComparison"]
        if not isinstance(comparison, dict) or not comparison.get("field"):
            raise PrecheckError("dataComparison 必须含 field（授权日期字段）。")
        date_field = comparison["field"]
        filters = payload.get("filters") or []
        has_main_period = any(
            isinstance(item, dict) and item.get("field") == date_field
            for item in filters
        )
        if not has_main_period:
            raise PrecheckError(
                f"传了 dataComparison 但 filters 缺少主周期日期条件（field={date_field}）："
                "补上 >= / <= 两行主周期过滤后重试，不得只传对比周期。"
            )
    for metric in payload.get("metrics") or []:
        if isinstance(metric, dict) and metric.get("expr") and metric.get("aggregation"):
            raise PrecheckError(
                f"公式指标 {metric.get('alias') or metric.get('field')} 同时带了 expr 与 aggregation："
                "公式字段不传普通聚合，删除 aggregation 后重试。"
            )
    _normalize_order_by(payload)


def _field_name(value: object) -> str:
    """归一 payload 字段引用，兼容 ``table.field`` 形态。"""
    return str(value or "").split(".")[-1]


def _validate_plan_binding(plan: dict, table_id: str, payload: dict) -> None:
    """把执行请求硬绑定到规划器的表、状态和授权字段集合。"""
    if plan.get("contract") != "query_plan_model_contract_v2":
        raise PrecheckError("plan 不是 query_plan_model_contract_v2 规划器输出。")
    if plan.get("status") != "planned":
        raise PrecheckError("plan 尚未达到 planned 状态：先完成规划器要求的澄清或恢复动作。")
    execution = plan.get("execution_ref")
    if not isinstance(execution, dict):
        raise PrecheckError("plan 缺少 execution_ref，禁止无授权引用执行。")
    if execution.get("plan_integrity") and not plan_integrity.verify(plan):
        raise PrecheckError("plan 完整性校验失败：禁止手工修改规划结果，请重新运行规划器。")
    planned_table = execution.get("table_id")
    if str(planned_table) != str(table_id):
        raise PrecheckError(
            f"--table-id 与规划器不一致：收到 {table_id}，规划器为 {planned_table}。"
        )
    payload_table = payload.get("tableId")
    if payload_table not in (None, "") and str(payload_table) != str(planned_table):
        raise PrecheckError(
            f"payload.tableId 与规划器不一致：收到 {payload_table}，规划器为 {planned_table}。"
        )
    if not isinstance(execution.get("query_template"), dict):
        raise PrecheckError(
            "规划器尚未下发 query_template：先完成默认时间、推荐字段或权限枚举确认。"
        )
    template = execution["query_template"]

    # 手工 payload 只允许补充排序、行数等执行参数；规划器确定的主周期和
    # 对比周期必须原样执行，避免“本月”在拼参时漂移成近 30 天。
    date_fields = {
        str(item.get("field_name"))
        for item in execution.get("date_fields") or []
        if isinstance(item, dict) and item.get("field_name")
    }

    def _time_filters(value: dict) -> list[dict]:
        return [
            item
            for item in value.get("filters") or []
            if isinstance(item, dict) and _field_name(item.get("field")) in date_fields
        ]

    if (
        _time_filters(payload) != _time_filters(template)
        or payload.get("dataComparison") != template.get("dataComparison")
    ):
        raise PrecheckError(
            "payload 时间范围与规划器不一致：主周期和对比周期禁止改写，请直接执行 query_template。"
        )
    if execution.get("plan_integrity"):
        for key in ("dimensions", "metrics", "filters"):
            if payload.get(key) != template.get(key):
                raise PrecheckError(
                    f"payload.{key} 与规划器原始模板不一致：只允许调整 orderBy 和 limit，"
                    "禁止删除筛选或改写字段。"
                )

    planned_dimensions = {
        str(item.get("field_name"))
        for item in execution.get("dimensions") or []
        if isinstance(item, dict) and item.get("field_name")
    }
    planned_metrics = {
        str(item.get("field_name"))
        for item in execution.get("metrics") or []
        if isinstance(item, dict) and item.get("field_name")
    }
    filter_fields = planned_dimensions | planned_metrics
    for key in ("date_fields", "filter_components", "default_filters"):
        filter_fields.update(
            str(item.get("field_name"))
            for item in execution.get(key) or []
            if isinstance(item, dict) and item.get("field_name")
        )
    platform_field = (execution.get("platform_component_alias") and "platform_name") or ""
    if platform_field:
        filter_fields.add(platform_field)

    def _assert_fields(entries: object, allowed: set[str], label: str) -> None:
        if entries is None:
            return
        if not isinstance(entries, list):
            raise PrecheckError(f"payload.{label} 必须是数组。")
        unknown = [
            _field_name(item.get("field"))
            for item in entries
            if isinstance(item, dict) and _field_name(item.get("field")) not in allowed
        ]
        if unknown:
            raise PrecheckError(
                f"payload.{label} 含规划器未授权字段 {unknown[:3]}：只能使用 execution_ref 中的字段。"
            )

    _assert_fields(payload.get("dimensions"), planned_dimensions, "dimensions")
    _assert_fields(payload.get("metrics"), planned_metrics, "metrics")
    _assert_fields(payload.get("filters"), filter_fields, "filters")
    comparison = payload.get("dataComparison")
    if isinstance(comparison, dict) and _field_name(comparison.get("field")) not in filter_fields:
        raise PrecheckError("dataComparison.field 不在规划器授权日期字段中。")


def _run_opscli(
    table_id: str, payload: dict, *, intent_code: str = "", selection_source: str = ""
) -> dict:
    """执行正式查询并解析返回 JSON（剥离升级提示等前缀噪声）。

    intent_code/selection_source 为可选的意图归因透传：当规划器（或降级路径）
    已经确定本次查询由哪条意图路由而来，就把它经 `--intent-code`/
    `--selection-source` 带给 `opscli query simple`，服务端据此落库统计
    "这条意图被真实执行了多少次"。留空时命令保持原样，不影响未接入意图路由的调用方。
    """
    try:
        command = [
            "opscli", "query", "simple",
            "--table-id", str(table_id),
            "--json", json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "--run",
        ]
        if intent_code:
            command.extend(
                ["--intent-code", intent_code, "--selection-source", selection_source or "local_fallback"]
            )
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=EXEC_TIMEOUT_SECONDS,
            **core.utf8_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"opscli_exec_failed:{error}") from error
    stdout = result.stdout or ""
    start = stdout.find("{")
    if start < 0:
        raise RuntimeError(f"opscli_no_json_output:{(result.stderr or stdout)[:200]}")
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError as error:
        raise RuntimeError(f"opscli_bad_json_output:{stdout[start:start + 200]}") from error


def _extract_rows(response: dict) -> tuple[list[dict], Any]:
    """从返回 JSON 兜底提取结果行与总行数（兼容多层形状）。"""
    rows: list = []
    for path in (("data", "result", "data"), ("result", "data"), ("data", "data")):
        node: Any = response
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list):
            rows = node
            break
    total = None
    data = response.get("data")
    if not isinstance(data, dict):
        data = {}
    result = data.get("result")
    if not isinstance(result, dict):
        result = {}
    meta = result.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    # QA 实测形状：总行数在 data.result.meta.totalCount；保留多层兜底兼容旧形状
    for key in ("totalCount", "total_count", "total", "rowCount"):
        for container in (meta, result, data, response):
            if isinstance(container, dict) and container.get(key) is not None:
                total = container[key]
                break
        if total is not None:
            break
    return [row for row in rows if isinstance(row, dict)], total


def _extract_currency(response: dict) -> str | None:
    """从返回 JSON 提取本次实际生效的币种代码（兼容多层形状）。

    服务端在 `meta.currency` 声明本次查询金额使用的币种（ISO 4217，如 CNY/USD）。
    实测存在 `data.result.meta`、`data.meta` 和顶层 `meta` 三种形状，逐层兜底取第一个
    非空字符串。该值必须进 stdout 的 disclosures：Agent 的金额结论要据此声明币种，
    只落在全量结果文件里会导致模型为了拿币种额外读一次文件，实际上往往被跳过。
    """
    for path in (("data", "result", "meta"), ("data", "meta"), ("meta",)):
        node: Any = response
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            currency = node.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return None


def _sort_value(value: Any) -> tuple[int, float | str]:
    """排序键归一：数值优先按数值比较，None 沉底。"""
    if value is None:
        return (2, "")
    if isinstance(value, (int, float)):
        return (0, float(value))
    text = str(value).replace(",", "")
    try:
        return (0, float(text))
    except ValueError:
        return (1, str(value))


def _is_monotonic(rows: list[dict], field: str, direction: str) -> bool:
    """校验结果行是否按声明字段单调（服务端排序是否真的生效）。"""
    values = [_sort_value(row.get(field)) for row in rows if field in row]
    if len(values) < 2:
        return True
    reverse = direction == "DESC"
    return values == sorted(values, reverse=reverse)


def _apply_order_fallback(
    table_id: str,
    payload: dict,
    rows: list[dict],
    order_by: list[dict],
    total: object = None,
    *,
    intent_code: str = "",
    selection_source: str = "",
) -> tuple[list[dict], dict | None]:
    """orderBy 未生效时的本地兜底（已知服务端缺陷的过渡方案）。

    - 无 limit：手上就是全量，单调即可证明服务端排序生效，否则本地重排；
    - 有 limit：单调**不能**作为判据（见下方注释），一律按总行数取全量后本地排序取前 N。
    返回 (修正后的行, 兜底披露信息或 None)。
    """
    primary = order_by[0]
    field, direction = primary["field"], primary["direction"]
    limit = payload.get("limit")
    # 带 limit 时切片单调只说明「这一片有序」，并不说明「这一片就是 Top N」——
    # 服务端整段忽略 orderBy 时返回的是自然序切片，而常量序列（如整片都是 0.0000）
    # 天然单调，判据会静默放过。实测：请求销售额 DESC 前 10，拿回 10 行全 0，
    # 而全量 193 行里存在 3176.76 的记录。因此只有无 limit 时才能用单调性下结论。
    if not limit and _is_monotonic(rows, field, direction):
        return rows, None
    note = {
        "order_fallback_applied": True,
        "order_field": field,
        "direction": direction,
    }
    if not limit:
        rows = sorted(rows, key=lambda row: _sort_value(row.get(field)), reverse=direction == "DESC")
        note["strategy"] = "local_resort"
        return rows, note
    # 有 limit：放大固定倍数仍是在错误的行里挑，必须按服务端报告的总行数取全量。
    # total 不可用时退回倍数放大，并在 strategy 里如实标注为尽力而为。
    try:
        span = int(str(total))
    except (TypeError, ValueError):
        span = 0
    exact = span > 0
    if not exact:
        span = int(limit) * ORDER_REQUERY_MULTIPLIER
    requery = dict(payload)
    requery["limit"] = min(span, ORDER_REQUERY_LIMIT_CAP)
    response = _run_opscli(
        table_id, requery, intent_code=intent_code, selection_source=selection_source
    )
    wide_rows, _total = _extract_rows(response)
    wide_rows = sorted(
        wide_rows, key=lambda row: _sort_value(row.get(field)), reverse=direction == "DESC"
    )
    corrected = wide_rows[: int(limit)]
    # 核对之后才能下结论：重查是为了「验证」而不是「假定」服务端排序失效。
    # 首查结果与本地算出的 Top N 一致时说明服务端排序本就生效，
    # 此时报 order_fallback_applied 会让 Agent 向用户披露一个并不存在的兜底。
    if corrected == rows:
        return rows, None
    note["strategy"] = f"requery_limit_{requery['limit']}_then_local_sort"
    # 取样口径必须可审计：未按全量重查时结论不能自称精确 Top N
    note["covers_full_result"] = bool(exact and span <= ORDER_REQUERY_LIMIT_CAP)
    return corrected, note


def _complete_server_paged_rows(
    table_id: str,
    payload: dict,
    rows: list[dict],
    total: object,
    *,
    intent_code: str = "",
    selection_source: str = "",
) -> tuple[list[dict], dict | None]:
    """用户未指定行数时，补齐服务端默认分页之外的剩余行。

    为什么必须补：服务端在 payload 不带 limit 时只返回默认页（实测 20 行），
    但 meta.totalCount 给的是全量行数。规划器模板恒填 limit=null，于是任何
    超过一页的查询都会静默只回首页——而模型拿到的 rows 看起来是完整的。
    这里显式重查一次并披露，避免把首页当全量。

    返回 (补齐后的行, 披露信息或 None)。
    """
    if payload.get("limit"):
        return rows, None  # 用户明确要了行数，按其口径执行，不擅自放大
    if not isinstance(total, int) or total <= len(rows):
        return rows, None
    requery = dict(payload)
    requery["limit"] = min(int(total), AUTO_COMPLETE_LIMIT_CAP)
    try:
        response = _run_opscli(
            table_id, requery, intent_code=intent_code, selection_source=selection_source
        )
    except RuntimeError as error:
        # 补齐失败不能把首页当全量，如实标记让上层披露
        return rows, {
            "auto_complete_applied": False,
            "reason": str(error)[:120],
            "server_default_page_rows": len(rows),
            "total_count": total,
        }
    full_rows, _total = _extract_rows(response)
    if len(full_rows) <= len(rows):
        return rows, {
            "auto_complete_applied": False,
            "reason": "requery_returned_no_more_rows",
            "server_default_page_rows": len(rows),
            "total_count": total,
        }
    return full_rows, {
        "auto_complete_applied": True,
        "server_default_page_rows": len(rows),
        "requery_limit": requery["limit"],
        "row_count_after_complete": len(full_rows),
    }


def _compact_preview(rows: list[dict], preview_rows: int) -> list[dict]:
    """预览行截断：只输出前 N 行，长字符串截断防撑爆。"""
    preview = []
    for row in rows[:preview_rows]:
        preview.append(
            {
                key: (value[:80] + "…" if isinstance(value, str) and len(value) > 80 else value)
                for key, value in row.items()
            }
        )
    return preview


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-id", default="")
    parser.add_argument("--json", default="", help="查询 payload JSON 字符串")
    parser.add_argument("--json-file", default="", help="payload 文件路径（- 为 stdin）")
    plan_group = parser.add_mutually_exclusive_group()
    plan_group.add_argument("--plan-json", default="", help="query_plan.py 的完整模型合同 JSON")
    plan_group.add_argument("--plan-file", default="", help="query_plan.py 模型合同文件路径")
    parser.add_argument(
        "--unsafe-unbound-plan",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--preview-rows", type=int, default=20)
    parser.add_argument("--no-evidence", action="store_true", help="不内嵌证据合同")
    parser.add_argument(
        "--no-order-fallback", action="store_true", help="不做排序生效校验与本地兜底"
    )
    parser.add_argument(
        "--result-dir", default=".", help="全量结果 JSON 落盘目录（默认当前目录）"
    )
    parser.add_argument(
        "--default-filters",
        default="",
        help="规划器 execution_ref.default_filters 的 JSON 数组，执行前自动注入缺失的 required 默认条件",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    # 入口先切 UTF-8 stdio：后续所有中文 JSON 输出都要能被 Agent 正确读取
    core.force_utf8_stdio()
    args = _parse_args(argv)
    try:
        if args.plan_file:
            plan_raw = core.read_text_auto(Path(args.plan_file))
        else:
            plan_raw = args.plan_json
        plan = _parse_payload(plan_raw) if plan_raw.strip() else None
        execution = plan.get("execution_ref") if isinstance(plan, dict) else None
        query_templates = (
            execution.get("query_templates") if isinstance(execution, dict) else None
        )
        if isinstance(query_templates, list) and len(query_templates) > 1:
            raise PrecheckError(
                "收到多币种规划：run_query 只能执行一个完整性绑定模板，请改用 "
                "query_flow.py 逐币种调用取数服务。"
            )

        if args.json_file:
            raw = sys.stdin.read() if args.json_file == "-" else core.read_text_auto(Path(args.json_file))
        else:
            raw = args.json
        if raw.strip():
            payload = _parse_payload(raw)
            payload_source = "manual_payload"
        elif plan:
            execution = plan.get("execution_ref")
            template = execution.get("query_template") if isinstance(execution, dict) else None
            if not isinstance(template, dict):
                raise PrecheckError(
                    "规划器尚未下发 query_template：先完成规划器要求的澄清或恢复动作。"
                )
            payload = json.loads(json.dumps(template, ensure_ascii=False))
            payload_source = "query_template"
        else:
            raise PrecheckError(
                "缺少 payload：传入 --plan-file 直接执行规划器模板，或用 --json/--json-file 传入查询参数。"
            )

        table_id = str(args.table_id or "")
        if plan:
            execution = plan.get("execution_ref")
            planned_table = execution.get("table_id") if isinstance(execution, dict) else None
            table_id = table_id or str(planned_table or "")
            _validate_plan_binding(plan, table_id, payload)
        elif not args.unsafe_unbound_plan:
            raise PrecheckError(
                "缺少规划器绑定：必须传 --plan-file 或 --plan-json，禁止绕过 query_plan.py 直接执行。"
            )
        if not table_id:
            raise PrecheckError("缺少 table-id：规划合同和 --table-id 均未提供数据集标识。")
        if payload.get("tableId") not in (None, "") and str(payload["tableId"]) != table_id:
            raise PrecheckError("payload.tableId 与 --table-id 不一致。")
        payload.setdefault("tableId", table_id)
        # 意图归因：从 plan.execution_ref 读取（降级路径由 local_fallback._emit_plan 写入），
        # 沿现有 plan 传参路径透传给下面所有 _run_opscli 调用，不新增独立传参通道
        intent_code = str(execution.get("intent_code") or "") if isinstance(execution, dict) else ""
        selection_source = (
            str(execution.get("selection_source") or "") if isinstance(execution, dict) else ""
        )
        # 生成规划器下发的数据集默认条件披露说明（服务端权威注入，本函数只读不写 payload）
        # 注意：默认条件实际注入由服务端完成，客户端不预注入，避免日期预设字面量冲突
        if args.default_filters.strip():
            default_filters = json.loads(args.default_filters)
        elif plan and isinstance(plan.get("execution_ref"), dict):
            default_filters = plan["execution_ref"].get("default_filters") or []
        else:
            default_filters = []
        default_notes = _apply_default_filters(payload, default_filters)
        _precheck(payload)
        order_by = payload.get("orderBy") or []

        response = _run_opscli(
            table_id, payload, intent_code=intent_code, selection_source=selection_source
        )
        if response.get("success") is False:
            error = response.get("error") or {}
            print(
                json.dumps(
                    {
                        "status": "query_failed",
                        "error": error,
                        "next_action_zh": (
                            "业务失败：按错误信息修正参数后重试；「未登录」时禁止交互式 "
                            "opscli auth login（沙箱凭证由平台注入），等待约1分钟重试一次后仍失败即停止并反馈。"
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            return 3

        rows, total = _extract_rows(response)
        # 服务端默认分页补齐必须在披露之前完成，否则 row_count_returned 是首页行数
        rows, auto_complete_note = _complete_server_paged_rows(
            table_id, payload, rows, total, intent_code=intent_code, selection_source=selection_source
        )
        disclosures: dict[str, Any] = {
            "row_count_returned": len(rows),
            "total_count": total,
            "limit": payload.get("limit"),
            # 截断判定只看「返回行数是否少于总行数」。旧实现要求 payload 必须带
            # limit 才算截断，导致服务端默认分页的截断被报成 truncated=false，
            # 模型据此把首页写成全量结论
            "truncated": total is not None and len(rows) < (total or 0),
        }
        # 币种披露：meta.currency 是服务端本次生效币种的唯一权威来源。有值必须让模型
        # 原样声明；没有值时明确要求「只能说未声明」，堵住按 _cny 后缀或经验猜币种的路径
        currency = _extract_currency(response)
        disclosures["currency"] = currency
        disclosures["currency_disclosure_zh"] = (
            f"本次金额币种为 {currency}：结论首句、结果表头和导出口径页必须写明该币种；"
            "禁止参考外部汇率折算或跨币种相加，需要其他币种时重新发起带币种意图的查询"
            if currency
            else "本次返回未声明币种：只能如实说明未声明，禁止按字段名后缀、数据集习惯或历史会话推断具体货币"
        )
        if auto_complete_note:
            disclosures["server_paging"] = auto_complete_note
            disclosures["server_paging_disclosure_zh"] = (
                "服务端未按 limit 返回全量：已自动重查补齐，结论按补齐后的行数陈述"
                if auto_complete_note.get("auto_complete_applied")
                else "服务端只返回了默认页且补齐失败：结论必须声明这是部分结果，禁止当作全量"
            )
        order_note = None
        if order_by and not args.no_order_fallback and rows:
            rows, order_note = _apply_order_fallback(
                table_id, payload, rows, order_by, total,
                intent_code=intent_code, selection_source=selection_source,
            )
            if order_note:
                disclosures["order_fallback"] = order_note
                # 重查窗口未覆盖全量时结论不能自称精确 Top N，必须把口径差异一并交代
                partial = "requery" in order_note["strategy"] and not order_note.get(
                    "covers_full_result"
                )
                disclosures["order_disclosure_zh"] = (
                    "服务端排序未生效（已知缺陷），本执行器已"
                    + (
                        "按总行数取全量后本地排序取前N"
                        if "requery" in order_note["strategy"]
                        else "本地重排"
                    )
                    + "，结论中必须披露该兜底行为"
                    + (
                        "；本次重查窗口未覆盖全部结果，前N可能不精确，必须如实声明"
                        if partial
                        else ""
                    )
                )
                # 本地重排后行数已按 limit 切片，披露口径必须同步刷新
                disclosures["row_count_returned"] = len(rows)
        if order_by and not order_note:
            disclosures["order_disclosure_zh"] = (
                f"排序已生效：按 {order_by[0]['field']} {order_by[0]['direction']}"
            )
        # 追加默认条件注入披露（有注入或冲突时才写入，保持 disclosures 简洁）
        if default_notes:
            disclosures["default_filters_zh"] = default_notes

        # 全量结果落盘：模型上下文只进预览，完整数据供导出/复核
        result_path = Path(args.result_dir) / f"query_result_{int(time.time())}.json"
        try:
            # 调用方常传一个尚不存在的子目录，旧实现直接 OSError 后把路径写成
            # null，模型既拿不到全量文件也不知道为什么，只能改写请求反复重查
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({**response, "rows_after_auto_complete": rows}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            disclosures["full_result_file"] = str(result_path)
        except OSError as error:
            disclosures["full_result_file"] = None
            disclosures["full_result_file_error"] = str(error)[:160]

        output: dict[str, Any] = {
            "status": "ok",
            "plan_execution": {
                "payload_source": payload_source,
                "integrity_verified": bool(
                    plan
                    and isinstance(plan.get("execution_ref"), dict)
                    and plan["execution_ref"].get("plan_integrity")
                    and plan_integrity.verify(plan)
                ),
            },
            "disclosures": disclosures,
            "preview_rows": _compact_preview(rows, args.preview_rows),
        }
        if not args.no_evidence:
            try:
                # 数据集中文名只有规划合同知道（查询返回体里没有任何 dataset* 键），
                # 不回填的话证据合同的 dataset_name_zh 恒为空，
                # 而结果分析的第一条要求正是「先说明数据集中文名」
                output["evidence_contract"] = evidence_contract.build_evidence_contract(
                    response,
                    dataset_name_zh=str(
                        ((plan or {}).get("model_view") or {}).get("dataset_name_zh", "")
                    ),
                )
            except Exception as error:  # noqa: BLE001 —— 证据合同失败不阻断查询结果
                output["evidence_contract_error"] = str(error)[:120]

        text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_STDOUT_BYTES:
            # 超限时按预览行数折半重试，保证 stdout 恒在限幅内
            while output["preview_rows"] and len(text.encode("utf-8")) > MAX_STDOUT_BYTES:
                output["preview_rows"] = output["preview_rows"][: max(1, len(output["preview_rows"]) // 2)]
                output["disclosures"]["preview_truncated_for_size"] = True
                text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write(text)
        return 0
    except PrecheckError as error:
        print(
            json.dumps(
                {"status": "precheck_failed", "next_action_zh": str(error)},
                ensure_ascii=False,
            )
        )
        return 2
    except Exception as error:  # noqa: BLE001 —— 未预期错误也要带指引，不裸 traceback
        print(
            json.dumps(
                {
                    "status": "executor_error",
                    "error": str(error)[:200],
                    "next_action_zh": (
                        "执行器异常：先原样重试一次；仍失败按 references/feedback-guide.md "
                        "提交一次反馈并停止，禁止绕过执行器直连。"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
