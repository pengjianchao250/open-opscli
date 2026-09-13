#!/usr/bin/env python3
"""初级业务视角的全字段矩阵测试。

目标：当前账号 78 个授权数据集、3312 个字段，每一个字段都必须能被业务用户用
中文名点名查到。对每个字段生成一条口语化请求，校验：

1. 该字段确实进入了 model_view 的维度/指标（或给出合法澄清，不得静默丢弃）；
2. 进入模板时用的是该字段的物理名，且归属正确的数据集；
3. 没有凭空多出用户没点名的筛选条件。

另附初级业务口吻矩阵：同一诉求用多种口语、省略、疑问、中英混杂表述改写，
要求解析结果一致。

只调用内核入口 run_plan，不直连后端 HTTP（铁律11）。
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import random
import re
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opscli.query.services.manager import QueryManager
from opscli.query.services.planner.entry import run_plan

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
COMPONENT_TABLE_IDS = {7, 8, 9, 10, 11, 19, 20, 35, 40}


def load_meta(email: str) -> dict[int, dict]:
    """按 table_id 汇总数据集与字段。"""
    payload = QueryManager().metadata_all(user_email=email).payload
    by_table: dict[int, list[dict]] = defaultdict(list)
    for item in payload["fields"]:
        by_table[int(item["table_id"])].append(item)
    out: dict[int, dict] = {}
    for ds in payload["datasets"]:
        tid = int(ds["table_id"])
        rows = by_table.get(tid, [])
        out[tid] = {
            "table_id": tid,
            "alias": ds["dataset_alias"],
            "name": ds.get("description") or ds.get("dataset_name"),
            "category": ds.get("dataset_category"),
            "dims": [r for r in rows if r.get("field_type") == "dimension"],
            "metrics": [r for r in rows if r.get("field_type") != "dimension"],
            "field_names": {str(r.get("field_name")) for r in rows},
            "filter_names": {str(r.get("field_name")) for r in rows}
            | {str(c.get("column_name")) for c in (ds.get("select_columns") or [])},
        }
    return out


def is_date_like(field: dict) -> bool:
    """日期类字段：不适合当作被点名的业务指标/维度来验证。"""
    name = str(field.get("field_name", "")).lower()
    label = str(field.get("verbose_name", ""))
    tokens = set(name.split("_"))
    return bool(
        tokens & {"date", "time", "day", "month", "year", "dt", "datetime"}
        or "日期" in label
        or "时间" in label
    )


def is_snapshot(field: dict) -> bool:
    return str(field.get("snapshot_metric")) in ("1", "True", "true")


@dataclass
class Case:
    case_id: str
    suite: str
    prompt: str
    table_id: int | None = None
    field_name: str = ""
    field_label: str = ""
    field_type: str = ""
    group: str = ""
    expect: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class Result:
    case: Case
    status: str = ""
    failures: list[str] = dc_field(default_factory=list)
    error: str = ""
    contract: dict | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and not self.error


# ------------------------------------------------------------ 初级业务口吻
# 初级业务用户的真实说法：口语、省略、疑问、客气语、中英混杂
NOVICE_METRIC_TEMPLATES = (
    "帮我看下{ds}{time}的{field}",
    "{ds}{time}的{field}是多少",
    "麻烦查一下{ds}{time}的{field}",
    "我想知道{ds}{time}的{field}",
    "{ds}{time}{field}有多少",
    "能不能帮我拉一下{ds}{time}的{field}",
    "{ds}这边{time}的{field}大概是多少",
    "看看{ds}{time}的{field}情况",
)
NOVICE_DIM_TEMPLATES = (
    "帮我看下{ds}{time}各{field}的{metric}",
    "{ds}{time}按{field}分组看下{metric}",
    "{ds}{time}的{metric}，按{field}拆开看",
    "我想看{ds}{time}每个{field}的{metric}",
    "麻烦按{field}统计一下{ds}{time}的{metric}",
)
NOVICE_TIMES = ("近7天", "上月", "本月", "昨天", "近30天")


def build_field_cases(meta: dict[int, dict], seed: int) -> list[Case]:
    """每个数据集的每个字段各生成一条点名用例。"""
    rng = random.Random(seed)
    cases: list[Case] = []
    for tid, ds in sorted(meta.items()):
        name = ds["name"]
        # 伴随指标：验证维度时需要一个该数据集真实存在的非快照指标
        companion = next(
            (
                str(m["verbose_name"])
                for m in ds["metrics"]
                if m.get("verbose_name") and not is_snapshot(m) and len(str(m["verbose_name"])) <= 12
            ),
            None,
        ) or next(
            (str(m["verbose_name"]) for m in ds["metrics"] if m.get("verbose_name")), None
        )
        for index, item in enumerate(ds["dims"] + ds["metrics"]):
            label = str(item.get("verbose_name") or "").strip()
            field_name = str(item.get("field_name") or "")
            if not label or not field_name:
                continue
            ftype = "dimension" if item.get("field_type") == "dimension" else "metric"
            time_word = NOVICE_TIMES[index % len(NOVICE_TIMES)]
            if ftype == "metric":
                template = NOVICE_METRIC_TEMPLATES[index % len(NOVICE_METRIC_TEMPLATES)]
                prompt = template.format(ds=name, time=time_word, field=label)
            else:
                if is_date_like(item) or not companion:
                    # 日期维度与无指标数据集：改用"列出取值"的点名形态
                    prompt = f"{name}{time_word}的{label}有哪些"
                else:
                    template = NOVICE_DIM_TEMPLATES[index % len(NOVICE_DIM_TEMPLATES)]
                    prompt = template.format(
                        ds=name, time=time_word, field=label, metric=companion
                    )
            cases.append(
                Case(
                    case_id=f"fld-t{tid}-{index}",
                    suite="field_coverage",
                    prompt=prompt,
                    table_id=tid,
                    field_name=field_name,
                    field_label=label,
                    field_type=ftype,
                )
            )
    rng.shuffle(cases)
    return cases


# 组合形态：每个字段在第二遍里换一种业务组合再点名一次
NOVICE_METRIC_COMBOS = (
    "{ds}{time}的{field}，帮我按{dim}拆开看",
    "{ds}{time}{field}最高的前5个{dim}",
    "{ds}{time}的{field}每天是多少",
    "{ds}{time}的{field}，跟上个周期比怎么样",
    "{ds}{time}的{field}是多少，用美元口径",
    "{ds}{time}各{dim}的{field}，从高到低排一下",
)
NOVICE_DIM_COMBOS = (
    "{ds}{time}各{field}的{metric}，取前5个",
    "{ds}{time}按{field}和日期一起看{metric}",
    "{ds}{time}各{field}的{metric}，跟上个周期比",
    "{ds}{time}各{field}的{metric}，从高到低",
)


def build_field_combination_cases(meta: dict[int, dict], seed: int) -> list[Case]:
    """第二遍字段覆盖：同一字段换成业务组合形态（TopN / 趋势 / 环比 / 币种 / 排序）。"""
    rng = random.Random(seed + 1)
    cases: list[Case] = []
    for tid, ds in sorted(meta.items()):
        name = ds["name"]
        companion_metric = next(
            (
                str(m["verbose_name"])
                for m in ds["metrics"]
                if m.get("verbose_name") and not is_snapshot(m) and len(str(m["verbose_name"])) <= 12
            ),
            None,
        )
        companion_dim = next(
            (
                str(d["verbose_name"])
                for d in ds["dims"]
                if d.get("verbose_name") and not is_date_like(d) and len(str(d["verbose_name"])) <= 8
            ),
            None,
        )
        for index, item in enumerate(ds["dims"] + ds["metrics"]):
            label = str(item.get("verbose_name") or "").strip()
            field_name = str(item.get("field_name") or "")
            if not label or not field_name:
                continue
            ftype = "dimension" if item.get("field_type") == "dimension" else "metric"
            time_word = NOVICE_TIMES[(index + 2) % len(NOVICE_TIMES)]
            if ftype == "metric":
                if not companion_dim:
                    continue
                template = NOVICE_METRIC_COMBOS[index % len(NOVICE_METRIC_COMBOS)]
                prompt = template.format(
                    ds=name, time=time_word, field=label, dim=companion_dim
                )
            else:
                if is_date_like(item) or not companion_metric:
                    continue
                template = NOVICE_DIM_COMBOS[index % len(NOVICE_DIM_COMBOS)]
                prompt = template.format(
                    ds=name, time=time_word, field=label, metric=companion_metric
                )
            cases.append(
                Case(
                    case_id=f"cmb-t{tid}-{index}",
                    suite="field_combination",
                    prompt=prompt,
                    table_id=tid,
                    field_name=field_name,
                    field_label=label,
                    field_type=ftype,
                )
            )
    rng.shuffle(cases)
    return cases


def build_novice_phrasing_cases(meta: dict[int, dict]) -> list[Case]:
    """初级业务口吻蜕变组：同一诉求的多种说法必须解析一致。"""
    groups: dict[str, list[str]] = {
        "nv-casual": [
            "近7天各平台的销售额",
            "帮我看下近7天各个平台卖了多少钱",
            "麻烦查一下最近7天每个平台的销售额",
            "我想知道近7天各平台销售额是多少",
            "能不能帮我拉一下近7天各平台的销售额，谢谢",
        ],
        "nv-question": [
            "近7天各平台的销量",
            "近7天各平台卖了多少个",
            "近7天每个平台的销量是多少？",
            "请问近7天各平台销量有多少",
        ],
        "nv-omit-subject": [
            "上月各平台的销售额",
            "上个月各平台卖了多少钱",
            "上月每个平台的销售额是多少",
        ],
        "nv-order-word": [
            "近7天各平台的订单量",
            "近7天各平台有多少单",
            "近7天各平台的单量是多少",
        ],
        "nv-topn": [
            "近7天销售额最高的前5个平台",
            "近7天哪5个平台销售额最高",
            "近7天销售额排前5的平台是哪些",
        ],
        "nv-trend": [
            "近7天每天的销售额",
            "近7天销售额每天是怎么变的",
            "帮我看下近7天销售额的日趋势",
        ],
        # 分组说法：初级用户不说"维度"，说"分开看""拆开看""按…看"
        "nv-groupby": [
            "近7天各平台的销售额",
            "近7天分平台看销售额",
            "近7天按平台拆开看销售额",
            "近7天销售额分平台统计",
            "近7天每一个平台的销售额",
            "近7天逐个平台的销售额",
        ],
        # 排序说法：点名了排序指标的几种写法必须等价
        "nv-best": [
            "近7天销售额最高的前3个平台",
            "近7天销售额排名前3的平台",
            "近7天销售额排前3的平台",
        ],
        "nv-worst": [
            "近7天销售额最低的前3个平台",
            "近7天销售额倒数前3的平台",
        ],
        # 筛选说法：只看/单看/限定。「九部这个部门」带了字段词，规划器会同时把部门
        # 加为分组维度，结果多一列常量部门名但数值不变，属可接受差异，不入等价组。
        "nv-filter": [
            "近7天九部的销售额",
            "近7天只看九部的销售额",
            "近7天限定九部的销售额",
        ],
        # 环比说法
        "nv-mom": [
            "近7天各平台的销售额环比上一周期",
            "近7天各平台的销售额跟上个周期比怎么样",
        ],
        # 组合：时间 + 分组 + 指标 + TopN 的口语版（均点名了排序指标）
        "nv-combo": [
            "上月各平台的销售额最高的前5个",
            "上个月哪5个平台的销售额最高",
            "上个月销售额前5的平台",
        ],
    }
    cases: list[Case] = []
    for group, prompts in groups.items():
        for index, prompt in enumerate(prompts):
            cases.append(
                Case(f"{group}-{index}", "novice_phrasing", prompt, group=group)
            )
    return cases


def build_terminology_cases() -> list[Case]:
    """业务术语矩阵：同一口径的多种说法必须落到同一个字段，或安全澄清。

    初级业务用户不使用元数据里的规范字段名，用的是自己部门的习惯叫法。
    这里逐个术语核对：能落到字段的必须落对，落不到的必须澄清而不是静默丢弃。
    """
    groups: dict[str, tuple[str, tuple[str, ...]]] = {
        # 组名: (期望落到的中文字段标签, 该口径的各种说法)
        "tm-sales-amount": (
            "销售额",
            ("销售额", "销售金额", "收入", "营业额", "流水", "成交额",
             "GMV", "销售业绩", "卖了多少钱"),
        ),
        "tm-sales-qty": (
            "销量",
            ("销量", "销售量", "订单量", "单量", "出单量", "成交量",
             "销售件数", "卖了多少个", "多少单"),
        ),
        "tm-ad-cost": (
            "广告费",
            ("广告费", "广告花费", "广告支出", "推广费", "投放费用", "广告成本"),
        ),
        "tm-profit": ("毛利", ("毛利", "毛利额", "利润额", "赚了多少")),
        "tm-purchase": ("采购成本", ("采购成本", "采购费用", "进货成本")),
    }
    cases: list[Case] = []
    for group, (expected_label, terms) in groups.items():
        for index, term in enumerate(terms):
            cases.append(
                Case(
                    f"{group}-{index}",
                    "terminology",
                    f"近7天各平台的{term}",
                    group=group,
                    field_label=expected_label,
                    expect={"expected_label": expected_label, "term": term},
                )
            )
    return cases


def build_time_term_cases() -> list[Case]:
    """口语时间术语矩阵：每种说法都必须解析出确定窗口或安全澄清。"""
    today = datetime.now(TZ).date()

    def days(n: int) -> tuple[str, str]:
        end = today
        return (end - timedelta(days=n - 1)).isoformat(), end.isoformat()

    first_of_month = today.replace(day=1)
    next_month = (first_of_month + timedelta(days=32)).replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    # 本周按周一起算
    monday = today - timedelta(days=today.weekday())
    last_monday = monday - timedelta(days=7)

    specs: list[tuple[str, str, tuple[str, str] | None]] = [
        ("tt-today", "今天", (today.isoformat(), today.isoformat())),
        ("tt-yesterday", "昨天", days(1) if False else ((today - timedelta(days=1)).isoformat(),) * 2),
        ("tt-before-yesterday", "前天", ((today - timedelta(days=2)).isoformat(),) * 2),
        ("tt-this-week", "本周", (monday.isoformat(), today.isoformat())),
        ("tt-this-week2", "这周", (monday.isoformat(), today.isoformat())),
        ("tt-last-week", "上周", (last_monday.isoformat(), (monday - timedelta(days=1)).isoformat())),
        ("tt-this-month", "本月", (first_of_month.isoformat(), (next_month - timedelta(days=1)).isoformat())),
        ("tt-this-month2", "这个月", (first_of_month.isoformat(), (next_month - timedelta(days=1)).isoformat())),
        ("tt-last-month", "上个月", (last_month_end.replace(day=1).isoformat(), last_month_end.isoformat())),
        ("tt-7d", "近7天", days(7)),
        ("tt-7d2", "最近7天", days(7)),
        ("tt-7d3", "过去一周", None),
        ("tt-30d", "近30天", days(30)),
        ("tt-ytd", "今年以来", (today.replace(month=1, day=1).isoformat(), today.isoformat())),
        ("tt-h1", "上半年", None),
        ("tt-recent", "最近", None),
        ("tt-these-days", "这两天", None),
    ]
    cases: list[Case] = []
    for cid, term, window in specs:
        cases.append(
            Case(
                cid,
                "time_terminology",
                f"{term}各平台的销售额",
                group="",
                expect={"window": window, "term": term},
            )
        )
    return cases


def build_novice_vague_cases() -> list[Case]:
    """初级业务的模糊/不完整表述：要求安全澄清而不是猜。"""
    prompts = [
        ("vg-no-time", "各平台的销售额"),
        ("vg-no-metric", "近7天各平台"),
        ("vg-only-verb", "帮我查一下数据"),
        ("vg-vague-metric", "近7天各平台的情况"),
        ("vg-vague-metric2", "近7天各平台表现怎么样"),
        ("vg-typo-field", "近7天各平台的销售鄂"),
        ("vg-wrong-field", "近7天各平台的毛利润率"),
        ("vg-polite-only", "麻烦帮我看一下，谢谢"),
        ("vg-pronoun", "这个月的数据帮我看下"),
        ("vg-unit-mix", "近7天各平台卖了多少钱和多少个"),
        ("vg-no-dataset", "帮我看看数据"),
        ("vg-emotive", "最近生意怎么样"),
        ("vg-abbrev", "近7天各平台的额"),
        ("vg-halfword", "近7天各平台的销"),
        ("vg-repeat", "销售额销售额销售额"),
        ("vg-onlypunct", "，。！"),
        ("vg-mixed-case", "近7天各平台的 SALES"),
        ("vg-space-inside", "近 7 天 各 平台 的 销售额"),
        ("vg-followup", "那上个月呢"),
        ("vg-sell-best", "近7天卖得最好的3个平台"),
        ("vg-sell-worst", "近7天卖得最差的3个平台"),
        ("vg-sell-most", "上个月哪5个平台卖得最多"),
    ]
    return [Case(cid, "novice_vague", prompt) for cid, prompt in prompts]


# ------------------------------------------------------------ 断言
def _tpl(contract: dict) -> dict | None:
    return (contract.get("execution_ref") or {}).get("query_template")


LEGIT_CLARIFY_CODES = {
    "snapshot_metric_window_conflict",
    "time_comparison_unsupported",
    "time_scope_confirmation",
    "recommended_fields_confirmation",
    "field_identity",
    "ambiguous_field_labels_zh",
    "component_filter_polarity_conflict",
    "unsupported_currency",
    "dataset_selection",
    "dataset_constraints",
    "business_dataset",
}


def check_field_case(case: Case, contract: dict, meta: dict[int, dict]) -> list[str]:
    """点名字段必须命中：进入模型视图、进入模板、归属正确数据集。"""
    fails: list[str] = []
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    status = contract.get("status")
    tpl = _tpl(contract)
    ds = meta[case.table_id]

    if status == "blocked":
        fails.append(f"blocked：{mv.get('block_reason_zh')}")
        return fails

    if status == "clarify_required":
        codes = set(mv.get("clarification_reason_codes") or [])
        # 点名的字段确实存在于该数据集，却报"不在数据集里"是硬缺陷
        if {"metric_not_in_dataset", "dimension_not_in_dataset"} & codes:
            fails.append(
                f"点名了本数据集真实存在的字段 {case.field_label!r}，却报 {sorted(codes)}"
                f"（unknown={mv.get('unknown_requested_fields')}）"
            )
        elif {"component_filter_value_unmatched", "component_filter_unauthorized"} & codes:
            fails.append(
                f"字段名被误当成筛选值：{json.dumps(mv.get('clarification_messages_zh'), ensure_ascii=False)[:160]}"
            )
        elif not (codes & LEGIT_CLARIFY_CODES):
            fails.append(f"澄清原因不在允许清单：{sorted(codes)}")
        return fails

    # planned：字段必须真的落到合同里
    seen_labels = [str(x) for x in (mv.get("dimensions") or []) + (mv.get("metrics") or [])]
    if case.field_label not in seen_labels:
        fails.append(f"点名字段 {case.field_label!r} 未进入 model_view（实际 {seen_labels}）")

    if tpl is not None:
        used = {str(d.get("field")) for d in (tpl.get("dimensions") or [])}
        used |= {str(m.get("field")) for m in (tpl.get("metrics") or [])}
        if case.field_name not in used:
            fails.append(f"点名字段物理名 {case.field_name} 未进入模板（实际 {sorted(used)}）")
        if er.get("table_id") != case.table_id:
            fails.append(f"选错数据集 table_id={er.get('table_id')} 期望 {case.table_id}")
        # 用户只点了字段，没给筛选值；除日期外不应凭空多出筛选条件
        extra = [
            (f.get("field"), f.get("operator"), f.get("value"))
            for f in (tpl.get("filters") or [])
            if isinstance(f, dict) and str(f.get("operator")) not in (">=", "<=", "between")
        ]
        if extra:
            fails.append(f"凭空多出筛选条件 {extra}")
        for order in tpl.get("orderBy") or []:
            aliases = {str(d.get("alias") or d.get("field")) for d in (tpl.get("dimensions") or [])}
            aliases |= {str(m.get("alias") or m.get("field")) for m in (tpl.get("metrics") or [])}
            if str(order.get("field")) not in aliases:
                fails.append(f"orderBy 字段 {order.get('field')} 不在本次投影里")
        for name in used:
            if name not in ds["field_names"]:
                fails.append(f"投影字段 {name} 不属于数据集 {ds['name']}")
    return fails


def check_generic(contract: dict) -> list[str]:
    """任何用例都适用的基础不变量。"""
    fails: list[str] = []
    status = contract.get("status")
    if status not in ("planned", "clarify_required", "blocked"):
        fails.append(f"非法 status={status}")
    if status in ("clarify_required", "blocked") and _tpl(contract) is not None:
        fails.append(f"{status} 不得下发可执行模板")
    mv = contract.get("model_view") or {}
    for key in ("dimensions", "metrics"):
        for item in mv.get(key) or []:
            if str(item).startswith("ds_"):
                fails.append(f"model_view.{key} 泄漏技术标识 {item!r}")
    return fails


AMBIGUOUS_ORDER_CASES = {"vg-sell-best", "vg-sell-worst", "vg-sell-most"}


def check_vague(contract: dict, case_id: str = "") -> list[str]:
    """模糊表述必须安全：要么澄清，要么下发的模板不含凭空筛选。

    「卖得最好/最多/最差」还额外要求：既然指标本身是模糊的，就必须带齐核心销售
    指标并强制披露"排序指标未唯一确定"，不得静默返回一个没有指标的清单。
    """
    fails = check_generic(contract)
    if case_id in AMBIGUOUS_ORDER_CASES:
        mv = contract.get("model_view") or {}
        metrics = [str(x) for x in (mv.get("metrics") or [])]
        if not metrics:
            fails.append("模糊排序说法返回零指标")
        disclosures = json.dumps(
            (contract.get("answer_contract") or {}).get("required_disclosures_zh") or [],
            ensure_ascii=False,
        )
        if "未能唯一确定" not in disclosures:
            fails.append(f"模糊排序说法缺排序未定披露：{disclosures[:160]}")
    tpl = _tpl(contract)
    if tpl is not None:
        extra = [
            (f.get("field"), f.get("operator"), f.get("value"))
            for f in (tpl.get("filters") or [])
            if isinstance(f, dict) and str(f.get("operator")) not in (">=", "<=", "between")
        ]
        if extra:
            fails.append(f"模糊表述凭空产生筛选条件 {extra}")
    return fails


def check_terminology(case: Case, contract: dict) -> list[str]:
    """术语必须落到预期字段，或给出澄清；不得静默产出零指标模板。"""
    fails = check_generic(contract)
    mv = contract.get("model_view") or {}
    status = contract.get("status")
    expected = case.expect.get("expected_label")
    if status == "planned":
        metrics = [str(x) for x in (mv.get("metrics") or [])]
        if not metrics:
            fails.append(f"术语「{case.expect.get('term')}」被静默丢弃，模板零指标")
        elif expected not in metrics:
            fails.append(f"术语「{case.expect.get('term')}」落到 {metrics}，期望含 {expected}")
    return fails


def check_time_term(case: Case, contract: dict) -> list[str]:
    """时间术语必须解析出确定窗口；未支持时必须澄清而不是静默取默认。"""
    fails = check_generic(contract)
    er = contract.get("execution_ref") or {}
    mv = contract.get("model_view") or {}
    scope = er.get("time_scope") or {}
    window = case.expect.get("window")
    got = (scope.get("start"), scope.get("end"))
    if window is not None:
        if got != tuple(window):
            fails.append(f"时间术语「{case.expect.get('term')}」窗口 {got} 期望 {tuple(window)}")
    else:
        # 未登记确切预期的说法：只要求不要静默套用默认口径
        if scope.get("is_default") and contract.get("status") == "planned":
            fails.append(
                f"时间术语「{case.expect.get('term')}」未识别却按默认口径直接执行："
                f"{mv.get('time_scope_zh')}"
            )
    return fails


def run_case(case: Case, email: str, meta: dict[int, dict]) -> Result:
    try:
        contract = run_plan(case.prompt, user_email=email)
    except Exception as exc:  # noqa: BLE001
        return Result(case=case, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}")
    if case.suite in ("field_coverage", "field_combination"):
        fails = check_generic(contract) + check_field_case(case, contract, meta)
    elif case.suite == "terminology":
        fails = check_terminology(case, contract)
    elif case.suite == "time_terminology":
        fails = check_time_term(case, contract)
    elif case.suite == "novice_vague":
        fails = check_vague(contract, case.case_id)
    else:
        fails = check_generic(contract)
    return Result(case=case, status=str(contract.get("status")), failures=fails, contract=contract)


def check_phrasing_groups(records: list[dict]) -> list[dict]:
    """初级口吻蜕变组：组内模板必须一致。

    records 是结果文件里的行（完整合同写盘后即释放），模板签名按写盘的 template
    计算：无模板记为 <none>，否则按键排序序列化后比较。
    """
    findings: list[dict] = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("suite") == "novice_phrasing":
            groups[record.get("group", "")].append(record)
    for group, items in sorted(groups.items()):
        sigs = {
            item["case_id"]: (
                "<none>"
                if item.get("template") is None
                else json.dumps(item["template"], ensure_ascii=False, sort_keys=True)
            )
            for item in items
        }
        if len(set(sigs.values())) > 1:
            findings.append({
                "group": group,
                "detail": {
                    item["case_id"]: {
                        "prompt": item["prompt"],
                        "status": item["status"],
                        "template": sigs[item["case_id"]][:300],
                    }
                    for item in items
                },
            })
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="chenbenli@aukeys.com")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/planner-audit-20260909")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--suite", action="append")
    parser.add_argument("--table-id", type=int, action="append")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--tag", default="fields")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="续跑：跳过结果文件里已完成的用例，剩余部分追加写入（本机内存吃紧时任务可能被中途结束）",
    )
    args = parser.parse_args()

    meta = load_meta(args.email)
    cases = (
        build_field_cases(meta, args.seed)
        + build_field_combination_cases(meta, args.seed)
        + build_novice_phrasing_cases(meta)
        + build_terminology_cases()
        + build_time_term_cases()
        + build_novice_vague_cases()
    )
    if args.suite:
        want = set(args.suite)
        cases = [c for c in cases if c.suite in want]
    if args.table_id:
        want_tables = set(args.table_id)
        cases = [c for c in cases if c.table_id in want_tables or c.table_id is None]
    if args.max_cases:
        cases = cases[: args.max_cases]

    covered_fields = {
        (c.table_id, c.field_name)
        for c in cases
        if c.suite in ("field_coverage", "field_combination")
    }
    total_fields = sum(len(v["dims"]) + len(v["metrics"]) for v in meta.values())
    print(f"数据集 {len(meta)}，字段 {total_fields}，字段用例覆盖 {len(covered_fields)}，总用例 {len(cases)}")

    # 逐条写盘后立即释放完整合同：6000 余份合同全部留在内存里时峰值过高，
    # 本机同时开着其他应用时会被系统低内存结束。输出文件的内容与顺序不变；
    # 汇总与口吻一致性检查在跑完后从结果文件全量统计，续跑时也能合并。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{args.tag}-results.jsonl"
    if args.resume and out.exists():
        done = {json.loads(line)["case_id"] for line in out.open(encoding="utf-8") if line.strip()}
        cases = [c for c in cases if c.case_id not in done]
        print(f"续跑：结果文件已有 {len(done)} 条，本次补跑 {len(cases)} 条")
    mode = "a" if args.resume else "w"
    with out.open(mode, encoding="utf-8") as fh, futures.ThreadPoolExecutor(args.workers) as pool:
        for res in pool.map(lambda c: run_case(c, args.email, meta), cases):
            if not res.ok:
                print(f"[{'ERR' if res.error else 'FAIL'}] {res.case.case_id} | {res.case.prompt[:72]}")
                for item in (res.failures or [res.error])[:2]:
                    print(f"        - {str(item)[:190]}")
            fh.write(json.dumps({
                "case_id": res.case.case_id, "suite": res.case.suite,
                "table_id": res.case.table_id, "field_name": res.case.field_name,
                "field_label": res.case.field_label, "field_type": res.case.field_type,
                "group": res.case.group, "prompt": res.case.prompt,
                "status": res.status, "ok": res.ok, "failures": res.failures, "error": res.error,
                "model_view": (res.contract or {}).get("model_view"),
                "template": _tpl(res.contract or {}),
            }, ensure_ascii=False, default=str) + "\n")
            fh.flush()

    records = [json.loads(line) for line in out.open(encoding="utf-8") if line.strip()]
    phrasing = check_phrasing_groups(records)
    for finding in phrasing:
        print(f"[REL] {finding['group']} 口吻不一致")
        print(f"        {json.dumps(finding['detail'], ensure_ascii=False)[:420]}")

    bad = [r for r in records if not r["ok"]]
    by_suite = Counter(r["suite"] for r in bad)
    by_table = Counter(r["table_id"] for r in bad if r.get("table_id"))
    print("\n==== 汇总 ====")
    print(f"总用例 {len(records)}，失败 {len(bad)}，口吻不一致组 {len(phrasing)}")
    for suite, n in by_suite.most_common():
        tot = sum(1 for r in records if r["suite"] == suite)
        print(f"  {suite}: {n}/{tot}")
    if by_table:
        print("失败最多的数据集：")
        for tid, n in by_table.most_common(12):
            print(f"  t{tid} {meta[tid]['name']}: {n}")
    print(f"明细：{out}")


if __name__ == "__main__":
    main()
