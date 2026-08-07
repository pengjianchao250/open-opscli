#!/usr/bin/env python3
"""拉取当前账号各组件字段的真实授权枚举值，落盘供碰撞扫描复用。

为什么要单独一步：枚举要走远端、耗时且按账号变化，而碰撞扫描本身是纯计算。
拆开后扫描可以反复跑而不重复付出网络开销。

组件表取自 dataset_select_columns.csv 全量——规划合同里的 filter_components
是按查询相关性排序后截断的，不能用于扫描。

用法：
    python3 scripts/regression/planner_enum_snapshot.py [输出路径] [--skill-dir DIR]

默认输出 ./planner_enums.snapshot.json，默认读 ~/.opscli/skills/ops-dataset-query。
需本地登录态（opscli auth token status 显示已登录）。
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

DEFAULT_SKILL_DIR = pathlib.Path.home() / ".opscli/skills/ops-dataset-query"
# 即时综合数据集：组件最全，作为扫描的取样数据集
DEFAULT_DATASET_ALIAS = "ds_d35ac6f3910c"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", default="planner_enums.snapshot.json", help="快照输出路径"
    )
    parser.add_argument(
        "--skill-dir", default=str(DEFAULT_SKILL_DIR), help="已安装 Skill 根目录"
    )
    parser.add_argument(
        "--dataset-alias", default=DEFAULT_DATASET_ALIAS, help="取样数据集 alias"
    )
    args = parser.parse_args()

    skill_dir = pathlib.Path(args.skill_dir).expanduser()
    scripts_dir = skill_dir / "scripts"
    data_dir = skill_dir / "data"
    if not (scripts_dir / "query_plan.py").is_file():
        print(f"未找到已安装的 Skill 脚本: {scripts_dir}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(scripts_dir))
    import query_plan as qp  # noqa: PLC0415

    # alias → table_id
    alias_to_table = {}
    with (data_dir / "datasets.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            alias_to_table[row.get("dataset_alias")] = row.get("table_id")

    # 该数据集每个筛选列对应的组件数据集
    components: dict[str, str | None] = {}
    with (data_dir / "dataset_select_columns.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("current_dataset_alias") != args.dataset_alias:
                continue
            column = row.get("column_name")
            component_alias = row.get("component_dataset_alias")
            if column and component_alias:
                components[column] = alias_to_table.get(component_alias)

    print(f"该数据集筛选组件 {len(components)} 个")

    result: dict[str, dict] = {}
    for spec in qp._ENUM_COMPONENT_SPECS:
        field = spec["field_name"]
        table_id = components.get(field)
        if not table_id:
            result[field] = {"label_zh": spec.get("label_zh"), "values": [], "note": "无组件"}
            print(f"  {field:<18} 无组件")
            continue
        errors: list = []
        values = qp._auto_enum_component_values(table_id, field, errors=errors)
        result[field] = {
            "label_zh": spec.get("label_zh"),
            "table_id": table_id,
            "values": values,
            "errors": errors,
        }
        print(f"  {field:<18} n={len(values):<5} {('错误: ' + str(errors[:1])) if errors else ''}")

    out = pathlib.Path(args.output)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(item.get("values") or []) for item in result.values())
    print(f"已落盘 {out}（共 {total} 个枚举值）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
