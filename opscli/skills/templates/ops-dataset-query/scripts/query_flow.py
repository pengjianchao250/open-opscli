#!/usr/bin/env python3
"""低调用一体化入口：一次规划，按规划模板调用一次或多次正式取数服务。"""

from __future__ import annotations

import argparse
import json
import tempfile
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import Sequence

import core
import plan_integrity
import query_plan
import run_query


def _execute_multi_currency(
    plan: dict,
    templates: list[dict],
    *,
    temp_dir: str,
    result_dir: Path | str,
    preview_rows: int,
) -> int:
    """逐币种执行完整性绑定模板，并把各服务端结果汇总为一个 JSON。"""
    if not plan_integrity.verify(plan):
        print(
            json.dumps(
                {
                    "status": "precheck_failed",
                    "next_action_zh": "多币种规划完整性校验失败：禁止拆分执行，请重新运行规划器。",
                },
                ensure_ascii=False,
            )
        )
        return 2
    currency_results: list[dict] = []
    exit_code = 0
    for index, template in enumerate(templates):
        currency = str(template.get("globalCurrency") or "").upper()
        # 每个子计划仍走 run_query 的完整性、字段和时间校验，避免多币种分支绕过闸门。
        currency_plan = deepcopy(plan)
        currency_plan["execution_ref"]["query_template"] = deepcopy(template)
        currency_plan["execution_ref"].pop("query_templates", None)
        plan_integrity.attach(currency_plan)
        plan_path = Path(temp_dir) / f"query-plan-{index}-{currency.lower()}.json"
        plan_path.write_text(
            json.dumps(currency_plan, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        buffer = StringIO()
        with redirect_stdout(buffer):
            current_code = run_query.main(
                [
                    "--plan-file",
                    str(plan_path),
                    "--result-dir",
                    str(Path(result_dir) / f"currency_{currency.lower()}"),
                    "--preview-rows",
                    str(preview_rows),
                ]
            )
        raw_output = buffer.getvalue().strip()
        try:
            output = json.loads(raw_output) if raw_output else {}
        except json.JSONDecodeError:
            output = {"status": "executor_output_invalid", "raw_output": raw_output[:500]}
            current_code = current_code or 2
        returned_currency = (output.get("disclosures") or {}).get("currency")
        currency_results.append(
            {
                "requested_currency": currency,
                "returned_currency": returned_currency,
                "currency_matches_request": returned_currency == currency,
                "result": output,
            }
        )
        if current_code and not exit_code:
            exit_code = current_code
            break

    queries_complete = len(currency_results) == len(templates) and not exit_code
    currency_validation_passed = queries_complete and all(
        item["currency_matches_request"] for item in currency_results
    )
    print(
        json.dumps(
            {
                "status": "ok" if not exit_code else "multi_currency_failed",
                "query_mode": "dataset_query",
                "multi_currency": True,
                "requested_global_currencies": [
                    str(item.get("globalCurrency") or "").upper() for item in templates
                ],
                "currency_results": currency_results,
                "comparison_contract": {
                    "service_queries_complete": queries_complete,
                    "currency_validation_passed": currency_validation_passed,
                    # 非金额指标不能仅凭字段名可靠识别，必须由 Agent 读取全量结果后核对。
                    "comparison_ready": False,
                    "alignment_validation_required": currency_validation_passed,
                    "rules_zh": [
                        "实际币种只认各结果 disclosures.currency；与请求不一致时停止金额对比并披露差异。",
                        "读取各 full_result_file 后，先确认共同维度键和非金额指标一致，再按共同维度关联。",
                        "金额只使用对应币种的服务端查询结果；禁止外部汇率、模型汇率或本地换算。",
                    ],
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return exit_code


def execute_flow(
    query: str,
    requested_fields: Sequence[str] = (),
    *,
    result_dir: Path | str = Path("."),
    preview_rows: int = 20,
    auto_upgrade: bool = True,
    auto_enum: bool = True,
) -> int:
    """规划一次；planned 数据集查询按币种模板数进入一次或多次执行。"""
    plan = query_plan.build_model_query_plan(
        query,
        requested_fields=requested_fields,
        auto_upgrade=auto_upgrade,
        auto_enum=auto_enum,
    )
    if plan.get("query_mode") != "dataset_query" or plan.get("status") != "planned":
        print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))
        return 0

    with tempfile.TemporaryDirectory(prefix="ops-dataset-query-") as temp_dir:
        execution = plan.get("execution_ref")
        templates = execution.get("query_templates") if isinstance(execution, dict) else None
        if isinstance(templates, list) and len(templates) > 1:
            return _execute_multi_currency(
                plan,
                templates,
                temp_dir=temp_dir,
                result_dir=result_dir,
                preview_rows=preview_rows,
            )
        plan_path = Path(temp_dir) / "query-plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return run_query.main(
            [
                "--plan-file",
                str(plan_path),
                "--result-dir",
                str(result_dir),
                "--preview-rows",
                str(preview_rows),
            ]
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="", help="用户原始查询")
    parser.add_argument("--query-file", default="", help="从 UTF-8 文件读取用户原始查询")
    parser.add_argument("--field", action="append", default=[], help="补充点名字段，可重复")
    parser.add_argument("--result-dir", default=".", help="完整查询结果落盘目录")
    parser.add_argument("--preview-rows", type=int, default=20)
    parser.add_argument("--no-auto-upgrade", action="store_true")
    parser.add_argument("--no-auto-enum", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：失败时返回简洁中文 JSON，避免裸 traceback。"""
    # 入口先切 UTF-8 stdio：一体化流程的中文 JSON 需被 Agent 原样读取
    core.force_utf8_stdio()
    args = _parse_args(argv)
    try:
        query = (
            Path(args.query_file).read_text(encoding="utf-8")
            if args.query_file
            else args.query
        ).strip()
        if not query:
            raise ValueError("缺少用户原始查询。")
        return execute_flow(
            query,
            requested_fields=args.field,
            result_dir=args.result_dir,
            preview_rows=args.preview_rows,
            auto_upgrade=not args.no_auto_upgrade,
            auto_enum=not args.no_auto_enum,
        )
    except Exception as error:  # noqa: BLE001 —— 入口需向 Agent 返回结构化恢复信息
        print(
            json.dumps(
                {
                    "status": "flow_error",
                    "error": str(error)[:200],
                    "next_action_zh": "保留用户原始查询重试一次；仍失败则按反馈规范提交并停止。",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
