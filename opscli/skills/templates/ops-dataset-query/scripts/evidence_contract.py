#!/usr/bin/env python3
"""把查询返回 JSON 拍平为受限的证据与披露规划器（evidence_contract_v1）——随包薄壳。

算法唯一实现在内核 `opscli.query.services.planner.evidence_contract`（`opscli query flow`、
`opscli query chart --run`、MCP `query_flow` / `query_chart` 已内嵌同一实现）。本脚本只保留
命令行壳：读 stdin 或 `--input` 文件，调用内核函数，输出 JSON。不再携带第二份算法副本——
第二轮 E2E 验收实测随包旧副本对真实返回形状（`data[i].price`、驼峰 `rowCount`、
`"error": null`）输出空证据与恒定误导披露，与内核修复脱节。

输入：一次查询返回 JSON（对象）。
输出：required_evidence（结论必须引用的证据路径与原值）、
required_disclosures_zh（必须披露的中文事项）、
forbidden_inferences_zh（禁止做出的推断）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

try:
    from opscli.query.services.planner.evidence_contract import (
        MAX_EVIDENCE,
        build_evidence_contract,
    )
except ImportError as error:  # opscli 未安装到当前 Python 环境
    build_evidence_contract = None  # type: ignore[assignment]
    MAX_EVIDENCE = 24
    _IMPORT_ERROR = str(error)
else:
    _IMPORT_ERROR = ""


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """命令行参数：查询返回 JSON 默认从 stdin 读取，--input 可改从文件读取。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-evidence", type=int, default=MAX_EVIDENCE)
    parser.add_argument(
        "--input",
        default="",
        help="查询返回 JSON 文件路径；配合 opscli ... --run > result.json 落盘旁路，"
        "避免大结果两次占用模型上下文",
    )
    parser.add_argument(
        "--dataset-name-zh",
        default="",
        help="数据集中文名（规划合同 model_view.dataset_name_zh），返回体本身不带该信息",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """读取返回 JSON 并输出证据合同；内核不可导入时给出明确的环境提示而不是静默降级。"""
    args = _parse_args(argv)
    if build_evidence_contract is None:
        print(
            json.dumps(
                {
                    "error": f"evidence_contract_requires_opscli: {_IMPORT_ERROR}",
                    "hint_zh": "请使用安装了 opscli 的 Python 运行本脚本（如 .venv/bin/python 或 uv run python）",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()
        value = json.loads(raw)
        result = build_evidence_contract(
            value, args.max_evidence, dataset_name_zh=args.dataset_name_zh
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
