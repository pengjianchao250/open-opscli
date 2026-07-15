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
  python3 scripts/run_query.py --table-id 2 --json "$QUERY_JSON" [--preview-rows 20] [--no-evidence]
  python3 scripts/run_query.py --table-id 2 --json-file payload.json
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

import evidence_contract

# stdout 输出限幅：预览+披露+证据合同的总字节数护栏
MAX_STDOUT_BYTES = 8000
# 排序兜底重查时 limit 的放大倍数与硬上限
ORDER_REQUERY_MULTIPLIER = 3
ORDER_REQUERY_LIMIT_CAP = 5000
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

    本函数保留对用户的透明性披露：
    - required 且用户无该字段 → 提示服务端将自动应用
    - required 且用户同字段同值/子集 → 提示"与你的条件一致"
    - required 且用户同字段冲突 → 提示"同时生效（AND），结果可能为空"
    - optional 且用户已有 → 提示用户条件优先（跳过）
    - filter_agg != none 的度量 having 条件 → 提示服务端将按聚合后过滤应用
    - 日期预设值 → 原样展示，注明"服务端解析为执行日"

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
            # optional 类型：用户已有同字段条件时，用户条件优先，不披露
            if user_conditions:
                continue
            # optional 且用户无该字段：服务端将应用
            notes.append(f"服务端将自动应用可选默认条件：{label} = {value_text}")
        elif user_conditions:
            # required + 用户同字段：判断是同值/子集（去重）还是冲突（AND 合并）
            # 去重仅适用等值语义（=/in）：异操作符（如 !=）属冲突场景，AND 合并保留并披露（终审修复）
            equality_ops = {"=", "==", "in"}
            covered = any(
                str(c.get("operator", "")) in equality_ops
                and set(c["value"] if isinstance(c.get("value"), list) else [c.get("value")]) <= set(values)
                for c in user_conditions
            )
            if covered:
                notes.append(f"默认条件 {label}={value_text} 与你的条件一致，已去重")
            else:
                # 冲突：服务端将 AND 合并，必须披露
                notes.append(
                    f"[!] 数据集强制默认条件 {label}={value_text} 与你的条件同时生效（AND），结果可能为空"
                )
        else:
            # required 且用户无该字段：服务端将自动注入
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


def _run_opscli(table_id: str, payload: dict) -> dict:
    """执行正式查询并解析返回 JSON（剥离升级提示等前缀噪声）。"""
    try:
        result = subprocess.run(
            [
                "opscli", "query", "simple",
                "--table-id", str(table_id),
                "--json", json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "--run",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=EXEC_TIMEOUT_SECONDS,
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
) -> tuple[list[dict], dict | None]:
    """orderBy 未生效时的本地兜底（已知服务端缺陷的过渡方案）。

    - 无 limit：直接本地重排；
    - 有 limit：切片可能已取错行，放大 limit 重查后本地排序取前 N；
    返回 (修正后的行, 兜底披露信息或 None)。
    """
    primary = order_by[0]
    field, direction = primary["field"], primary["direction"]
    if _is_monotonic(rows, field, direction):
        return rows, None
    limit = payload.get("limit")
    note = {
        "order_fallback_applied": True,
        "order_field": field,
        "direction": direction,
    }
    if not limit:
        rows = sorted(rows, key=lambda row: _sort_value(row.get(field)), reverse=direction == "DESC")
        note["strategy"] = "local_resort"
        return rows, note
    # 有 limit：加大窗口重查再本地排序切片
    requery = dict(payload)
    requery["limit"] = min(int(limit) * ORDER_REQUERY_MULTIPLIER, ORDER_REQUERY_LIMIT_CAP)
    response = _run_opscli(table_id, requery)
    wide_rows, _total = _extract_rows(response)
    wide_rows = sorted(
        wide_rows, key=lambda row: _sort_value(row.get(field)), reverse=direction == "DESC"
    )
    note["strategy"] = f"requery_limit_{requery['limit']}_then_local_sort"
    return wide_rows[: int(limit)], note


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
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--json", default="", help="查询 payload JSON 字符串")
    parser.add_argument("--json-file", default="", help="payload 文件路径（- 为 stdin）")
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
    args = _parse_args(argv)
    try:
        if args.json_file:
            raw = sys.stdin.read() if args.json_file == "-" else Path(args.json_file).read_text(encoding="utf-8")
        else:
            raw = args.json
        if not raw.strip():
            raise PrecheckError("缺少 payload：用 --json 或 --json-file 传入查询参数。")
        payload = _parse_payload(raw)
        payload.setdefault("tableId", args.table_id)
        # 生成规划器下发的数据集默认条件披露说明（服务端权威注入，本函数只读不写 payload）
        # 注意：默认条件实际注入由服务端完成，客户端不预注入，避免日期预设字面量冲突
        default_filters = json.loads(args.default_filters) if args.default_filters.strip() else []
        default_notes = _apply_default_filters(payload, default_filters)
        _precheck(payload)
        order_by = payload.get("orderBy") or []

        response = _run_opscli(args.table_id, payload)
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
        disclosures: dict[str, Any] = {
            "row_count_returned": len(rows),
            "total_count": total,
            "limit": payload.get("limit"),
            "truncated": bool(payload.get("limit")) and total is not None and len(rows) < (total or 0),
        }
        order_note = None
        if order_by and not args.no_order_fallback and rows:
            rows, order_note = _apply_order_fallback(args.table_id, payload, rows, order_by)
            if order_note:
                disclosures["order_fallback"] = order_note
                disclosures["order_disclosure_zh"] = (
                    "服务端排序未生效（已知缺陷），本执行器已"
                    + ("放大窗口重查并本地排序取前N" if "requery" in order_note["strategy"] else "本地重排")
                    + "，结论中必须披露该兜底行为"
                )
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
            result_path.write_text(
                json.dumps(response, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            disclosures["full_result_file"] = str(result_path)
        except OSError:
            disclosures["full_result_file"] = None

        output: dict[str, Any] = {
            "status": "ok",
            "disclosures": disclosures,
            "preview_rows": _compact_preview(rows, args.preview_rows),
        }
        if not args.no_evidence:
            try:
                output["evidence_contract"] = evidence_contract.build_evidence_contract(response)
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
                        "执行器异常：先原样重试一次；仍失败改用 opscli query simple 直连执行，"
                        "并按 references/feedback-guide.md 提交一次反馈。"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
