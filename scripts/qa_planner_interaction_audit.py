#!/usr/bin/env python3
"""规划器特性交叉兼容矩阵。

本轮修复涉及时间解析、指标别名、口语问法、维度吞并、组件筛选、排序行数、
对比、币种、趋势、快照、权限枚举十余条互相重叠的代码路径。单独验证每条修复
不足以证明它们能同时成立——这里把每条修复抽象成一个"特性片段"，按两两、
三重、四重叠加组装成自然语言请求，要求**所有片段的预期效果同时出现在同一份
规划合同里**，任何一条被别的特性挤掉即判失败。

三种视角共用同一套片段库：
- 专业运营给领导汇报：完整句式 + 明确口径 + TopN/环比/币种
- 专业测试：不变量与冲突组合
- 菜鸟运营：口语片段（卖了多少钱/哪5个/分平台看/前天）

只调用内核入口 run_plan，不直连后端 HTTP（铁律11）。
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import itertools
import json
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opscli.query.services.planner.entry import run_plan

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")


def today() -> date:
    return datetime.now(TZ).date()


def last_n(n: int) -> tuple[str, str]:
    end = today()
    return (end - timedelta(days=n - 1)).isoformat(), end.isoformat()


def day_offset(n: int) -> tuple[str, str]:
    day = (today() - timedelta(days=n)).isoformat()
    return day, day


def this_month() -> tuple[str, str]:
    start = today().replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat(), (nxt - timedelta(days=1)).isoformat()


def last_month() -> tuple[str, str]:
    first = today().replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1).isoformat(), end.isoformat()


def quarter_window(year: int, index: int) -> tuple[str, str]:
    month = (index - 1) * 3 + 1
    start = date(year, month, 1)
    end_month = month + 3
    nxt = date(year + end_month // 13, (end_month - 1) % 12 + 1, 1)
    return start.isoformat(), (nxt - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- 片段库
@dataclass(frozen=True)
class Fragment:
    """一条修复对应的可组合语言片段及其单独应产生的合同效果。"""

    frag_id: str
    slot: str          # time / metric / dim / filter / tail
    text: str
    expect: dict[str, Any] = dc_field(default_factory=dict)
    persona: str = "all"
    # 与之组合会让本片段语义变成空操作的片段（如正向平台范围已把排除项排除在外）
    skip_with: frozenset[str] = frozenset()


def fragments() -> list[Fragment]:
    now = today()
    return [
        # ---- 时间 ----
        Fragment("t-7d", "time", "近7天", {"time": last_n(7)}),
        Fragment("t-fullwidth", "time", "近７天", {"time": last_n(7)}, "novice"),
        Fragment("t-daybefore", "time", "前天", {"time": day_offset(2)}, "novice"),
        Fragment("t-daybefore2", "time", "大前天", {"time": day_offset(3)}, "novice"),
        Fragment("t-single-date", "time", "2026年8月15日", {"time": ("2026-08-15", "2026-08-15")}),
        Fragment("t-quarter", "time", "今年第一季度", {"time": quarter_window(now.year, 1)}, "leadership"),
        Fragment("t-quarter2", "time", "今年Q1", {"time": quarter_window(now.year, 1)}, "leadership"),
        Fragment("t-lastmonth", "time", "上个月", {"time": last_month()}, "novice"),
        Fragment("t-thismonth", "time", "本月", {"time": this_month()}, "leadership"),
        # ---- 指标 ----
        Fragment("m-sales", "metric", "销售额", {"metrics": ["销售额"]}),
        Fragment("m-revenue-alias", "metric", "营业额", {"metrics": ["销售额"]}, "novice"),
        Fragment("m-gmv", "metric", "GMV", {"metrics": ["销售额"]}, "novice"),
        Fragment("m-qty", "metric", "销量", {"metrics": ["销量"]}),
        Fragment("m-qty-alias", "metric", "销售量", {"metrics": ["销量"], "dim_absent": "销售"}, "novice"),
        Fragment("m-adcost", "metric", "广告支出", {"metrics": ["广告费"]}, "novice"),
        Fragment("m-margin", "metric", "毛利率", {"metrics": ["毛利率"]}, "leadership"),
        # ---- 维度 ----
        Fragment("d-platform", "dim", "平台", {"dims": ["平台"]}),
        Fragment("d-bigteam", "dim", "大组", {"dims": ["大组"]}),
        Fragment("d-team", "dim", "销售小组", {"dims": ["销售小组"], "dim_absent": "销售"}),
        Fragment("d-dept", "dim", "部门", {"dims": ["部门"]}),
        Fragment("d-country", "dim", "国家", {"dims": ["国家"]}),
        Fragment("d-brand", "dim", "品牌", {"dims": ["品牌"]}),
        # ---- 筛选 ----
        Fragment("f-dept", "filter", "九部", {"filter": ("dept_name", "=", "九部")}),
        Fragment("f-dept-num", "filter", "项目九部", {"filter": ("dept_name", "=", "项目九部")}),
        Fragment("f-composite", "filter", "一部-B组",
                 {"filter": ("team_name", "=", "一部-B组"), "no_filter_field": "large_team_name"}),
        Fragment("f-platform", "filter", "亚马逊SC", {"filter": ("platform_name", "=", "Amazon")}),
        # ---- 尾部修饰：排序 / 对比 / 币种 / 趋势 / 排除 ----
        # 不点名排序指标：由本次唯一指标承担排序，验证"排序不因别的特性丢失"
        Fragment("o-top5", "tail", "，取最高的前5个", {"limit": 5, "order_desc": True}, "leadership"),
        Fragment("o-which5", "tail", "，哪5个最高", {"limit": 5, "order_desc": True}, "novice"),
        Fragment("o-asc", "tail", "，升序取前3", {"limit": 3, "order_desc": False}, "leadership"),
        Fragment("c-mom", "tail", "，环比上一周期", {"comparison": True}, "leadership"),
        Fragment("c-mom-casual", "tail", "，跟上个周期比怎么样", {"comparison": True}, "novice"),
        Fragment("c-yoy", "tail", "，同比去年同期", {"comparison": True}, "leadership"),
        Fragment("cur-usd", "tail", "，用美元口径", {"currency": "USD"}, "leadership"),
        Fragment("cur-multi", "tail", "，分别用人民币和加拿大元展示",
                 {"multi_currency": ["CNY", "CAD"]}, "leadership"),
        Fragment("tr-daily", "tail", "，按日趋势", {"trend": True}, "leadership"),
        Fragment("tr-daily-casual", "tail", "，每天分开看", {"trend": True}, "novice"),
        # 已有正向平台范围时排除项对模板是空操作（正向集合本就不含它们），
        # 因此不与 f-platform 组合断言；该组合的正确性由"不得多出同名销售小组
        # 筛选"单独覆盖。
        Fragment("x-exclude-plat", "tail", "，排除亚马逊VC",
                 {"filter": ("platform_name", "!=", "Amazon VC")}, "leadership",
                 frozenset({"f-platform"})),
        Fragment("x-exclude-multi", "tail", "，排除TikTok和Temu",
                 # 平台授权值已改为确定性排序，IN/NOT_IN 列表按字典序
                 {"filter": ("platform_name", "not_in", ["Temu", "Tiktok"]),
                  "no_filter_value": ("team_name", "Tiktok")}, "leadership",
                 frozenset({"f-platform"})),
    ]


def compose(parts: dict[str, Fragment]) -> str:
    """组装成 {时间}{筛选}各{维度}的{指标}{尾部} 形态的自然语言请求。"""
    time_text = parts["time"].text if "time" in parts else "近7天"
    filter_text = parts["filter"].text if "filter" in parts else ""
    dim_text = parts["dim"].text if "dim" in parts else "平台"
    metric_text = parts["metric"].text if "metric" in parts else "销售额"
    tail_text = "".join(
        parts[name].text for name in sorted(parts) if parts[name].slot == "tail"
    )
    return f"{time_text}{filter_text}各{dim_text}的{metric_text}{tail_text}"


def merge_expect(parts: dict[str, Fragment]) -> dict[str, Any]:
    """合并所有片段的预期；列表型预期累积，标量型直接覆盖。"""
    merged: dict[str, Any] = {
        "metrics": [], "dims": [], "filters": [], "dim_absent": [],
        "no_filter_field": [], "no_filter_value": []
    }
    for fragment in parts.values():
        for name, value in fragment.expect.items():
            if name == "metrics":
                merged["metrics"].extend(value)
            elif name == "dims":
                merged["dims"].extend(value)
            elif name == "filter":
                merged["filters"].append(value)
            elif name == "dim_absent":
                merged["dim_absent"].append(value)
            elif name == "no_filter_field":
                merged["no_filter_field"].append(value)
            elif name == "no_filter_value":
                merged["no_filter_value"].append(value)
            else:
                merged[name] = value
    return merged


@dataclass
class Case:
    case_id: str
    suite: str
    prompt: str
    expect: dict[str, Any]
    persona: str
    parts: tuple[str, ...]


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


def _tpl(contract: dict) -> dict | None:
    return (contract.get("execution_ref") or {}).get("query_template")


def check(case: Case, contract: dict) -> list[str]:
    """所有片段的预期必须同时成立，任何一条被别的特性挤掉即失败。"""
    fails: list[str] = []
    exp = case.expect
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    status = contract.get("status")

    if status != "planned":
        codes = mv.get("clarification_reason_codes") or []
        message = json.dumps(mv.get("clarification_messages_zh"), ensure_ascii=False)
        fails.append(f"status={status} codes={codes} msg={message[:130]}")
        return fails

    template = _tpl(contract)
    if template is None:
        fails.append("planned 但没有下发模板")
        return fails

    got_metrics = [str(item) for item in (mv.get("metrics") or [])]
    for label in exp.get("metrics") or []:
        if label not in got_metrics:
            fails.append(f"缺指标 {label}（实际 {got_metrics}）")

    got_dims = [str(item) for item in (mv.get("dimensions") or [])]
    for label in exp.get("dims") or []:
        if label not in got_dims:
            fails.append(f"缺维度 {label}（实际 {got_dims}）")
    for label in exp.get("dim_absent") or []:
        if label in got_dims:
            fails.append(f"不应出现维度 {label}（实际 {got_dims}）")

    if exp.get("time"):
        scope = er.get("time_scope") or {}
        got = (scope.get("start"), scope.get("end"))
        # 快照口径会把窗口收敛到最新完整快照日，属既定行为，不算冲突
        if got != tuple(exp["time"]) and not er.get("snapshot_policy"):
            fails.append(f"时间窗 {got} 期望 {tuple(exp['time'])}")

    template_filters = [f for f in (template.get("filters") or []) if isinstance(f, dict)]
    actual_filters = [
        (f.get("field"), f.get("operator"), f.get("value")) for f in template_filters
    ]
    for want_field, want_op, want_value in exp.get("filters") or []:
        hit = [
            f for f in template_filters
            if str(f.get("field")) == want_field
            and str(f.get("operator")) == want_op
            and f.get("value") == want_value
        ]
        if not hit:
            fails.append(f"缺筛选 {want_field} {want_op} {want_value}（实际 {actual_filters}）")
    for field_name in exp.get("no_filter_field") or []:
        bad = [f for f in template_filters if str(f.get("field")) == field_name]
        if bad:
            fails.append(f"不应出现 {field_name} 筛选（实际 {actual_filters}）")
    for field_name, bad_value in exp.get("no_filter_value") or []:
        bad = [
            f for f in template_filters
            if str(f.get("field")) == field_name and f.get("value") == bad_value
        ]
        if bad:
            fails.append(f"不应出现 {field_name}={bad_value} 筛选（实际 {actual_filters}）")

    if exp.get("limit") is not None and template.get("limit") != exp["limit"]:
        fails.append(f"limit={template.get('limit')} 期望 {exp['limit']}")

    if exp.get("order_desc") is not None:
        order_by = template.get("orderBy") or []
        # 趋势会追加日期升序；显式排序诉求必须仍然生效
        metric_orders = [
            item for item in order_by if "date" not in str(item.get("field", "")).lower()
        ]
        if not metric_orders:
            fails.append(f"缺按指标排序（实际 {order_by}）")
        elif bool(metric_orders[0].get("desc")) != bool(exp["order_desc"]):
            fails.append(f"排序方向 {metric_orders[0].get('desc')} 期望 {exp['order_desc']}")

    if exp.get("comparison") and not template.get("dataComparison"):
        fails.append("缺 dataComparison")

    if exp.get("currency") and template.get("globalCurrency") != exp["currency"]:
        fails.append(f"globalCurrency={template.get('globalCurrency')} 期望 {exp['currency']}")
    if exp.get("multi_currency"):
        templates = er.get("query_templates") or []
        got = [str(item.get("globalCurrency")) for item in templates if isinstance(item, dict)]
        for code in exp["multi_currency"]:
            if code not in got:
                fails.append(f"多币种缺 {code}（实际 {got}）")

    if exp.get("trend"):
        dims = [str(item.get("field")) for item in (template.get("dimensions") or [])]
        date_names = {str(item.get("field_name")) for item in (er.get("date_fields") or [])}
        if not (set(dims) & date_names):
            fails.append(f"趋势未补日期维度（实际 {dims}）")
    return fails


def build_cases(personas: set[str]) -> list[Case]:
    """两两 + 三重 + 四重叠加。"""
    pool = [f for f in fragments() if f.persona in personas or f.persona == "all"]
    by_slot: dict[str, list[Fragment]] = defaultdict(list)
    for fragment in pool:
        by_slot[fragment.slot].append(fragment)

    cases: list[Case] = []
    seen: set[tuple[str, ...]] = set()

    def add(parts: dict[str, Fragment], suite: str) -> None:
        ids = tuple(sorted(item.frag_id for item in parts.values()))
        if ids in seen:
            return
        # 组合后语义互相抵消的片段对不参与断言
        if any(
            other in item.skip_with
            for item in parts.values()
            for other in ids
        ):
            return
        seen.add(ids)
        persona = next(
            (item.persona for item in parts.values() if item.persona != "all"), "all"
        )
        cases.append(
            Case(
                case_id="ix-" + "+".join(ids),
                suite=suite,
                prompt=compose(parts),
                expect=merge_expect(parts),
                persona=persona,
                parts=ids,
            )
        )

    pairs = [
        ("time", "metric"), ("time", "dim"), ("metric", "dim"),
        ("dim", "filter"), ("metric", "tail"), ("time", "tail"),
        ("dim", "tail"), ("filter", "tail"),
    ]
    for left, right in pairs:
        for first in by_slot[left]:
            for second in by_slot[right]:
                add({left: first, right: second}, "pairwise")

    for first in by_slot["time"]:
        for second in by_slot["dim"]:
            for third in by_slot["tail"]:
                add({"time": first, "dim": second, "tail": third}, "triple")

    for first in by_slot["time"][:5]:
        for second in by_slot["filter"]:
            for third in by_slot["dim"][:4]:
                for fourth in by_slot["tail"][:8]:
                    add(
                        {"time": first, "filter": second, "dim": third, "tail": fourth},
                        "quad",
                    )
    cases.extend(
        case for case in build_conflict_cases()
        if case.persona in personas or case.persona == "all"
    )
    return cases


def build_conflict_cases() -> list[Case]:
    """槽位模板覆盖不到的高风险冲突组合，逐条写死预期。

    这些组合会让两条以上修复在同一句里争夺同一段文本或同一个合同字段，
    是"新增优化互不兼容"最容易暴露的地方。
    """
    now = today()
    specs: list[tuple[str, str, dict[str, Any], str]] = [
        # 快照 × 维度保留 × 趋势
        ("cf-snapshot-dim", "即时综合数据集近7天各平台的平台库存",
         {"dims": ["平台"], "metrics": ["平台库存"]}, "leadership"),
        ("cf-snapshot-trend", "即时综合数据集近7天各平台的平台库存，按日趋势",
         {"dims": ["平台"], "metrics": ["平台库存"], "trend": True}, "leadership"),
        ("cf-snapshot-topn", "即时综合数据集近7天平台库存最高的前5个平台",
         {"dims": ["平台"], "metrics": ["平台库存"], "limit": 5, "order_desc": True}, "leadership"),
        # 三个「销售」同句
        ("cf-three-sales", "近7天各销售小组的销售额，按销售额降序取前5",
         {"dims": ["销售小组"], "metrics": ["销售额"], "dim_absent": ["销售"],
          "limit": 5, "order_desc": True}, "leadership"),
        ("cf-sales-person", "近7天各销售的销售量，取最高的前5个",
         {"dims": ["销售"], "metrics": ["销量"], "limit": 5, "order_desc": True}, "novice"),
        # 单日 × 趋势 / 单日 × 环比
        ("cf-singleday-trend", "2026年8月15日各平台的销售额，按日趋势",
         {"time": ("2026-08-15", "2026-08-15"), "trend": True}, "leadership"),
        ("cf-singleday-mom", "2026年8月15日各平台的销售额，环比上一周期",
         {"time": ("2026-08-15", "2026-08-15"), "comparison": True}, "leadership"),
        # 季度 × 环比 / 季度 × 同比 × 币种
        ("cf-quarter-mom", "今年第一季度各平台的销售额，环比上一周期",
         {"time": quarter_window(now.year, 1), "comparison": True}, "leadership"),
        ("cf-quarter-yoy-cur", "今年第一季度各大组的销售额，同比去年同期，用美元口径",
         {"time": quarter_window(now.year, 1), "dims": ["大组"],
          "comparison": True, "currency": "USD"}, "leadership"),
        # 复合值排除 × 分组 × TopN
        ("cf-composite-exclude", "近7天各销售小组的销售额，排除一部-B组，取最高的前5个",
         {"dims": ["销售小组"], "metrics": ["销售额"], "limit": 5, "order_desc": True,
          "filters": [("team_name", "!=", "一部-B组")],
          "no_filter_field": "large_team_name"}, "leadership"),
        # 全角 × 单日语义 × TopN × 口语
        ("cf-fullwidth-topn", "近７天哪5个平台卖得钱最多",
         {"time": last_n(7), "dims": ["平台"]}, "novice"),
        ("cf-fullwidth-money", "近７天各平台卖了多少钱，取最高的前5个",
         {"time": last_n(7), "dims": ["平台"], "metrics": ["销售额"],
          "limit": 5, "order_desc": True}, "novice"),
        # 疑问代词 × 排除
        ("cf-interrogative-exclude", "近7天销售额排前5的平台是哪些，排除亚马逊VC",
         {"dims": ["平台"], "limit": 5,
          "filters": [("platform_name", "!=", "Amazon VC")]}, "novice"),
        # 派生指标 × 环比 × 币种
        ("cf-derived-mom", "广告费数据集本月各平台的SP广告占比，环比上一周期",
         {"metrics": ["SP广告占比"], "dims": ["平台"], "comparison": True}, "leadership"),
        ("cf-margin-currency", "近7天各平台的毛利率，用美元口径",
         {"metrics": ["毛利率"], "dims": ["平台"], "currency": "USD"}, "leadership"),
        # 含「的」的维度标签 × TopN × 环比
        ("cf-de-label", "物控库存周转近7天各目的国的国内中转仓库存，取最高的前5个",
         {"dims": ["目的国"], "metrics": ["国内中转仓库存"], "limit": 5,
          "order_desc": True}, "leadership"),
        # 斜杠标签 × 分组 × 币种
        ("cf-slash-label", "即时综合数据集昨天每个新/老品(物控编码)的销售额，用美元口径",
         {"dims": ["新/老品(物控编码)"], "metrics": ["销售额"], "currency": "USD"}, "leadership"),
        # 业务术语别名 × 筛选 × 多币种
        ("cf-alias-multi-cur", "近7天九部各平台的营业额，分别用人民币和加拿大元展示",
         {"metrics": ["销售额"], "dims": ["平台"],
          "filters": [("dept_name", "=", "九部")],
          "multi_currency": ["CNY", "CAD"]}, "novice"),
        # 口语时间 × 口语指标 × 口语分组
        ("cf-all-casual", "前天分平台看卖了多少钱",
         {"time": day_offset(2), "dims": ["平台"], "metrics": ["销售额"]}, "novice"),
        ("cf-all-casual2", "上个月每个大组卖了多少个",
         {"time": last_month(), "dims": ["大组"], "metrics": ["销量"]}, "novice"),
        # 编号部门 × 大组维度 × 排除平台
        ("cf-dept-bigteam-exclude", "近7天项目九部各大组的销售额，排除亚马逊VC",
         {"dims": ["大组"], "metrics": ["销售额"],
          "filters": [("dept_name", "=", "项目九部"),
                      ("platform_name", "!=", "Amazon VC")]}, "leadership"),
    ]
    return [
        Case(case_id=case_id, suite="conflict", prompt=prompt,
             expect=_normalize_expect(expect), persona=persona, parts=(case_id,))
        for case_id, prompt, expect, persona in specs
    ]


def _normalize_expect(raw: dict[str, Any]) -> dict[str, Any]:
    """把手写预期补齐成 check() 需要的形状。"""
    merged: dict[str, Any] = {
        "metrics": [], "dims": [], "filters": [], "dim_absent": [],
        "no_filter_field": [], "no_filter_value": []
    }
    for name, value in raw.items():
        if name in ("metrics", "dims", "filters", "dim_absent"):
            merged[name] = list(value)
        elif name == "no_filter_field":
            merged["no_filter_field"] = [value] if isinstance(value, str) else list(value)
        else:
            merged[name] = value
    return merged


def run_case(case: Case, email: str) -> Result:
    try:
        contract = run_plan(case.prompt, user_email=email)
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}"
        return Result(case=case, error=detail)
    return Result(
        case=case,
        status=str(contract.get("status")),
        failures=check(case, contract),
        contract=contract,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="chenbenli@aukeys.com")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/planner-audit-20260909")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--persona", action="append", help="leadership / novice；缺省全部")
    parser.add_argument("--suite", action="append")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--tag", default="interaction")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="续跑：跳过结果文件里已完成的用例，剩余部分追加写入（本机内存吃紧时任务可能被中途结束）",
    )
    args = parser.parse_args()

    personas = set(args.persona or ["leadership", "novice", "all"])
    cases = build_cases(personas)
    if args.suite:
        want = set(args.suite)
        cases = [c for c in cases if c.suite in want]
    if args.max_cases:
        cases = cases[: args.max_cases]
    print(f"交叉用例 {len(cases)}（片段 {len(fragments())}）")

    # 逐条写盘后立即释放完整合同：1800 余份合同全部留在内存里时峰值有数 GB，
    # 本机同时开着其他应用时整条验证链会被系统低内存结束（2026-09-10 连续两次）。
    # 输出文件的内容与顺序不变；汇总在跑完后从结果文件全量统计，续跑时也能合并。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{args.tag}-results.jsonl"
    if args.resume and out.exists():
        done = {json.loads(line)["case_id"] for line in out.open(encoding="utf-8") if line.strip()}
        cases = [c for c in cases if c.case_id not in done]
        print(f"续跑：结果文件已有 {len(done)} 条，本次补跑 {len(cases)} 条")
    mode = "a" if args.resume else "w"
    with out.open(mode, encoding="utf-8") as handle, futures.ThreadPoolExecutor(args.workers) as pool:
        for res in pool.map(lambda c: run_case(c, args.email), cases):
            if not res.ok:
                print(f"[{'ERR' if res.error else 'FAIL'}] {res.case.case_id}")
                print(f"        {res.case.prompt}")
                for item in (res.failures or [res.error])[:3]:
                    print(f"        - {str(item)[:180]}")
            handle.write(json.dumps({
                "case_id": res.case.case_id, "suite": res.case.suite,
                "persona": res.case.persona, "parts": list(res.case.parts),
                "prompt": res.case.prompt, "expect": res.case.expect,
                "status": res.status, "ok": res.ok,
                "failures": res.failures, "error": res.error,
                "model_view": (res.contract or {}).get("model_view"),
                "template": _tpl(res.contract or {}),
            }, ensure_ascii=False, default=str) + "\n")
            handle.flush()

    # 汇总按结果文件全量统计：续跑时包含此前已完成的部分
    records = [json.loads(line) for line in out.open(encoding="utf-8") if line.strip()]
    bad = [r for r in records if not r["ok"]]
    print("\n==== 汇总 ====")
    print(f"总用例 {len(records)}，失败 {len(bad)}")
    for suite, count in Counter(r["suite"] for r in bad).most_common():
        total = sum(1 for r in records if r["suite"] == suite)
        print(f"  {suite}: {count}/{total}")
    part_fail = Counter(part for r in bad for part in r["parts"])
    if part_fail:
        print("参与失败最多的片段：")
        for name, count in part_fail.most_common(12):
            print(f"  {name}: {count}")
    combo_fail = Counter(
        tuple(sorted(pair))
        for r in bad
        for pair in itertools.combinations(r["parts"], 2)
    )
    if combo_fail:
        print("最常同时出现的失败片段对：")
        for pair, count in combo_fail.most_common(10):
            print(f"  {pair[0]} + {pair[1]}: {count}")
    print(f"明细：{out}")


if __name__ == "__main__":
    main()
