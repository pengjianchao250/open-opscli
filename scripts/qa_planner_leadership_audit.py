#!/usr/bin/env python3
"""领导汇报视角的规划器全量审计。

覆盖当前账号全部授权数据集，用领导口吻的自然语言构造基线/多指标/趋势/TopN/
环比/快照/组件筛选等组合，逐条与独立计算的预期（时间窗口、指标、维度、排序、
行数、筛选极性）对照，输出结构化缺陷清单。

只调用 opscli.query 内核入口 run_plan，不直连后端 HTTP（铁律11）。
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import re
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opscli.query.services.manager import QueryManager
from opscli.query.services.planner.entry import run_plan

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------- 时间预期
def today() -> date:
    """审计基准日：与规划器一致，取 Asia/Shanghai 当前日期。"""
    from datetime import datetime

    return datetime.now(TZ).date()


def win_last_n_days(n: int) -> tuple[str, str]:
    """近 N 天（含今天）：与规划器口径一致。"""
    end = today()
    start = end - timedelta(days=n - 1)
    return start.isoformat(), end.isoformat()


def win_this_month() -> tuple[str, str]:
    """本月整自然月：1 日至月末。"""
    t = today()
    start = t.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat(), (nxt - timedelta(days=1)).isoformat()


def win_last_month() -> tuple[str, str]:
    """上月整自然月。"""
    t = today()
    first = t.replace(day=1)
    last_end = first - timedelta(days=1)
    return last_end.replace(day=1).isoformat(), last_end.isoformat()


def win_yesterday() -> tuple[str, str]:
    d = (today() - timedelta(days=1)).isoformat()
    return d, d


# ---------------------------------------------------------------- 用例模型
@dataclass
class Case:
    case_id: str
    suite: str
    prompt: str
    expect: dict[str, Any] = dc_field(default_factory=dict)
    note: str = ""
    fields: tuple[str, ...] = ()


@dataclass
class Result:
    case: Case
    status: str = ""
    ok: bool = False
    failures: list[str] = dc_field(default_factory=list)
    contract: dict[str, Any] | None = None
    error: str = ""


# ---------------------------------------------------------------- 元数据
def load_meta(email: str) -> dict[int, dict]:
    """按 table_id 汇总数据集与字段（走内核缓存，不直连后端）。"""
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
        }
    return out


# 领导常用的分组维度优先级（存在即优先选取）
_DIM_PRIORITY = ["平台", "渠道", "国家", "部门", "销售小组", "大组", "品牌", "开发小组", "品类", "店铺"]
# 领导常用指标优先级
_METRIC_PRIORITY = ["销售额", "销量", "广告费", "退款金额", "毛利", "点击量", "曝光量", "退款数量"]


def pick_dim(ds: dict) -> dict | None:
    """挑一个适合领导口吻分组的维度：优先业务组织维度，排除日期/长文本。"""
    labels = {str(d.get("verbose_name")): d for d in ds["dims"]}
    for want in _DIM_PRIORITY:
        if want in labels:
            return labels[want]
    for d in ds["dims"]:
        name = str(d.get("verbose_name") or "")
        if not name or name in ("日期",) or "日期" in name or "时间" in name:
            continue
        if str(d.get("groupable")) in ("0", "False", "false"):
            continue
        if len(name) > 8 or "链接" in name or "图片" in name:
            continue
        return d
    return None


def pick_metrics(ds: dict, n: int = 2, snapshot: bool | None = None) -> list[dict]:
    """挑 n 个指标；snapshot=True 只取快照指标，False 只取非快照。"""
    pool = []
    for m in ds["metrics"]:
        snap = str(m.get("snapshot_metric")) in ("1", "True", "true")
        if snapshot is True and not snap:
            continue
        if snapshot is False and snap:
            continue
        name = str(m.get("verbose_name") or "")
        if not name or len(name) > 12:
            continue
        pool.append(m)
    ordered = []
    labels = {str(m.get("verbose_name")): m for m in pool}
    for want in _METRIC_PRIORITY:
        if want in labels and labels[want] not in ordered:
            ordered.append(labels[want])
    for m in pool:
        if m not in ordered:
            ordered.append(m)
    return ordered[:n]


def has_date_field(ds: dict) -> bool:
    return any("日期" in str(d.get("verbose_name") or "") for d in ds["dims"])


# ---------------------------------------------------------------- 用例生成
def build_dataset_cases(meta: dict[int, dict]) -> list[Case]:
    """按数据集生成领导汇报口吻的组合用例。"""
    cases: list[Case] = []
    s7, e7 = win_last_n_days(7)
    sm, em = win_this_month()
    slm, elm = win_last_month()

    for tid, ds in sorted(meta.items()):
        if ds["category"] == "query_component":
            continue
        name = ds["name"]
        dim = pick_dim(ds)
        mets = pick_metrics(ds, 2, snapshot=False)
        if not dim or not mets:
            continue
        dim_zh = str(dim["verbose_name"])
        m1 = str(mets[0]["verbose_name"])
        m2 = str(mets[1]["verbose_name"]) if len(mets) > 1 else None
        dated = has_date_field(ds)

        # 1) 基线：单维度单指标 + 相对时间
        cases.append(Case(
            f"t{tid}-baseline", "leadership_baseline",
            f"帮我从{name}里看一下近7天各{dim_zh}的{m1}",
            {"status": "planned", "table_id": tid, "metrics": [m1], "dims": [dim_zh],
             "time": (s7, e7) if dated else None},
        ))
        # 2) 多指标：领导常一次要两个口径
        if m2:
            cases.append(Case(
                f"t{tid}-multi", "leadership_multi_metric",
                f"{name}本月各{dim_zh}的{m1}和{m2}分别是多少",
                {"status": "planned", "table_id": tid, "metrics": [m1, m2], "dims": [dim_zh],
                 "time": (sm, em) if dated else None, "order_absent": True},
            ))
        # 3) 趋势：必须补日期维度并按日期升序
        if dated:
            cases.append(Case(
                f"t{tid}-trend", "leadership_trend",
                f"{name}近7天{m1}的按日趋势",
                {"status": "planned", "table_id": tid, "metrics": [m1],
                 "time": (s7, e7), "trend": True},
            ))
        # 4) TopN：单指标降序 + limit
        cases.append(Case(
            f"t{tid}-topn", "leadership_topn",
            f"{name}上月{m1}最高的前5个{dim_zh}",
            {"status": "planned", "table_id": tid, "metrics": [m1], "dims": [dim_zh],
             "time": (slm, elm) if dated else None, "limit": 5, "order_desc": True},
        ))
        # 5) 环比：主周期 + dataComparison
        if dated:
            cases.append(Case(
                f"t{tid}-mom", "leadership_comparison",
                f"{name}本月各{dim_zh}的{m1}环比上月怎么样",
                {"status": "planned", "table_id": tid, "metrics": [m1], "dims": [dim_zh],
                 "time": (sm, em), "comparison": True},
            ))
        # 6) 快照指标：窗口收敛到最新完整快照日
        snaps = pick_metrics(ds, 1, snapshot=True)
        if snaps and dated:
            sn = str(snaps[0]["verbose_name"])
            cases.append(Case(
                f"t{tid}-snapshot", "leadership_snapshot",
                f"{name}近7天各{dim_zh}的{sn}",
                {"status": "planned", "table_id": tid, "metrics": [sn], "dims": [dim_zh],
                 "snapshot": True},
            ))
            # 7) 快照 + 流量指标混查且未按日分组 → 必须澄清
            cases.append(Case(
                f"t{tid}-snapmix", "leadership_snapshot_conflict",
                f"{name}近7天各{dim_zh}的{sn}和{m1}",
                {"status": "clarify_required", "codes": ["snapshot_metric_window_conflict"]},
            ))
    return cases


def build_semantic_cases(meta: dict[int, dict]) -> list[Case]:
    """跨数据集的语义/口径用例：时间、别名、平台语义、币种、组件筛选、极性。"""
    cases: list[Case] = []
    s7, e7 = win_last_n_days(7)
    s30, e30 = win_last_n_days(30)
    sm, em = win_this_month()
    slm, elm = win_last_month()
    ys, ye = win_yesterday()
    t = today()

    def add(cid, suite, prompt, expect, note="", fields=()):
        cases.append(Case(cid, suite, prompt, expect, note, fields))

    # --- 时间口径 ---
    add("time-7d", "time_scope", "近7天各平台的销售额", {"status": "planned", "time": (s7, e7)})
    add("time-30d", "time_scope", "近30天各平台的销售额", {"status": "planned", "time": (s30, e30)})
    add("time-thismonth", "time_scope", "本月各平台的销售额", {"status": "planned", "time": (sm, em)})
    add("time-lastmonth", "time_scope", "上月各平台的销售额", {"status": "planned", "time": (slm, elm)})
    add("time-yesterday", "time_scope", "昨天各平台的销售额", {"status": "planned", "time": (ys, ye)})
    add("time-none", "time_scope", "各平台的销售额", {"status": "clarify_required", "codes": ["time_scope_confirmation"]})
    add("time-prev7", "time_scope", "前7天各平台的销售额", {"status": "planned", "time_not_limit": True})
    add("time-explicit", "time_scope", "2026年8月1日到2026年8月15日各平台的销售额",
        {"status": "planned", "time": ("2026-08-01", "2026-08-15")})
    add("time-en-month", "time_scope", "Aug 2026 各平台的销售额", {"status": "planned", "time": ("2026-08-01", "2026-08-31")})
    add("time-cross-year", "time_scope", "2025年12月25日到2026年1月5日各平台的销售额",
        {"status": "planned", "time": ("2025-12-25", "2026-01-05")})
    add("time-q", "time_scope", "今年第一季度各平台的销售额", {"status": "planned", "time": (f"{t.year}-01-01", f"{t.year}-03-31")})

    # --- 指标别名映射 ---
    for alias, canon in [("订单量", "销量"), ("单量", "销量"), ("销售金额", "销售额"), ("收入", "销售额")]:
        add(f"alias-{alias}", "metric_alias", f"近7天各平台的{alias}",
            {"status": "planned", "metrics": [canon], "alias_map": alias})
    add("alias-adcost", "metric_alias", "近7天各平台的广告花费",
        {"status": "planned", "metrics": ["广告费"], "alias_map": "广告花费"})
    # 完整标签内嵌短别名不得另算指标
    add("alias-embedded", "metric_alias", "近7天各平台的主营业务收入",
        {"status": None, "no_extra_metric": True})

    # --- TopN / 排序 ---
    add("topn-front3", "topn", "近7天销售额最高的前3个平台", {"status": "planned", "limit": 3, "order_desc": True})
    add("topn-cn10", "topn", "近7天销售额前十的平台", {"status": "planned", "limit": 10, "order_desc": True})
    add("topn-top5", "topn", "近7天 top5 平台的销售额", {"status": "planned", "limit": 5, "order_desc": True})
    add("topn-not-time", "topn", "前7天各平台的销售额", {"status": "planned", "limit_absent": True})
    add("topn-not-time2", "topn", "前3个月各平台的销售额", {"status": "planned", "limit_absent": True})
    # order_unresolved 只在"用户确实要了排序或行数"时才该出现；纯多指标查询不该有排序
    add("topn-multi-metric", "topn", "近7天各平台的销售额和销量",
        {"status": "planned", "order_absent": True})
    add("topn-multi-metric-ask", "topn", "近7天各平台的销售额和销量，前5",
        {"status": "planned", "order_absent": True, "order_unresolved": True})
    add("topn-explicit-asc", "topn", "近7天各平台的销售额和销量，按销量升序",
        {"status": "planned", "order_desc": False})

    # --- 趋势 ---
    add("trend-daily", "trend", "近7天销售额的按日趋势", {"status": "planned", "trend": True, "time": (s7, e7)})
    add("trend-everyday", "trend", "近7天每天的销售额", {"status": "planned", "trend": True})
    add("trend-negated", "trend", "近7天的销售额，不按日拆分", {"status": "planned", "trend": False})

    # --- 平台语义 ---
    add("plat-amazon", "platform", "近7天亚马逊的销售额",
        {"status": "planned", "platform_members": ["亚马逊SC", "亚马逊VC"]})
    add("plat-amazon-sc", "platform", "近7天亚马逊SC的销售额", {"status": "planned", "platform_members": ["亚马逊SC"]})
    add("plat-amazon-vc", "platform", "近7天亚马逊VC的销售额", {"status": "planned", "platform_members": ["亚马逊VC"]})
    add("plat-tiktok", "platform", "近7天TikTok的销售额", {"status": "planned", "platform_members": ["TikTok"]})

    # --- 币种 ---
    for code, word in [("USD", "美元"), ("CAD", "加元"), ("EUR", "欧元"), ("JPY", "日元"), ("GBP", "英镑")]:
        add(f"cur-{code}", "currency", f"近7天各平台的销售额，用{word}口径",
            {"status": "planned", "currency": code})
    add("cur-hkd", "currency", "近7天各平台的销售额，用港币口径",
        {"status": "clarify_required", "codes": ["unsupported_currency"]})
    add("cur-multi", "currency", "近7天各平台的销售额，分别用人民币和加拿大元展示",
        {"status": "planned", "multi_currency": ["CNY", "CAD"]})

    # --- 组件筛选：分组词不得当筛选值 ---
    add("comp-group-word", "component_filter", "近7天按部门看销售额", {"status": "planned", "dims": ["部门"], "no_filter_on": "dept_name"})
    add("comp-group-word2", "component_filter", "近7天各事业部的销售额", {"status": None})
    add("comp-groupby-en", "component_filter", "近7天 group by 部门 的销售额", {"status": "planned", "dims": ["部门"], "no_filter_on": "dept_name"})

    # --- 排除极性 ---
    add("excl-single", "polarity", "近7天各平台销售额，排除亚马逊VC", {"status": None, "exclude_expected": True})
    add("excl-multi", "polarity", "近7天各渠道销售额，排除TikTok和Temu", {"status": None, "exclude_expected": True})
    add("excl-conflict", "polarity", "近7天只看亚马逊SC，同时排除亚马逊SC的销售额",
        {"status": "clarify_required", "codes_any": ["component_filter_polarity_conflict"]})

    # --- 组件枚举意图 ---
    add("enum-zh", "component_enum", "列出当前可见的部门", {"status": "planned", "component_query": True})
    add("enum-zh2", "component_enum", "有哪些渠道可选", {"status": "planned", "component_query": True})
    add("enum-en", "component_enum", "show available 部门", {"status": "planned", "component_query": True})
    add("enum-en2", "component_enum", "what values are available for 渠道", {"status": "planned", "component_query": True})
    add("enum-business-block", "component_enum", "近7天 available inventory 有多少",
        {"status_not": "planned_component", "no_component_target": True})

    # --- 字段不存在 ---
    add("miss-metric", "not_in_dataset", "近7天各平台的净推荐值",
        {"status": "clarify_required", "codes_any": ["metric_not_in_dataset", "dataset_confirmation_required"]})
    add("miss-dim", "not_in_dataset", "近7天各仓库的销售额",
        {"status": "clarify_required", "codes_any": ["dimension_not_in_dataset", "dataset_confirmation_required"]})

    # --- 多指标完整性 ---
    add("metric-complete", "metric_completeness", "近7天各平台的收入及毛利",
        {"status": None, "metrics_all_or_clarify": ["销售额", "毛利"]})

    # --- 大组维度（回归点） ---
    add("dim-bigteam", "dimension_label", "近7天各大组的销售额", {"status": "planned", "dims": ["大组"]})
    add("dim-bigteam2", "dimension_label", "近7天每个大组的销量", {"status": "planned", "dims": ["大组"]})
    add("dim-bigplatform", "dimension_label", "近7天各大平台的销售额", {"status": "planned", "dims": ["平台"]})
    add("dim-smallteam", "dimension_label", "近7天各销售小组的销售额", {"status": "planned", "dims": ["销售小组"]})
    add("dim-devteam", "dimension_label", "近7天各开发小组的销售额", {"status": "planned", "dims": ["开发小组"]})
    add("dim-bigcat", "dimension_label", "近7天各大品类的销售额", {"status": None})

    # --- 本轮修复的缺陷回归位 ---
    add("reg-quarter-thisyear", "regression", "今年第一季度各平台的销售额",
        {"status": "planned", "time": (f"{t.year}-01-01", f"{t.year}-03-31")})
    add("reg-quarter-q1", "regression", "今年Q1各平台的销售额",
        {"status": "planned", "time": (f"{t.year}-01-01", f"{t.year}-03-31")})
    add("reg-quarter-lastyear", "regression", "去年第四季度各平台的销售额",
        {"status": "planned", "time": (f"{t.year - 1}-10-01", f"{t.year - 1}-12-31")})
    add("reg-quarter-bare", "regression", "第2季度各平台的销售额",
        {"status": "planned", "time": (f"{t.year}-04-01", f"{t.year}-06-30")})
    add("reg-bigteam", "regression", "近7天各大组的销售额", {"status": "planned", "dims": ["大组"]})
    add("reg-dim-not-swallowed", "regression", "即时综合数据集近7天各平台的平台库存",
        {"status": "planned", "dims": ["平台"], "metrics": ["平台库存"]})
    add("reg-exact-label", "regression", "退款产地数据集上月销售额最高的前5个平台",
        {"status": "planned", "table_id": 27, "metrics": ["销售额"],
         "limit": 5, "order_desc": True, "metric_count": 1})
    add("reg-date-anchor", "regression", "转运预估和实际账单近7天调拨数量的按日趋势",
        {"status": "planned", "table_id": 99, "trend": True, "date_field": "date_id"})
    add("reg-date-anchor2", "regression", "物流费用账单数据集近7天各渠道的包裹长",
        {"status": "planned", "table_id": 76, "date_field": "date_id"})
    add("reg-unknown-metric", "regression", "近7天各平台的净推荐值",
        {"status": "clarify_required", "codes": ["metric_not_in_dataset"]})
    add("reg-enum-dept", "regression", "列出当前可见的部门",
        {"status": "planned", "table_id": 40, "component_query": True})
    add("reg-enum-channel", "regression", "有哪些渠道可选",
        {"status": "planned", "table_id": 7, "component_query": True})
    add("reg-enum-team", "regression", "列出当前可见的销售小组",
        {"status": "planned", "table_id": 11, "component_query": True})
    add("reg-plat-exclude", "regression", "近7天各平台销售额，排除亚马逊VC",
        {"status": "planned", "filter_expect": ("platform_name", "!=", "Amazon VC")})
    add("reg-plat-exclude-multi", "regression", "近7天各渠道销售额，排除TikTok和Temu",
        # 平台授权值已改为确定性排序（IN 列表顺序无语义，排序后规划结果可复现）
        {"status": "planned", "filter_expect": ("platform_name", "not_in", ["Temu", "Tiktok"]),
         "no_filter_on": "team_name"})
    add("reg-composite-team", "regression", "近7天各销售小组的销售额，排除一部-B组",
        {"status": "planned", "filter_expect": ("team_name", "!=", "一部-B组"),
         "no_filter_on": "dept_name"})
    add("reg-composite-team-include", "regression", "近7天一部-B组的销售额",
        {"status": "planned", "filter_expect": ("team_name", "=", "一部-B组"),
         "no_filter_on": "large_team_name"})
    add("reg-dept-plain", "regression", "近7天各销售小组销售额，排除一部和B组",
        {"status": "planned", "filter_expect": ("dept_name", "!=", "一部")})
    add("reg-dept-numeral", "regression", "近7天项目九部的销售额",
        {"status": "planned", "filter_expect": ("dept_name", "=", "项目九部")})
    add("reg-dept-numeral2", "regression", "近7天九部的销售额",
        {"status": "planned", "filter_expect": ("dept_name", "=", "九部")})
    add("reg-polarity", "regression", "近7天只看亚马逊SC，同时排除亚马逊SC的销售额",
        {"status": "clarify_required", "codes": ["component_filter_polarity_conflict"]})

    # --- 暴力/对抗测试暴露并修复的缺陷回归位 ---
    add("reg-punct-enum", "regression", "海运在途SKU明细上月各原产国/地区的包装长CM",
        {"status": "planned", "table_id": 84, "no_filter_on": "brand_name"})
    add("reg-punct-enum2", "regression", "SP搜索词数据集本月点击量最高的前5个匹配/投放类型",
        {"status": "planned", "table_id": 48, "no_filter_on": "brand_name"})
    add("reg-label-value", "regression", "净利分解数据集上月各美国或非美的关税",
        {"status": "planned", "table_id": 43, "dims": ["美国或非美"], "metrics": ["关税"],
         "no_filter_on": "country_name"})
    add("reg-negation-label", "regression",
        "库存周转数据集近7天各部门的周转天数(不含在途)和总周转天数",
        {"metrics_all_or_clarify": ["周转天数(不含在途)", "总周转天数"]})
    add("reg-negation-real", "regression", "近7天的销售额，不按日拆分",
        {"status": "planned", "trend": False})
    add("reg-fullwidth-time", "regression", "近７天各平台的销售额",
        {"status": "planned", "time": (s7, e7)})
    add("reg-fullwidth-month", "regression", "２０２６年８月各平台的销售额",
        {"status": "planned", "time": ("2026-08-01", "2026-08-31")})
    add("reg-single-date", "regression", "2026年8月15日各平台的销售额",
        {"status": "planned", "time": ("2026-08-15", "2026-08-15")})
    add("reg-single-date2", "regression", "8月15日各平台的销售额",
        {"status": "planned", "time": (f"{t.year}-08-15", f"{t.year}-08-15")})
    add("reg-single-date-iso", "regression", "2026-08-15各平台的销售额",
        {"status": "planned", "time": ("2026-08-15", "2026-08-15")})
    add("reg-month-still-month", "regression", "2026年8月各平台的销售额",
        {"status": "planned", "time": ("2026-08-01", "2026-08-31")})
    add("reg-union-swallow", "regression",
        "近7天各平台各国家各渠道各部门各品牌各销售小组各大组的销售额",
        {"status": "planned", "dims": ["平台", "国家", "渠道", "部门", "品牌", "销售小组", "大组"],
         "dim_count": 7})
    add("reg-sales-person", "regression", "近7天各销售的销售额",
        {"status": "planned", "dims": ["销售"]})
    add("reg-particle-value", "regression", "净利分解数据集近30天各公司SKU的管理费用-网络费",
        {"status": "planned", "table_id": 43, "dims": ["公司SKU"],
         "metrics": ["管理费用-网络费"], "no_filter_on": "b_ed_sku"})
    add("reg-shadow-parent-sku", "regression",
        "即时综合数据集今年第一季度各品牌和各父公司SKU的销售额",
        {"status": "planned", "dims": ["品牌", "父公司SKU"], "no_filter_on": "ed_sku"})
    add("reg-shadow-team-label", "regression", "近7天销售小组一部-B组的销售额",
        {"status": "planned", "filter_expect": ("team_name", "=", "一部-B组"),
         "no_filter_on": "team_username"})
    add("reg-team-username-filter", "regression", "近7天销售是张三的销售额",
        {"status": "clarify_required", "codes_any": ["component_filter_value_unmatched"]})
    add("reg-dept-suffix-metric", "regression", "入库预估和实际账单上月各品牌的物流部承担金额",
        {"status": "planned", "table_id": 97, "dims": ["品牌"],
         "metrics": ["物流部承担金额"], "no_filter_on": "dept_name"})
    add("reg-dept-suffix-metric2", "regression",
        "入库预估和实际账单近7天各柜型的物流部承担金额，用美元口径",
        {"status": "planned", "table_id": 97, "currency": "USD", "no_filter_on": "dept_name"})
    add("reg-dept-still-filters", "regression", "近7天九部的销售额",
        {"status": "planned", "filter_expect": ("dept_name", "=", "九部")})
    add("reg-grouping-not-filter", "regression", "SKU仓库库龄明细上月各事业部每天的31-60天库龄走势",
        {"status": "planned", "table_id": 54, "dims": ["事业部"], "no_filter_on": "org_name"})
    add("reg-grouping-pair", "regression", "Wayfair退货退款昨天各产品名称和各销售小组的退款金额(原币)",
        {"status": "planned", "table_id": 63, "dims": ["产品名称", "销售小组"],
         "no_filter_on": "team_name"})
    add("reg-grouping-pair2", "regression", "净利分解数据集近30天各美国或非美和各公司SKU的销售成本",
        {"status": "planned", "table_id": 43, "dims": ["美国或非美", "公司SKU"],
         "no_filter_on": "b_ed_sku"})
    add("reg-labeled-filter", "regression", "近7天部门是九部的销售额",
        {"status": "planned", "filter_expect": ("dept_name", "=", "九部")})
    add("reg-group-and-filter", "regression", "近7天各部门的销售额，只看九部",
        {"status": "planned", "dims": ["部门"],
         "filter_expect": ("dept_name", "=", "九部")})
    add("reg-label-with-de", "regression", "物控库存周转近7天各目的国的国内中转仓库存",
        {"status": "planned", "table_id": 29, "dims": ["目的国"]})
    add("reg-label-with-de2", "regression", "海运在途SKU明细上季度各目的国家的总毛重KG",
        {"status": "planned", "table_id": 84, "dims": ["目的国家"]})
    add("reg-single-char-label", "regression", "集团在职花名册近7天各岗的人数",
        {"dims": ["岗"], "no_code": "dimension_not_in_dataset"})
    add("reg-devteam-alias", "regression", "发货数据集上季度各品类和各开发小组的广告费",
        {"status": "planned", "table_id": 2, "dims": ["品类", "开发小组"],
         "no_filter_on": "team_name"})
    add("reg-devteam-alias2", "regression",
        "亚马逊VC退货退款近14天各销售和各开发小组的退款金额(原币)",
        {"status": "planned", "table_id": 72, "dims": ["销售", "开发小组"],
         "no_filter_on": "team_name"})

    # --- 初级业务视角矩阵暴露并修复的缺陷回归位 ---
    add("nv-reg-money", "regression", "近7天各平台卖了多少钱",
        {"status": "planned", "dims": ["平台"], "metrics": ["销售额"]})
    add("nv-reg-qty", "regression", "近7天各平台卖了多少个",
        {"status": "planned", "dims": ["平台"], "metrics": ["销量"]})
    add("nv-reg-orders", "regression", "近7天各平台有多少单",
        {"status": "planned", "dims": ["平台"], "metrics": ["销量"]})
    add("nv-reg-salesqty", "regression", "近7天各平台的销售量",
        {"status": "planned", "dims": ["平台"], "metrics": ["销量"], "dim_count": 1})
    add("nv-reg-salespieces", "regression", "近7天各平台的销售件数",
        {"status": "planned", "dims": ["平台"], "metrics": ["销量"], "dim_count": 1})
    add("nv-reg-revenue-alias", "regression", "近7天各平台的营业额",
        {"status": "planned", "metrics": ["销售额"]})
    add("nv-reg-gmv", "regression", "近7天各平台的GMV",
        {"status": "planned", "metrics": ["销售额"]})
    add("nv-reg-adspend", "regression", "近7天各平台的广告支出",
        {"status": "planned", "metrics": ["广告费"]})
    add("nv-reg-purchase", "regression", "近7天各平台的进货成本",
        {"status": "planned", "metrics": ["采购成本"]})
    add("nv-reg-salesperson", "regression", "近7天各销售的销售额",
        {"status": "planned", "dims": ["销售"], "metrics": ["销售额"]})
    add("nv-reg-daybefore", "regression", "前天各平台的销售额",
        {"status": "planned", "time": ((t - timedelta(days=2)).isoformat(),) * 2})
    add("nv-reg-daybefore2", "regression", "大前天各平台的销售额",
        {"status": "planned", "time": ((t - timedelta(days=3)).isoformat(),) * 2})
    add("nv-reg-which-n", "regression", "近7天哪5个平台销售额最高",
        {"status": "planned", "dims": ["平台"], "limit": 5, "order_desc": True})
    add("nv-reg-interrogative", "regression", "近7天销售额排前5的平台是哪些",
        {"status": "planned", "dims": ["平台"], "limit": 5})
    add("nv-reg-labeled-filter", "regression", "近7天平台是亚马逊SC的销售额",
        {"status": "planned", "filter_expect": ("platform_name", "=", "Amazon")})
    add("nv-reg-mom-casual", "regression", "近7天各平台的销售额跟上个周期比怎么样",
        {"status": "planned", "comparison": True})
    add("nv-reg-sellbest", "regression", "近7天卖得最好的3个平台",
        {"status": "planned", "dims": ["平台"], "order_unresolved": True})
    add("nv-reg-component-enum", "regression", "查询组件产品数据集近7天的公司SKU有哪些",
        {"status": "planned", "table_id": 9, "component_query": True})
    add("nv-reg-component-enum2", "regression", "查询组件渠道数据集近7天的渠道名称有哪些",
        {"status": "planned", "table_id": 7, "component_query": True})
    add("nv-reg-colloquial-de", "regression", "近7天各平台的卖了多少钱",
        {"status": "planned", "dims": ["平台"], "metrics": ["销售额"]})
    add("nv-reg-derived-metric", "regression", "广告费数据集本月的SP广告占比",
        {"status": "planned", "table_id": 12, "metrics": ["SP广告占比"]})
    add("nv-reg-derived-metric2", "regression", "净利分解数据集昨天的毛利率",
        {"status": "planned", "table_id": 43, "metrics": ["毛利率"]})
    add("nv-reg-slash-label", "regression", "即时综合数据集昨天每个新/老品(物控编码)的星级",
        {"status": "planned", "table_id": 1, "dims": ["新/老品(物控编码)"]})

    # --- 特性交叉兼容矩阵暴露并修复的缺陷回归位 ---
    add("ix-reg-yoy-window", "regression", "近7天各平台的销售额，同比去年同期",
        {"status": "planned", "time": (s7, e7), "comparison": True})
    add("ix-reg-yoy-window2", "regression", "上个月各平台的销售额，同比去年同期",
        {"status": "planned", "time": (slm, elm), "comparison": True})
    add("ix-reg-yoy-window3", "regression", "前天各平台的销售额，同比去年同期",
        {"status": "planned", "time": ((t - timedelta(days=2)).isoformat(),) * 2,
         "comparison": True})
    add("ix-reg-lastyear-still-works", "regression", "去年各平台的销售额",
        {"status": "planned", "time": (f"{t.year - 1}-01-01", f"{t.year - 1}-12-31")})
    add("ix-reg-order-suffix", "regression", "近7天各平台的销量，取销售额最高的前5个",
        {"status": "planned", "limit": 5, "order_desc": True})
    add("ix-reg-order-suffix2", "regression", "近7天各平台的销量，哪5个销售额最高",
        {"status": "planned", "limit": 5, "order_desc": True})
    add("ix-reg-measure-window", "regression", "近7天各平台卖了多少钱，取最高的前5个",
        {"status": "planned", "dims": ["平台"], "metrics": ["销售额"],
         "limit": 5, "order_desc": True})
    add("ix-reg-platform-literal", "regression", "近7天亚马逊SC各平台的销售额，排除TikTok和Temu",
        {"status": "planned", "no_filter_on": "team_name"})

    # --- 近义词 / 综合报表矩阵暴露并修复的缺陷回归位 ---
    add("syn-reg-exclude-tichu", "regression", "近7天各平台的销售额，剔除亚马逊VC",
        {"status": "planned", "filter_expect": ("platform_name", "!=", "Amazon VC")})
    add("syn-reg-exclude-postfix", "regression", "近7天各平台的销售额，亚马逊VC除外",
        {"status": "planned", "filter_expect": ("platform_name", "!=", "Amazon VC")})
    add("syn-reg-exclude-postfix2", "regression", "近7天各平台的销售额，亚马逊VC以外",
        {"status": "planned", "filter_expect": ("platform_name", "!=", "Amazon VC")})
    add("syn-reg-include-still-works", "regression", "近7天亚马逊VC的销售额",
        {"status": "planned", "filter_expect": ("platform_name", "=", "Amazon VC")})
    add("syn-reg-dept-alias", "regression", "近7天各事业部的销售额",
        {"status": "planned", "dims": ["部门"], "metrics": ["销售额"]})
    add("syn-reg-dept-alias-exact", "regression",
        "SKU仓库库龄明细上月各事业部每天的31-60天库龄走势",
        {"status": "planned", "table_id": 54, "dims": ["事业部"], "dim_count": 2})
    add("syn-reg-total-sales", "regression", "近7天各平台的销售总额",
        {"status": "planned", "metrics": ["销售额"]})
    add("syn-reg-sales-count", "regression", "近7天各平台的销售数量",
        {"status": "planned", "metrics": ["销量"]})
    add("syn-reg-best-n", "regression", "近7天销售额最多的5个平台",
        {"status": "planned", "limit": 5, "order_desc": True})
    add("syn-reg-worst-n", "regression", "近7天销售额最少的3个平台",
        {"status": "planned", "limit": 3, "order_desc": False})
    add("syn-reg-generic-noun", "regression", "8月份各平台的数据，包含广告费、广告销售额、ACOS",
        {"status": "planned", "metrics": ["广告费", "广告销售额", "ACOS"]})
    add("syn-reg-category-gate", "regression", "查询8月份的综合数据情况，包括库存、广告、销售、退款数据",
        {"status": "clarify_required", "codes": ["metric_not_in_dataset"]})
    add("syn-reg-inventory-gate", "regression",
        "查询2026年8月1日至8月31日的综合数据，需要包含以下指标：库存数据（如库存数量、库存金额）、"
        "广告数据（如广告花费、广告销售额、ACOS）、销售数据（如销售额、订单量、销量）、"
        "退款数据（如退款金额、退款数量）。请按日期维度汇总展示。",
        {"status": "clarify_required", "codes": ["metric_not_in_dataset"]})
    add("syn-reg-colloquial-ad", "regression", "近7天各平台广告花了多少",
        {"status": "planned", "metrics": ["广告费"]})
    add("syn-reg-enum-alias-ok", "regression", "8月份各平台的数据，包括营业额、订单量、广告支出",
        {"status": "planned", "metrics": ["销售额", "销量", "广告费"]})
    # 枚举分页截断回归位：销售小组有 681 个授权值，默认页只取 500 个，
    # 落在首页之外的值会校验不过并被拆成部门+大组两个更宽的条件
    add("syn-reg-enum-paging", "regression", "2026年8月15日一部-B组各平台的销售额，取最高的前5个",
        {"status": "planned", "filter_expect": ("team_name", "=", "一部-B组"),
         "no_filter_on": "large_team_name"})
    # 多值组合回归位：单值抽取器只锁第一个值，剩下的会漏给销售小组做主段反查
    add("mv-reg-dept-and", "regression", "近7天项目二部和项目六部的销售额",
        {"status": "planned", "filter_expect": ("dept_name", "in", ["项目六部", "项目二部"]),
         "no_filter_on": "team_name"})
    add("mv-reg-dept-comma", "regression", "近7天九部、一部的销售额",
        {"status": "planned", "filter_expect": ("dept_name", "in", ["九部", "一部"]),
         "no_filter_on": "team_name"})
    add("mv-reg-dept-separately", "regression", "近7天项目二部和项目六部分别的销售额",
        {"status": "planned", "dims": ["部门"],
         "filter_expect": ("dept_name", "in", ["项目六部", "项目二部"])})
    add("mv-reg-plat-and", "regression", "近7天亚马逊和TEMU的销售额",
        {"status": "planned",
         "filter_expect": ("platform_name", "in", ["Amazon", "Amazon VC", "Temu"])})
    add("mv-reg-plat-separately", "regression", "近7天亚马逊和TEMU分别的销售额",
        {"status": "planned", "dims": ["平台"]})
    add("mv-reg-each", "regression", "近7天九部和一部各自卖了多少钱",
        {"status": "planned", "dims": ["部门"], "metrics": ["销售额"]})
    add("mv-reg-no-separately", "regression", "近7天九部和一部的销售额",
        {"status": "planned", "dim_count": 0})
    add("mv-reg-bigteam-yield", "regression", "近7天A组和B组分别的销售额",
        {"status": "planned", "dims": ["大组"],
         "filter_expect": ("large_team_name", "in", ["A组", "B组"])})
    add("mv-reg-team-multi-nodept", "regression", "近7天一部-A组和一部-B组的销售额",
        {"status": "planned", "filter_expect": ("team_name", "in", ["一部-A组", "一部-B组"]),
         "no_filter_on": "dept_name"})
    add("mv-reg-team-partial", "regression", "近7天二部-A组和一部-A组的销售额",
        {"status": "planned", "filter_expect": ("team_name", "=", "一部-A组"),
         "no_filter_on": "dept_name"})
    add("mv-reg-team-unknown", "regression", "近7天九部-Z组的销售额",
        {"status": "clarify_required", "codes": ["component_filter_value_unmatched"]})

    return cases


# ---------------------------------------------------------------- 断言
def _tpl(contract: dict) -> dict | None:
    er = contract.get("execution_ref") or {}
    return er.get("query_template")


def _filters(contract: dict) -> list[dict]:
    tpl = _tpl(contract) or {}
    return [f for f in (tpl.get("filters") or []) if isinstance(f, dict)]


def check(case: Case, contract: dict) -> list[str]:
    """把用例预期与规划合同逐项对照，返回失败描述列表。"""
    fails: list[str] = []
    exp = case.expect
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    status = contract.get("status")
    tpl = _tpl(contract)

    want_status = exp.get("status")
    if want_status and status != want_status:
        fails.append(f"status={status} 期望 {want_status}")

    if exp.get("table_id") and er.get("table_id") not in (None, exp["table_id"]):
        fails.append(f"table_id={er.get('table_id')} 期望 {exp['table_id']}")

    if exp.get("metrics"):
        got = [str(x) for x in (mv.get("metrics") or [])]
        for m in exp["metrics"]:
            if m not in got:
                fails.append(f"缺指标 {m}（实际 {got}）")

    if exp.get("dims"):
        got = [str(x) for x in (mv.get("dimensions") or [])]
        for d in exp["dims"]:
            if d not in got:
                fails.append(f"缺维度 {d}（实际 {got}）")

    if exp.get("time"):
        ts = er.get("time_scope") or {}
        got = (ts.get("start"), ts.get("end"))
        if got != tuple(exp["time"]):
            fails.append(f"时间窗口 {got} 期望 {tuple(exp['time'])}")

    if exp.get("codes"):
        got = list(mv.get("clarification_reason_codes") or [])
        for c in exp["codes"]:
            if c not in got:
                fails.append(f"缺澄清码 {c}（实际 {got}）")

    if exp.get("codes_any"):
        got = set(mv.get("clarification_reason_codes") or [])
        if not (got & set(exp["codes_any"])):
            fails.append(f"澄清码 {sorted(got)} 未命中任一 {exp['codes_any']}")

    if exp.get("limit") is not None and tpl is not None:
        if tpl.get("limit") != exp["limit"]:
            fails.append(f"limit={tpl.get('limit')} 期望 {exp['limit']}")

    if exp.get("limit_absent") and tpl is not None and tpl.get("limit") is not None:
        fails.append(f"不应有 limit，实际 {tpl.get('limit')}")

    if exp.get("order_desc") is not None and tpl is not None:
        ob = tpl.get("orderBy") or []
        if not ob:
            fails.append("缺 orderBy")
        elif bool(ob[0].get("desc")) != bool(exp["order_desc"]):
            fails.append(f"orderBy desc={ob[0].get('desc')} 期望 {exp['order_desc']}")

    if exp.get("order_absent") and tpl is not None:
        ob = tpl.get("orderBy") or []
        # 趋势场景规划器会主动按日期升序，不算违例
        if ob and not any("date" in str(o.get("field", "")).lower() for o in ob):
            fails.append(f"不应下发排序，实际 {ob}")

    if exp.get("trend") is True and tpl is not None:
        dims = [str(d.get("field")) for d in (tpl.get("dimensions") or [])]
        # 判据用合同自己声明的日期字段集合，避免把 create_time 这类合法日期列误判
        date_names = {str(f.get("field_name")) for f in (er.get("date_fields") or [])}
        if not (set(dims) & date_names):
            fails.append(f"趋势未补日期维度，实际 {dims}（可用日期字段 {sorted(date_names)}）")
    if exp.get("trend") is False and tpl is not None:
        dims = [str(d.get("field")) for d in (tpl.get("dimensions") or [])]
        if any("date" in d.lower() for d in dims):
            fails.append(f"否定语境仍补了日期维度 {dims}")

    if exp.get("comparison") and tpl is not None:
        if not tpl.get("dataComparison"):
            fails.append("环比缺 dataComparison")

    if exp.get("snapshot"):
        pol = er.get("snapshot_policy")
        if not pol:
            fails.append("快照指标未收敛 snapshot_policy")

    if exp.get("currency") and tpl is not None:
        if tpl.get("globalCurrency") != exp["currency"]:
            fails.append(f"globalCurrency={tpl.get('globalCurrency')} 期望 {exp['currency']}")

    if exp.get("multi_currency"):
        tpls = er.get("query_templates") or []
        got = [str(t.get("globalCurrency")) for t in tpls if isinstance(t, dict)]
        for c in exp["multi_currency"]:
            if c not in got:
                fails.append(f"多币种缺 {c}（实际 {got}）")

    if exp.get("platform_members"):
        got = [str(x) for x in (mv.get("platform_semantic_members") or [])]
        for m in exp["platform_members"]:
            if m not in got:
                fails.append(f"平台语义缺 {m}（实际 {got}）")

    if exp.get("no_filter_on"):
        bad = [f for f in _filters(contract) if str(f.get("field")) == exp["no_filter_on"]]
        if bad:
            fails.append(f"分组词被当筛选值 {bad}")

    if exp.get("exclude_expected") and tpl is not None:
        ops = {str(f.get("operator")) for f in _filters(contract)}
        if not ({"!=", "not_in"} & ops):
            fails.append(f"排除极性丢失，实际算子 {sorted(ops)}")

    if exp.get("alias_map"):
        maps = mv.get("field_alias_mappings_zh") or []
        if not any(str(m.get("requested")) == exp["alias_map"] for m in maps):
            fails.append(f"缺别名映射披露 {exp['alias_map']}（实际 {maps}）")

    if exp.get("component_query"):
        if status != "planned" or tpl is None:
            fails.append(f"组件枚举未下发模板（status={status}）")

    if exp.get("no_component_target"):
        if er.get("table_id") in (7, 8, 9, 10, 11, 19, 20, 35, 40):
            fails.append(f"业务表达被误判为组件枚举 table_id={er.get('table_id')}")

    if exp.get("metrics_all_or_clarify"):
        want = exp["metrics_all_or_clarify"]
        got = [str(x) for x in (mv.get("metrics") or [])]
        if status == "planned":
            missing = [m for m in want if m not in got]
            if missing:
                fails.append(f"planned 但指标不完整，缺 {missing}（实际 {got}）")

    if exp.get("order_unresolved"):
        dis = json.dumps(mv, ensure_ascii=False) + json.dumps(contract.get("answer_contract") or {}, ensure_ascii=False)
        if "order_unresolved" not in dis and "自然序" not in dis:
            fails.append("多指标未点名排序时缺 order_unresolved 披露")

    if exp.get("no_code"):
        got = list(mv.get("clarification_reason_codes") or [])
        if exp["no_code"] in got:
            fails.append(f"不应出现澄清码 {exp['no_code']}（实际 {got}）")

    if exp.get("dim_count") is not None:
        got = [str(x) for x in (mv.get("dimensions") or [])]
        if len(got) != exp["dim_count"]:
            fails.append(f"维度数 {len(got)} 期望 {exp['dim_count']}（{got}）")

    if exp.get("metric_count") is not None:
        got = [str(x) for x in (mv.get("metrics") or [])]
        if len(got) != exp["metric_count"]:
            fails.append(f"指标数 {len(got)} 期望 {exp['metric_count']}（{got}）")

    if exp.get("date_field") and tpl is not None:
        used = {
            str(f.get("field"))
            for f in _filters(contract)
            if str(f.get("operator")) in (">=", "<=", "between")
        }
        if used and exp["date_field"] not in used:
            fails.append(f"时间锚点 {sorted(used)} 期望 {exp['date_field']}")

    if exp.get("filter_expect") and tpl is not None:
        want_field, want_op, want_value = exp["filter_expect"]
        # in/not_in 的取值是列表，按集合语义比对（顺序无语义）
        def _same_value(actual: object) -> bool:
            if isinstance(actual, list) and isinstance(want_value, list):
                return sorted(map(str, actual)) == sorted(map(str, want_value))
            return actual == want_value

        hit = [
            f for f in _filters(contract)
            if str(f.get("field")) == want_field
            and str(f.get("operator")) == want_op
            and _same_value(f.get("value"))
        ]
        if not hit:
            fails.append(
                f"缺筛选 {want_field} {want_op} {want_value}"
                f"（实际 {[(f.get('field'), f.get('operator'), f.get('value')) for f in _filters(contract)]}）"
            )

    if exp.get("no_extra_metric"):
        got = [str(x) for x in (mv.get("metrics") or [])]
        if len(got) > 1:
            fails.append(f"完整标签内嵌别名被拆成多指标 {got}")

    return fails


# ---------------------------------------------------------------- 执行
def run_case(case: Case, email: str) -> Result:
    try:
        contract = run_plan(
            case.prompt, user_email=email, requested_fields=list(case.fields)
        )
    except Exception as exc:  # noqa: BLE001
        return Result(case=case, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}")
    fails = check(case, contract)
    return Result(
        case=case,
        status=str(contract.get("status")),
        ok=not fails,
        failures=fails,
        contract=contract,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="chenbenli@aukeys.com")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/planner-audit-20260909")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--suite", action="append", help="只跑指定 suite，可重复")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--tag", default="run")
    args = parser.parse_args()

    meta = load_meta(args.email)
    cases = build_dataset_cases(meta) + build_semantic_cases(meta)
    if args.suite:
        want = set(args.suite)
        cases = [c for c in cases if c.suite in want]
    if args.max_cases:
        cases = cases[: args.max_cases]

    print(f"数据集 {len(meta)}，用例 {len(cases)}")
    results: list[Result] = []
    with futures.ThreadPoolExecutor(args.workers) as pool:
        for res in pool.map(lambda c: run_case(c, args.email), cases):
            results.append(res)
            if not res.ok:
                mark = "ERR" if res.error else "FAIL"
                print(f"[{mark}] {res.case.case_id} | {res.case.prompt}")
                for f in (res.failures or [res.error])[:4]:
                    print(f"        - {f}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{args.tag}-results.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({
                "case_id": r.case.case_id, "suite": r.case.suite, "prompt": r.case.prompt,
                "expect": r.case.expect, "status": r.status, "ok": r.ok,
                "failures": r.failures, "error": r.error,
                "model_view": (r.contract or {}).get("model_view"),
                "execution_ref": (r.contract or {}).get("execution_ref"),
            }, ensure_ascii=False, default=str) + "\n")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    errored = sum(1 for r in results if r.error)
    by_suite = Counter(r.case.suite for r in results if not r.ok)
    print("\n==== 汇总 ====")
    print(f"总用例 {total}，通过 {passed}，失败 {total - passed}，异常 {errored}")
    for suite, n in by_suite.most_common():
        tot = sum(1 for r in results if r.case.suite == suite)
        print(f"  {suite}: 失败 {n}/{tot}")
    print(f"明细：{out}")


if __name__ == "__main__":
    main()
