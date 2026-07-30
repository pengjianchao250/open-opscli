#!/usr/bin/env python3
"""规划器形态/词表碰撞扫描（同族缺陷的前置发现工具）。

背景：规划器用「编码形态」与「词表」去猜用户文本里某段属于哪个字段。
这类判据天然会碰撞——真实授权值里的一段恰好命中别的字段的形态或槽位词，
就会被误读。2026-07 期间靠实际报错逐个暴露过多起（平台词吃渠道值、
否定词吃字段标签、日期吃渠道SKU、同值跨字段静默绑错等）。
本脚本把这类碰撞一次性枚举出来，替代「等报错再修」。

两条方法论要求（第一版都踩过，务必保持）：
1. 判定必须调用生产代码里真正的匹配器。_term_spans 对 ASCII 词条有词边界约束
   （`(?<![a-z0-9])`），`sb` 不会命中 `BSB-201`；用朴素 `in` 判定会产生上百条假警报
   （实测 118 条假 vs 13 条真）。
2. 分级必须调用生产判据（_is_value_fragment / _cross_field_candidates 是否存在），
   不要在脚本里复刻一份判断逻辑，否则实现修好后脚本仍报未覆盖。

扫描维度与后果分级：
  A' 同一值同时属于多个字段枚举 → 裸值可能静默绑错字段（最危险）
  A  编码形态跨字段命中          → 后果是 fail-closed 澄清（烦但安全）
  B  编码形态命中日期/纯数字字面量
  C  槽位词表命中授权枚举值
  D  通用业务词与授权值主段相等
  E  字段标签含否定词
  F  授权值主段重名（设计内，走澄清）

用法：
    python3 scripts/regression/planner_enum_snapshot.py enums.json
    python3 scripts/regression/planner_collision_scan.py enums.json

数据集或授权枚举扩容后重跑，确认没有新增「高」级碰撞。
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys

DEFAULT_SKILL_DIR = pathlib.Path.home() / ".opscli/skills/ops-dataset-query"

LITERALS = {
    "ISO 日期": "2026-07-01",
    "斜杠日期": "2026/07/01",
    "点分日期": "2026.07.01",
    "紧凑日期": "20260701",
    "年月": "2026-07",
    "长数字": "1234567890",
}
LEVEL_ORDER = {"高": 0, "中": 1, "低": 2, "设计内": 3, "已修": 4}
MAX_PER_GROUP = 6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="planner_enum_snapshot.py 产出的枚举快照")
    parser.add_argument("--skill-dir", default=str(DEFAULT_SKILL_DIR))
    args = parser.parse_args()

    skill_dir = pathlib.Path(args.skill_dir).expanduser()
    sys.path.insert(0, str(skill_dir / "scripts"))
    import query_plan as qp  # noqa: PLC0415
    import time_scope as ts  # noqa: PLC0415
    import typed_schema_linking as schema  # noqa: PLC0415

    data_dir = skill_dir / "data"
    enums = json.loads(pathlib.Path(args.snapshot).read_text(encoding="utf-8"))
    rules = json.loads((data_dir / "intent_rules.json").read_text(encoding="utf-8"))

    spec_order = [item["field_name"] for item in qp._ENUM_COMPONENT_SPECS]
    specs = {item["field_name"]: item for item in qp._ENUM_COMPONENT_SPECS}
    normalize_value = qp._normalize_component_value
    sibling_terms = schema.all_slot_terms(rules)
    has_cross_field_guard = hasattr(qp, "_cross_field_candidates")

    findings: list[tuple[str, str, str]] = []

    def report(level: str, dimension: str, detail: str) -> None:
        findings.append((level, dimension, detail))

    def label_of(field: str) -> str:
        return (
            (enums.get(field) or {}).get("label_zh")
            or specs.get(field, {}).get("label_zh")
            or field
        )

    # ── A' 同一值同时属于多个字段枚举 ──────────────────────────────
    owners: dict[str, set] = {}
    for field, payload in enums.items():
        for value in payload.get("values") or []:
            owners.setdefault(normalize_value(value), set()).add(field)
    shared = {value: group for value, group in owners.items() if len(group) > 1}

    def cross_field_covered(group: set) -> bool:
        """该碰撞是否落在 _cross_field_candidates 的检查范围内。

        该判据只遍历「带编码形态」的字段，所以涉及无形态字段（渠道/国家/品牌等，
        它们走枚举反查）的碰撞并不在防护内，不能一并标为已修——
        这个漏洞是靠人为注入 country_name 碰撞、发现门禁没触发才暴露的。
        """
        return has_cross_field_guard and all(
            specs.get(field, {}).get("value_pattern") for field in group
        )

    reported_high = 0
    for value, group in list(shared.items())[:MAX_PER_GROUP]:
        ordered = sorted(
            group, key=lambda f: spec_order.index(f) if f in spec_order else 99
        )
        covered = cross_field_covered(group)
        reported_high += 0 if covered else 1
        report(
            "已修" if covered else "高",
            "A' 同值跨字段",
            f"值 {value!r} 同时是 {[label_of(f) for f in ordered]} 的授权值"
            + (
                "；裸值已由 _cross_field_candidates 转澄清（标签形态各自正确）"
                if covered
                else "；含无编码形态的字段，不在该判据检查范围内，裸值可能静默绑错"
            ),
        )
    remaining = list(shared.items())[MAX_PER_GROUP:]
    if remaining:
        uncovered = [v for v, g in remaining if not cross_field_covered(g)]
        report(
            "高" if uncovered else "已修",
            "A' 同值跨字段",
            f"其余 {len(remaining)} 个同值跨字段情形"
            + (f"，其中 {len(uncovered)} 个不在检查范围内" if uncovered else "同理已覆盖"),
        )

    # ── A 编码形态跨字段命中 ────────────────────────────────────────
    for owner in spec_order:
        pattern = specs[owner].get("value_pattern")
        if not pattern:
            continue
        compiled = re.compile(pattern)
        own_values = {
            normalize_value(v) for v in (enums.get(owner) or {}).get("values") or []
        }
        for other, payload in enums.items():
            if other == owner:
                continue
            values = payload.get("values") or []
            hits = [
                v
                for v in values
                if compiled.search(str(v)) and normalize_value(v) not in own_values
            ]
            if not hits:
                continue
            earlier = (
                spec_order.index(owner) < spec_order.index(other)
                if other in spec_order
                else True
            )
            report(
                "中" if earlier else "低",
                "A 形态跨字段",
                f"{label_of(owner)} 的形态命中 {label_of(other)} 的 {len(hits)}/{len(values)} 个值"
                + ("（排序更靠前，会先抢）" if earlier else "（排序靠后，一般抢不到）")
                + f"，例：{hits[:2]}",
            )

    # ── B 编码形态命中字面量 ────────────────────────────────────────
    for owner in spec_order:
        pattern = specs[owner].get("value_pattern")
        if not pattern:
            continue
        compiled = re.compile(pattern)
        for name, literal in LITERALS.items():
            found = compiled.search(literal)
            if not found:
                continue
            # 时间窗口起止已由 _time_literals_consumed 登记为已消费
            guarded = literal == "2026-07-01" and hasattr(qp, "_time_literals_consumed")
            report(
                "已修" if guarded else "中",
                "B 形态吃字面量",
                f"{label_of(owner)} 的形态命中{name} {literal!r} → {found.group(0)!r}"
                + ("（时间窗口字面量已登记 consumed）" if guarded else "（无防护）"),
            )

    # ── C 槽位词表命中授权枚举值 ────────────────────────────────────
    for slot_name, slot_values in (rules.get("slots") or {}).items():
        for slot_value, record in slot_values.items():
            for term in record.get("terms") or []:
                for field, payload in enums.items():
                    for value in payload.get("values") or []:
                        spans = schema._term_spans(term, str(value))
                        if not spans:
                            continue
                        if schema.normalize(term) == schema.normalize(str(value)):
                            continue  # 值本身就是该平台名，属正常语义
                        normalized_value = schema.normalize(str(value))
                        start, end = spans[0]
                        if schema._is_value_fragment(
                            normalized_value, start, end, sibling_terms
                        ):
                            level = "已修"
                            note = "被 _is_value_fragment 判为复合值片段"
                        else:
                            level = "高"
                            note = ("首段" if start == 0 else "中段") + "，未被现有判据覆盖"
                        report(
                            level,
                            "C 槽位词吃枚举值",
                            f"槽位 {slot_name}.{slot_value} 词 {term!r} 命中 "
                            f"{label_of(field)} 的值 {value!r}（{note}）",
                        )

    # ── D 通用业务词与授权值主段相等 ────────────────────────────────
    generic = qp._generic_slot_terms()
    for field, payload in enums.items():
        for value in payload.get("values") or []:
            base = normalize_value(value).split("-")[0]
            if len(base) >= 2 and base in generic:
                report(
                    "已修",
                    "D 通用词撞主段",
                    f"{label_of(field)} 的值 {value!r} 主段 {base!r} 是通用业务词"
                    f"（_generic_slot_terms 已排除主段匹配）",
                )

    # ── E 字段标签含否定词 ─────────────────────────────────────────
    labels = set()
    with (data_dir / "dataset_fields.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            for key, value in row.items():
                if value and key and ("name" in key or "label" in key):
                    labels.add(value.strip())
    for label in sorted(labels):
        normalized = normalize_value(label)
        spans = ts.negated_spans(normalized)
        if not spans:
            continue
        swallowed = any(
            start == 0 and end >= len(normalized) for start, end in spans
        )
        report(
            "中" if swallowed else "已修",
            "E 标签含否定词",
            f"字段标签 {label!r} 含否定词"
            + ("（整体落入否定区间，会被误屏蔽）" if swallowed else "（区间包含判定下不受影响）"),
        )

    # ── F 授权值主段重名 ───────────────────────────────────────────
    for field, payload in enums.items():
        bases: dict[str, list] = {}
        for value in payload.get("values") or []:
            base = normalize_value(value).split("-")[0]
            if len(base) >= 2:
                bases.setdefault(base, []).append(value)
        multi = {base: group for base, group in bases.items() if len(group) > 1}
        if multi:
            sample = [(base, len(group)) for base, group in list(multi.items())[:2]]
            report(
                "设计内",
                "F 主段重名",
                f"{label_of(field)} 有 {len(multi)} 个主段对应多值，裸提主段走澄清，例：{sample}",
            )

    # ── 汇总 ───────────────────────────────────────────────────────
    findings.sort(key=lambda item: (LEVEL_ORDER.get(item[0], 9), item[1]))
    counts: dict[str, int] = {}
    for level, _dimension, _detail in findings:
        counts[level] = counts.get(level, 0) + 1

    total_values = sum(len(p.get("values") or []) for p in enums.values())
    print("=" * 76)
    print("规划器形态/词表碰撞扫描")
    print(f"枚举值 {total_values} 个 / 字段标签 {len(labels)} 个")
    print("按级别: " + "  ".join(f"{k}={counts[k]}" for k in LEVEL_ORDER if k in counts))
    print("=" * 76)

    shown: dict[str, int] = {}
    for level, dimension, detail in findings:
        key = f"{level}|{dimension}"
        shown[key] = shown.get(key, 0) + 1
        if shown[key] <= MAX_PER_GROUP:
            print(f"[{level}] {dimension}: {detail}")
    for key, seen in shown.items():
        if seen > MAX_PER_GROUP:
            level, dimension = key.split("|", 1)
            print(f"[{level}] {dimension}: …其余 {seen - MAX_PER_GROUP} 条同类省略")

    # 存在「高」级碰撞时以非零码退出，便于挂进回归门禁
    return 1 if counts.get("高") else 0


if __name__ == "__main__":
    raise SystemExit(main())
