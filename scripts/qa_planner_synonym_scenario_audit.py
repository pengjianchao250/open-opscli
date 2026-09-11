#!/usr/bin/env python3
"""近义词 / 同义词矩阵 + 专业运营场景矩阵 + 行为快照兼容校验。

三个部分：

1. **同义词矩阵**：同一业务口径的多种说法必须解析到同一个字段/同一份模板，
   或者安全澄清。覆盖指标、维度、时间、筛选、排序、对比、趋势、动作词八类。
2. **专业场景矩阵**：按真实运营场景组织的完整请求（周报、月度复盘、大促盘点、
   广告效率、库存健康、退款分析、人员绩效、物流成本、新品跟踪），逐条写死预期。
3. **行为快照**：`--snapshot` 把当前语料的规划结果落盘；`--compare` 用同一语料
   重跑并与快照逐条比对，任何非预期的行为变化都会被列出来。用于保证新一轮修复
   不影响既有规划器行为。

只调用内核入口 run_plan，不直连后端 HTTP（铁律11）。
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
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


def last_month() -> tuple[str, str]:
    first = today().replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1).isoformat(), end.isoformat()


# ---------------------------------------------------------------- 用例模型
@dataclass
class Case:
    case_id: str
    suite: str
    prompt: str
    group: str = ""
    persona: str = "all"
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


def _tpl(contract: dict) -> dict | None:
    return (contract.get("execution_ref") or {}).get("query_template")


# ---------------------------------------------------------------- 同义词矩阵
# 每组：期望落到的中文字段标签 → 该口径的各种说法。
# 说法能落到字段的必须落对；落不到的必须澄清，不得静默产出零指标模板。
METRIC_SYNONYMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "syn-sales": (
        "销售额",
        ("销售额", "销售金额", "营业额", "成交额", "收入", "GMV",
         "销售收入", "卖了多少钱", "销售总额"),
    ),
    "syn-qty": (
        "销量",
        ("销量", "销售量", "销售件数", "订单量", "单量", "出单量", "成交量",
         "卖了多少个", "多少单", "销售数量"),
    ),
    "syn-adcost": (
        "广告费",
        ("广告费", "广告花费", "广告支出", "广告成本", "投放费用", "广告投入"),
    ),
    "syn-profit": ("毛利", ("毛利", "毛利额", "毛利润")),
    "syn-purchase": ("采购成本", ("采购成本", "采购费用", "进货成本", "采购金额")),
    "syn-refund": ("退款金额", ("退款金额", "退款额", "退款总额")),
    "syn-click": ("点击量", ("点击量", "点击次数", "点击数")),
    "syn-impression": ("曝光量", ("曝光量", "曝光次数", "展现量")),
    # 2026-09-10：广告缩写 CTR 即点击率
    "syn-ctr": ("点击率", ("点击率", "CTR")),
}

# 维度近义说法：同一分组字段的多种叫法
DIM_SYNONYMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "syn-dim-platform": ("平台", ("各平台", "分平台", "按平台", "每个平台", "各个平台", "逐个平台")),
    "syn-dim-country": ("国家", ("各国家", "分国家", "按国家", "每个国家", "各个国家")),
    "syn-dim-dept": ("部门", ("各部门", "分部门", "按部门", "每个部门", "各事业部")),
    "syn-dim-team": ("销售小组", ("各销售小组", "按销售小组", "每个销售小组", "分销售小组")),
    "syn-dim-bigteam": ("大组", ("各大组", "按大组", "每个大组", "分大组")),
    "syn-dim-channel": ("渠道", ("各渠道", "分渠道", "按渠道", "每个渠道")),
    "syn-dim-brand": ("品牌", ("各品牌", "分品牌", "按品牌", "每个品牌")),
    "syn-dim-sku": ("公司SKU", ("各公司SKU", "按公司SKU", "每个公司SKU")),
    "syn-dim-category": ("品类", ("各品类", "按品类", "每个品类", "分品类")),
    "syn-dim-devteam": ("开发小组", ("各开发小组", "按开发小组", "每个开发小组")),
}

# 筛选说法：同一筛选值的多种引导方式
FILTER_SYNONYMS: dict[str, tuple[tuple[str, str, str], tuple[str, ...]]] = {
    "syn-filter-dept": (
        ("dept_name", "=", "九部"),
        ("九部的销售额", "只看九部的销售额", "仅看九部的销售额",
         "限定九部的销售额", "部门是九部的销售额", "部门为九部的销售额",
         "筛选九部的销售额"),
    ),
}

# 排除说法：同一排除诉求的多种引导方式
EXCLUDE_SYNONYMS: dict[str, tuple[tuple[str, str, str], tuple[str, ...]]] = {
    "syn-exclude-plat": (
        ("platform_name", "!=", "Amazon VC"),
        ("排除亚马逊VC", "剔除亚马逊VC", "去掉亚马逊VC", "不含亚马逊VC",
         "不要亚马逊VC", "亚马逊VC除外", "亚马逊VC以外",
         # 2026-09-10 同义词复测补齐：以下说法原先被读成"只看 VC"
         "扣除亚马逊VC", "刨除亚马逊VC", "排掉亚马逊VC", "拿掉亚马逊VC", "不算亚马逊VC",
         "除去亚马逊VC", "抛开亚马逊VC", "除了亚马逊VC", "除亚马逊VC外",
         "不包括亚马逊VC在内"),
    ),
    # 组件字段同一批排除说法：原先同样被反转成包含条件
    "syn-exclude-dept": (
        ("dept_name", "!=", "九部"),
        ("排除九部", "扣除九部", "刨除九部", "不算九部", "除去九部", "除了九部",
         "九部除外", "九部以外", "不包括九部在内"),
    ),
    # 品类不开原文反查：裸值排除原先被静默丢弃，字段后接排除词也抽不到值
    "syn-exclude-cat": (
        ("category", "!=", "家居类"),
        ("剔除家居类", "扣除家居类", "除了家居类", "家居类除外", "品类排除家居类",
         "品类不看家居类"),
    ),
    # 复合值：字段后接排除词时原先被连同排除词一起吞成「排除一部-B组」
    "syn-exclude-team": (
        ("team_name", "!=", "一部-B组"),
        ("排除一部-B组", "销售小组排除一部-B组", "扣除一部-B组", "除了一部-B组"),
    ),
}

# 时间近义说法：同一窗口的多种叫法
TIME_SYNONYMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "syn-t-7d": (last_n(7), ("近7天", "最近7天", "过去7天", "近七天", "近7日", "最近一周内")),
    "syn-t-30d": (last_n(30), ("近30天", "最近30天", "过去30天", "近三十天")),
    "syn-t-lastmonth": (last_month(), ("上月", "上个月", "上一个月")),
    "syn-t-yesterday": (
        ((today() - timedelta(days=1)).isoformat(),) * 2,
        ("昨天", "昨日"),
    ),
    "syn-t-daybefore": (
        ((today() - timedelta(days=2)).isoformat(),) * 2,
        ("前天", "前日"),
    ),
    "syn-t-thisweek": (
        (
            (today() - timedelta(days=today().weekday())).isoformat(),
            today().isoformat(),
        ),
        ("本周", "这周", "WTD", "本周至今"),
    ),
    "syn-t-ytd": (
        (today().replace(month=1, day=1).isoformat(), today().isoformat()),
        ("今年以来", "今年", "本年", "年初至今", "YTD"),
    ),
    # 2026-09-10 专业时间口径补齐：以下说法原先整句退回默认近 30 天
    "syn-t-mtd": (
        (today().replace(day=1).isoformat(), today().isoformat()),
        ("MTD", "月初至今", "本月至今"),
    ),
    "syn-t-qtd": (
        (
            today().replace(month=(today().month - 1) // 3 * 3 + 1, day=1).isoformat(),
            today().isoformat(),
        ),
        ("本季度", "QTD", "本季度至今", "季初至今"),
    ),
    "syn-t-h1": (
        (today().replace(month=1, day=1).isoformat(), today().replace(month=6, day=30).isoformat()),
        ("上半年", "今年上半年"),
    ),
    "syn-t-halfyear": (
        ((today() - timedelta(days=179)).isoformat(), today().isoformat()),
        ("近半年", "最近半年", "过去半年"),
    ),
}

# 排序 / 行数近义说法
ORDER_SYNONYMS: dict[str, tuple[dict[str, Any], tuple[str, ...]]] = {
    "syn-top-desc": (
        {"limit": 5, "order_desc": True},
        ("销售额最高的前5个平台", "销售额排名前5的平台", "销售额排前5的平台",
         "销售额top5的平台", "哪5个平台销售额最高", "销售额最多的5个平台"),
    ),
    "syn-top-asc": (
        {"limit": 3, "order_desc": False},
        ("销售额最低的前3个平台", "销售额最少的3个平台", "销售额倒数前3的平台"),
    ),
}

# 对比近义说法
COMPARE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "syn-mom": ("环比上一周期", "环比", "跟上个周期比", "与上一周期对比", "较上期"),
    "syn-yoy": ("同比去年同期", "同比", "跟去年同期比", "与去年同期对比"),
}

# 趋势近义说法
TREND_SYNONYMS: tuple[str, ...] = ("按日趋势", "每天的走势", "日趋势", "按天看", "每天分开看", "逐日走势")

# 动作词：不改变语义的礼貌/动词前缀
ACTION_PREFIXES: tuple[str, ...] = (
    "", "帮我看下", "麻烦查一下", "请统计", "我想看", "拉一下", "汇总一下",
    "给我出一下", "能不能帮我查", "看看",
)


def build_synonym_cases() -> list[Case]:
    cases: list[Case] = []
    for group, (label, terms) in METRIC_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_metric",
                              f"近7天各平台的{term}", group, "all",
                              {"expected_label": label, "term": term}))
    for group, (label, terms) in DIM_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_dim",
                              f"近7天{term}的销售额", group, "all",
                              {"expected_dim": label, "term": term}))
    for group, (window, terms) in TIME_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_time",
                              f"{term}各平台的销售额", group, "all",
                              {"expected_window": window, "term": term}))
    for group, (expect, terms) in ORDER_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_order",
                              f"近7天{term}", group, "all", dict(expect, term=term)))
    for group, terms in COMPARE_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_compare",
                              f"近7天各平台的销售额，{term}", group, "all",
                              {"comparison": True, "window": last_n(7), "term": term}))
    for index, term in enumerate(TREND_SYNONYMS):
        cases.append(Case(f"syn-trend-{index}", "synonym_trend",
                          f"近7天各平台的销售额，{term}", "syn-trend", "all",
                          {"trend": True, "term": term}))
    for group, (want, terms) in FILTER_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_filter",
                              f"近7天{term}", group, "all",
                              {"expected_filter": want, "term": term}))
    for group, (want, terms) in EXCLUDE_SYNONYMS.items():
        for index, term in enumerate(terms):
            cases.append(Case(f"{group}-{index}", "synonym_exclude",
                              f"近7天各平台的销售额，{term}", group, "all",
                              {"expected_filter": want, "term": term}))
    for index, prefix in enumerate(ACTION_PREFIXES):
        cases.append(Case(f"syn-action-{index}", "synonym_action",
                          f"{prefix}近7天各平台的销售额", "syn-action", "all",
                          {"template_same_as_group": True, "term": prefix or "(无前缀)"}))
    return cases


# ---------------------------------------------------------------- 专业场景矩阵
def build_scenario_cases() -> list[Case]:
    """按真实运营场景组织的完整请求，逐条写死预期。"""
    s7, e7 = last_n(7)
    slm, elm = last_month()
    specs: list[tuple[str, str, str, dict[str, Any]]] = [
        # ---- 专业运营给领导汇报 ----
        ("sc-weekly", "leadership",
         "近7天各平台的销售额和销量，按销售额降序取前10",
         {"metrics": ["销售额", "销量"], "dims": ["平台"], "window": (s7, e7),
          "limit": 10, "order_desc": True}),
        ("sc-monthly-review", "leadership",
         "上个月各部门的销售额，环比上一周期",
         {"metrics": ["销售额"], "dims": ["部门"], "window": (slm, elm),
          "comparison": True}),
        ("sc-yoy-review", "leadership",
         "上个月各平台的销售额，同比去年同期",
         {"metrics": ["销售额"], "dims": ["平台"], "window": (slm, elm),
          "comparison": True}),
        ("sc-quarter-board", "leadership",
         f"今年第一季度各大组的销售额，用美元口径",
         {"metrics": ["销售额"], "dims": ["大组"], "currency": "USD"}),
        ("sc-daily-trend", "leadership",
         "近7天销售额的按日趋势",
         {"metrics": ["销售额"], "window": (s7, e7), "trend": True}),
        ("sc-ad-efficiency", "leadership",
         "近7天各平台的广告费和销售额，按广告费降序取前5",
         {"metrics": ["广告费", "销售额"], "dims": ["平台"], "limit": 5,
          "order_desc": True}),
        ("sc-refund", "leadership",
         "上个月各平台的退款金额，按退款金额降序取前5",
         {"dims": ["平台"], "window": (slm, elm), "limit": 5, "order_desc": True}),
        ("sc-dual-currency", "leadership",
         "近7天各平台的销售额，分别用人民币和加拿大元展示",
         {"metrics": ["销售额"], "dims": ["平台"], "multi_currency": ["CNY", "CAD"]}),
        ("sc-dept-filtered", "leadership",
         "近7天九部各销售小组的销售额，按销售额降序取前10",
         {"dims": ["销售小组"], "filters": [("dept_name", "=", "九部")],
          "limit": 10, "order_desc": True}),
        ("sc-exclude-vc", "leadership",
         "近7天各平台的销售额，排除亚马逊VC",
         {"metrics": ["销售额"], "dims": ["平台"],
          "filters": [("platform_name", "!=", "Amazon VC")]}),
        # ---- 专业测试视角：口径与边界 ----
        ("sc-inventory-snapshot", "test",
         "库存周转数据集近7天各部门的总库存",
         {"dims": ["部门"], "metrics": ["总库存"], "snapshot": True}),
        ("sc-inventory-mixed", "test",
         "即时综合数据集近7天各平台的总库存和销售额",
         {"status": "clarify_required", "codes": ["snapshot_metric_window_conflict"]}),
        ("sc-margin-rate", "test",
         "近7天各平台的毛利率",
         {"metrics": ["毛利率"], "dims": ["平台"]}),
        ("sc-ad-share", "test",
         "广告费数据集本月各平台的SP广告占比",
         {"metrics": ["SP广告占比"], "dims": ["平台"]}),
        ("sc-composite-team", "test",
         "近7天一部-B组各平台的销售额",
         {"dims": ["平台"], "filters": [("team_name", "=", "一部-B组")],
          "no_filter_field": "large_team_name"}),
        ("sc-enum-channel", "test", "有哪些渠道可选", {"component_table": True}),
        ("sc-enum-dept", "test", "列出当前可见的部门", {"component_table": True}),
        ("sc-unsupported-currency", "test",
         "近7天各平台的销售额，用港币口径",
         {"status": "clarify_required", "codes": ["unsupported_currency"]}),
        ("sc-unknown-metric", "test",
         "近7天各平台的净推荐值",
         {"status": "clarify_required", "codes": ["metric_not_in_dataset"]}),
        ("sc-unknown-dim", "test",
         "近7天各仓库的销售额",
         {"status": "clarify_required", "codes": ["dimension_not_in_dataset"]}),
        # ---- 菜鸟运营视角：口语与省略 ----
        ("sc-novice-money", "novice", "近7天各平台卖了多少钱",
         {"metrics": ["销售额"], "dims": ["平台"]}),
        ("sc-novice-qty", "novice", "上个月每个大组卖了多少个",
         {"metrics": ["销量"], "dims": ["大组"], "window": (slm, elm)}),
        ("sc-novice-top", "novice", "近7天哪5个平台卖得钱最多",
         {"dims": ["平台"]}),
        ("sc-novice-yesterday", "novice", "昨天各渠道的销售额",
         {"dims": ["渠道"], "metrics": ["销售额"]}),
        ("sc-novice-daybefore", "novice", "前天各平台卖了多少钱",
         {"metrics": ["销售额"], "dims": ["平台"],
          "window": ((today() - timedelta(days=2)).isoformat(),) * 2}),
        ("sc-novice-split", "novice", "近7天分平台看销售额",
         {"metrics": ["销售额"], "dims": ["平台"]}),
        ("sc-novice-compare", "novice", "近7天各平台的销售额跟上个周期比怎么样",
         {"metrics": ["销售额"], "dims": ["平台"], "comparison": True}),
        ("sc-novice-trend", "novice", "近7天每天的销售额是多少",
         {"metrics": ["销售额"], "trend": True}),
        ("sc-novice-which", "novice", "近7天销售额排前5的平台是哪些",
         {"dims": ["平台"], "limit": 5}),
        ("sc-novice-polite", "novice", "麻烦帮我拉一下近7天各平台的销售额，谢谢",
         {"metrics": ["销售额"], "dims": ["平台"]}),
    ]
    return [
        Case(case_id=case_id, suite="scenario", prompt=prompt, persona=persona,
             expect=expect)
        for case_id, persona, prompt, expect in specs
    ]


def build_composite_report_cases() -> list[Case]:
    """多类目综合报表矩阵（举一反三）。

    真实形态：给领导出一张"综合数据"报表，用并列列举点名若干类目。
    判据只有一条——**被点名的类目要么真的落到字段，要么必须澄清**，
    不允许某一类静默消失。库存类在即时综合数据集里没有对应口径（只有
    平台库存/国内库存等具体口径），因此点名"库存/库存数量/库存金额"时应澄清；
    换到库存周转数据集则应能落上。
    """
    specs: list[tuple[str, str, str, dict[str, Any]]] = [
        # 全部类目都能落上 → 必须 planned
        # 只给类目词、不给具体口径时，数据集里有多个「广告*」字段，规划器不猜、
        # 转澄清并给候选，这是既定的安全行为
        ("cp-ad-sales-refund", "leadership",
         "8月份的综合数据，包括广告、销售、退款数据，按日期汇总",
         {"status": "clarify_required", "codes": ["metric_not_in_dataset"],
          "unknown_contains": ["广告", "销售", "退款"]}),
        ("cp-sales-only", "leadership",
         "8月份的数据，包括销售额、销量、广告费、退款金额",
         {"status": "planned",
          "metrics": ["销售额", "销量", "广告费", "退款金额"]}),
        ("cp-ad-detail", "leadership",
         "8月份各平台的数据，包含广告费、广告销售额、ACOS",
         {"status": "planned", "metrics": ["广告费", "广告销售额", "ACOS"]}),
        # 含落不上的类目 → 必须澄清并点名是哪一类
        ("cp-with-inventory", "leadership",
         "查询8月份的综合数据情况，包括库存、广告、销售、退款数据",
         {"status": "clarify_required", "codes": ["metric_not_in_dataset"],
          "unknown_contains": ["库存"]}),
        ("cp-inventory-detail", "leadership",
         "查询2026年8月1日至8月31日的综合数据，需要包含以下指标："
         "库存数据（如库存数量、库存金额）、广告数据（如广告花费、广告销售额、ACOS）、"
         "销售数据（如销售额、订单量、销量）、退款数据（如退款金额、退款数量）。"
         "请按日期维度汇总展示。",
          {"status": "clarify_required", "codes": ["metric_not_in_dataset"],
           "unknown_contains": ["库存数量", "库存金额"]}),
        ("cp-unknown-category", "test",
         "8月份的综合数据，包括销售、物流时效、退款数据",
         {"status": "clarify_required", "codes": ["metric_not_in_dataset"],
          "unknown_contains": ["物流时效"]}),
        ("cp-nps", "test",
         "8月份各平台的数据，包括销售额、净推荐值",
         {"status": "clarify_required", "codes": ["metric_not_in_dataset"],
          "unknown_contains": ["净推荐值"]}),
        # 换到确有该口径的数据集 → 必须能落上
        ("cp-inventory-dataset", "leadership",
         "库存周转数据集8月份各部门的数据，包括总库存",
         {"status": "planned", "metrics": ["总库存"]}),
        # 口语版综合报表
        ("cp-novice", "novice",
         "8月份的数据帮我看下，包括卖了多少钱、卖了多少个、广告花了多少",
         {"status": "planned"}),
        # 已覆盖类目 + 别名混写，不得误报
        ("cp-alias-mix", "leadership",
         "8月份各平台的数据，包括营业额、订单量、广告支出",
         {"status": "planned", "metrics": ["销售额", "销量", "广告费"]}),
    ]
    return [
        Case(case_id=case_id, suite="composite_report", prompt=prompt,
             persona=persona, expect=expect)
        for case_id, persona, prompt, expect in specs
    ]


def build_multi_value_cases() -> list[Case]:
    """多值组合矩阵（举一反三）。

    「项目二部和项目六部」「亚马逊和TEMU」这类并列点名多个筛选值的请求，判据两条：
    1. 列举里的**每一个值**都要落到同一个字段的 in 列表，不得只锁第一个、
       剩下的漏给别的组件做主段反查；
    2. 原文出现「分别/各自/分开」时必须按该字段分组逐值展示，不得只给一个合计。
    """
    specs: list[tuple[str, str, str, dict[str, Any]]] = [
        # 部门多值：不同连接词
        ("mv-dept-and", "leadership", "近7天项目二部和项目六部的销售额",
         {"status": "planned",
          "filters": [("dept_name", "in", ["项目六部", "项目二部"])]}),
        ("mv-dept-comma", "leadership", "近7天项目二部、项目六部的销售额",
         {"status": "planned",
          "filters": [("dept_name", "in", ["项目六部", "项目二部"])]}),
        ("mv-dept-yu", "leadership", "近7天九部与一部的销售额",
         {"status": "planned", "filters": [("dept_name", "in", ["九部", "一部"])]}),
        ("mv-dept-labeled", "leadership", "近7天部门是九部和一部的销售额",
         {"status": "planned", "filters": [("dept_name", "in", ["九部", "一部"])]}),
        ("mv-dept-three", "leadership", "近7天九部、一部和七部的销售额",
         {"status": "planned",
          "filters": [("dept_name", "in", ["九部", "一部", "七部"])]}),
        # 平台多值：亚马逊要展开成 SC+VC
        ("mv-plat-and", "leadership", "近7天亚马逊和TEMU的销售额",
         {"status": "planned",
          "filters": [("platform_name", "in", ["Amazon", "Amazon VC", "Temu"])]}),
        ("mv-plat-sc", "leadership", "近7天亚马逊SC和TikTok的销售额",
         {"status": "planned",
          "filters": [("platform_name", "in", ["Amazon", "Tiktok"])]}),
        # 「分别」必须补分组维度
        ("mv-dept-separately", "leadership", "近7天项目二部和项目六部分别的销售额",
         {"status": "planned", "dims": ["部门"],
          "filters": [("dept_name", "in", ["项目六部", "项目二部"])]}),
        ("mv-dept-separately2", "leadership", "近7天项目二部和项目六部分别的销售情况",
         {"status": "planned", "dims": ["部门"]}),
        ("mv-plat-separately", "leadership", "近7天亚马逊和TEMU分别的销售额",
         {"status": "planned", "dims": ["平台"],
          "filters": [("platform_name", "in", ["Amazon", "Amazon VC", "Temu"])]}),
        ("mv-dept-each", "novice", "近7天九部和一部各自卖了多少钱",
         {"status": "planned", "dims": ["部门"], "metrics": ["销售额"]}),
        ("mv-plat-split", "novice", "近7天亚马逊和TikTok分开看销售额",
         {"status": "planned", "dims": ["平台"]}),
        # 无「分别」时保持合计，不擅自补维度
        ("mv-dept-total", "test", "近7天九部和一部的销售额",
         {"status": "planned", "dim_absent": ["部门"]}),
        # 多值 + TopN / 环比 / 币种 叠加
        ("mv-with-topn", "leadership",
         "近7天项目二部和项目六部分别的销售额，取最高的前5个",
         {"status": "planned", "dims": ["部门"], "limit": 5, "order_desc": True}),
        ("mv-with-mom", "leadership",
         "上个月九部和一部分别的销售额，环比上一周期",
         {"status": "planned", "dims": ["部门"], "comparison": True}),
        ("mv-with-currency", "leadership",
         "近7天亚马逊和TEMU分别的销售额，用美元口径",
         {"status": "planned", "dims": ["平台"], "currency": "USD"}),
        # 多值排除
        ("mv-exclude-two", "leadership", "近7天各渠道销售额，排除TikTok和Temu",
         {"status": "planned",
          "filters": [("platform_name", "not_in", ["Temu", "Tiktok"])]}),
        # ---- 举一反三：其他组件字段的多值 ----
        ("mv-country-and", "leadership", "近7天美国和加拿大的销售额",
         {"status": "planned", "filters": [("country_name", "in", ["美国", "加拿大"])]}),
        ("mv-country-separately", "leadership", "近7天美国和加拿大分别的销售额",
         {"status": "planned", "dims": ["国家"]}),
        ("mv-country-exclude", "leadership", "近7天各平台的销售额，排除美国和加拿大",
         {"status": "planned", "filters": [("country_name", "not_in", ["美国", "加拿大"])]}),
        ("mv-team-and", "leadership", "近7天一部-A组和一部-B组的销售额",
         {"status": "planned", "filters": [("team_name", "in", ["一部-A组", "一部-B组"])],
          "no_filter_field": "dept_name"}),
        ("mv-team-separately", "leadership", "近7天一部-A组和一部-B组分别的销售额",
         {"status": "planned", "dims": ["销售小组"]}),
        ("mv-bigteam-separately", "leadership", "近7天A组和B组分别的销售额",
         {"status": "planned", "dims": ["大组"],
          "filters": [("large_team_name", "in", ["A组", "B组"])]}),
        # 列举里有一个值未授权：按授权交集查询，未纳入的值不得以片段形式混进别的字段
        ("mv-team-partial", "test", "近7天一部-A组和二部-A组的销售额",
         {"status": "planned", "filters": [("team_name", "=", "一部-A组")],
          "no_filter_field": "dept_name"}),
        ("mv-team-partial-rev", "test", "近7天二部-A组和一部-A组的销售额",
         {"status": "planned", "filters": [("team_name", "=", "一部-A组")],
          "no_filter_field": "dept_name"}),
        # 单独一个未授权复合值：必须澄清，不得拆成部门筛选
        ("mv-team-unknown", "test", "近7天九部-Z组的销售额",
         {"status": "clarify_required", "codes": ["component_filter_value_unmatched"]}),
        # 多值 + 趋势
        ("mv-dept-trend", "leadership", "近7天项目二部和项目六部分别的销售情况，按日趋势",
         {"status": "planned", "dims": ["部门"], "trend": True}),
        # ---- 2026-09-10 同义词复测：分句点名、正向限定截断、未授权值 ----
        # 分句点名的两个部门都要保留，并各自按所在语段判定极性
        ("mv-dept-cross-clause", "test", "近7天排除九部，只看十一部的销售额",
         {"status": "planned",
          "filters": [("dept_name", "=", "十一部"), ("dept_name", "!=", "九部")]}),
        # 正向点名的部门未授权：不能只剩「排除九部」把范围放大
        ("mv-dept-unauth-include", "test", "近7天排除九部，只看十部的销售额",
         {"status": "clarify_required", "codes": ["component_filter_unauthorized"]}),
        # 列举里一个部门未授权：按授权交集查询（并披露未纳入）
        ("mv-dept-partial", "test", "近7天九部和十部的销售额",
         {"status": "planned", "filters": [("dept_name", "=", "九部")]}),
        # 不带标点的「排除A只看B」：B 仍按包含处理
        ("mv-country-restrict", "novice", "近7天排除美国只看加拿大的销售额",
         {"status": "planned",
          "filters": [("country_name", "=", "加拿大"), ("country_name", "!=", "美国")]}),
        # 品类裸值多值排除
        ("mv-cat-exclude-two", "leadership", "近7天各品类销售额，剔除家居和户外",
         {"status": "planned", "filters": [("category", "not_in", ["家居", "户外"])]}),
        # 「包括X在内」范围不变
        ("mv-inclusive", "novice", "近7天包括九部在内的各部门销售额",
         {"status": "planned", "no_filter_field": "dept_name"}),
    ]
    return [
        Case(case_id=case_id, suite="multi_value", prompt=prompt,
             persona=persona, expect=expect)
        for case_id, persona, prompt, expect in specs
    ]


# ---------------------------------------------------------------- 断言
LEGIT_CLARIFY = {
    "snapshot_metric_window_conflict", "time_scope_confirmation",
    "recommended_fields_confirmation", "unsupported_currency",
    "metric_not_in_dataset", "dimension_not_in_dataset", "field_identity",
    "dataset_selection", "dataset_constraints", "business_dataset",
    "component_filter_value_unmatched", "component_filter_unauthorized",
    "component_filter_polarity_conflict", "time_comparison_unsupported",
}
COMPONENT_TABLE_IDS = {7, 8, 9, 10, 11, 19, 20, 35, 40}


def check_synonym(case: Case, contract: dict) -> list[str]:
    """同义说法必须落对字段；落不到时只能安全澄清，不得静默产出零指标模板。"""
    fails: list[str] = []
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    status = contract.get("status")
    template = _tpl(contract)
    term = case.expect.get("term")

    if status == "blocked":
        fails.append(f"blocked：{mv.get('block_reason_zh')}")
        return fails
    if status == "clarify_required":
        codes = set(mv.get("clarification_reason_codes") or [])
        if not (codes & LEGIT_CLARIFY):
            fails.append(f"澄清原因不在允许清单：{sorted(codes)}")
        return fails

    if case.suite == "synonym_metric":
        metrics = [str(x) for x in (mv.get("metrics") or [])]
        if not metrics:
            fails.append(f"说法「{term}」被静默丢弃，模板零指标")
        elif case.expect["expected_label"] not in metrics:
            fails.append(f"说法「{term}」落到 {metrics}，期望含 {case.expect['expected_label']}")
    elif case.suite == "synonym_dim":
        dims = [str(x) for x in (mv.get("dimensions") or [])]
        if case.expect["expected_dim"] not in dims:
            fails.append(f"说法「{term}」的分组维度 {dims}，期望含 {case.expect['expected_dim']}")
    elif case.suite == "synonym_time":
        scope = er.get("time_scope") or {}
        got = (scope.get("start"), scope.get("end"))
        if got != tuple(case.expect["expected_window"]):
            fails.append(f"说法「{term}」窗口 {got} 期望 {tuple(case.expect['expected_window'])}")
    elif case.suite == "synonym_order" and template is not None:
        if template.get("limit") != case.expect["limit"]:
            fails.append(f"说法「{term}」limit={template.get('limit')} 期望 {case.expect['limit']}")
        order_by = template.get("orderBy") or []
        metric_orders = [o for o in order_by if "date" not in str(o.get("field", "")).lower()]
        if not metric_orders:
            fails.append(f"说法「{term}」缺按指标排序")
        elif bool(metric_orders[0].get("desc")) != bool(case.expect["order_desc"]):
            fails.append(
                f"说法「{term}」排序方向 {metric_orders[0].get('desc')} 期望 {case.expect['order_desc']}"
            )
    elif case.suite == "synonym_compare" and template is not None:
        if not template.get("dataComparison"):
            fails.append(f"说法「{term}」缺 dataComparison")
        scope = er.get("time_scope") or {}
        got = (scope.get("start"), scope.get("end"))
        if got != tuple(case.expect["window"]):
            fails.append(f"说法「{term}」主周期 {got} 期望 {tuple(case.expect['window'])}")
    elif case.suite in ("synonym_filter", "synonym_exclude") and template is not None:
        want = tuple(case.expect["expected_filter"])
        actual = [
            (f.get("field"), f.get("operator"), f.get("value"))
            for f in (template.get("filters") or [])
            if isinstance(f, dict)
        ]
        if want not in {tuple(item) for item in actual}:
            fails.append(f"说法「{term}」缺筛选 {want}（实际 {actual}）")
    elif case.suite == "synonym_trend" and template is not None:
        dims = [str(d.get("field")) for d in (template.get("dimensions") or [])]
        date_names = {str(f.get("field_name")) for f in (er.get("date_fields") or [])}
        if not (set(dims) & date_names):
            fails.append(f"说法「{term}」未补日期维度（实际 {dims}）")
    return fails


def check_scenario(case: Case, contract: dict) -> list[str]:
    fails: list[str] = []
    exp = case.expect
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    status = contract.get("status")
    template = _tpl(contract)

    want_status = exp.get("status")
    if want_status and want_status != "planned":
        if status != want_status:
            fails.append(f"status={status} 期望 {want_status}")
        for code in exp.get("codes") or []:
            if code not in (mv.get("clarification_reason_codes") or []):
                fails.append(f"缺澄清码 {code}（实际 {mv.get('clarification_reason_codes')}）")
        unknown = [str(x) for x in (mv.get("unknown_requested_fields") or [])]
        for term in exp.get("unknown_contains") or []:
            if term not in unknown:
                fails.append(f"未点名落空口径 {term}（实际 {unknown}）")
        return fails

    if status != "planned":
        fails.append(
            f"status={status} codes={mv.get('clarification_reason_codes')} "
            f"msg={json.dumps(mv.get('clarification_messages_zh'), ensure_ascii=False)[:120]}"
        )
        return fails

    if exp.get("component_table"):
        if er.get("table_id") not in COMPONENT_TABLE_IDS:
            fails.append(f"枚举请求未落到组件表（table_id={er.get('table_id')}）")
        return fails

    got_metrics = [str(x) for x in (mv.get("metrics") or [])]
    for label in exp.get("metrics") or []:
        if label not in got_metrics:
            fails.append(f"缺指标 {label}（实际 {got_metrics}）")
    got_dims = [str(x) for x in (mv.get("dimensions") or [])]
    for label in exp.get("dims") or []:
        if label not in got_dims:
            fails.append(f"缺维度 {label}（实际 {got_dims}）")
    for label in exp.get("dim_absent") or []:
        if label in got_dims:
            fails.append(f"不应出现维度 {label}（实际 {got_dims}）")

    if exp.get("window"):
        scope = er.get("time_scope") or {}
        got = (scope.get("start"), scope.get("end"))
        if got != tuple(exp["window"]) and not er.get("snapshot_policy"):
            fails.append(f"时间窗 {got} 期望 {tuple(exp['window'])}")

    if template is not None:
        template_filters = [f for f in (template.get("filters") or []) if isinstance(f, dict)]
        actual = [(f.get("field"), f.get("operator"), f.get("value")) for f in template_filters]
        for want in exp.get("filters") or []:
            want_field, want_op, want_value = want
            # in/not_in 的取值是列表，不能进集合；逐条比对，列表按集合语义匹配
            hit = any(
                str(field) == want_field
                and str(op) == want_op
                and (
                    sorted(map(str, value)) == sorted(map(str, want_value))
                    if isinstance(value, list) and isinstance(want_value, list)
                    else value == want_value
                )
                for field, op, value in actual
            )
            if not hit:
                fails.append(f"缺筛选 {want}（实际 {actual}）")
        if exp.get("no_filter_field"):
            bad = [f for f in template_filters if str(f.get("field")) == exp["no_filter_field"]]
            if bad:
                fails.append(f"不应出现 {exp['no_filter_field']} 筛选（实际 {actual}）")
        if exp.get("limit") is not None and template.get("limit") != exp["limit"]:
            fails.append(f"limit={template.get('limit')} 期望 {exp['limit']}")
        if exp.get("order_desc") is not None:
            order_by = template.get("orderBy") or []
            metric_orders = [
                o for o in order_by if "date" not in str(o.get("field", "")).lower()
            ]
            if not metric_orders:
                fails.append(f"缺按指标排序（实际 {order_by}）")
            elif bool(metric_orders[0].get("desc")) != bool(exp["order_desc"]):
                fails.append(f"排序方向 {metric_orders[0].get('desc')} 期望 {exp['order_desc']}")
        if exp.get("comparison") and not template.get("dataComparison"):
            fails.append("缺 dataComparison")
        if exp.get("currency") and template.get("globalCurrency") != exp["currency"]:
            fails.append(f"globalCurrency={template.get('globalCurrency')} 期望 {exp['currency']}")
        if exp.get("trend"):
            dims = [str(d.get("field")) for d in (template.get("dimensions") or [])]
            date_names = {str(f.get("field_name")) for f in (er.get("date_fields") or [])}
            if not (set(dims) & date_names):
                fails.append(f"趋势未补日期维度（实际 {dims}）")
    if exp.get("multi_currency"):
        templates = er.get("query_templates") or []
        got = [str(x.get("globalCurrency")) for x in templates if isinstance(x, dict)]
        for code in exp["multi_currency"]:
            if code not in got:
                fails.append(f"多币种缺 {code}（实际 {got}）")
    if exp.get("snapshot") and not er.get("snapshot_policy"):
        fails.append("快照指标未收敛 snapshot_policy")
    return fails


def check_group_consistency(results: list[Result]) -> list[dict]:
    """同义词组内模板必须一致（clarify 的成员单独列出，不参与一致性比对）。"""
    findings: list[dict] = []
    groups: dict[str, list[Result]] = defaultdict(list)
    for res in results:
        if res.case.group and res.case.suite.startswith("synonym"):
            groups[res.case.group].append(res)
    for group, items in sorted(groups.items()):
        planned = [item for item in items if item.status == "planned"]
        signatures = {
            item.case.case_id: json.dumps(_tpl(item.contract or {}), ensure_ascii=False, sort_keys=True)
            for item in planned
        }
        if len(set(signatures.values())) > 1:
            findings.append({
                "group": group,
                "detail": {
                    item.case.case_id: {
                        "prompt": item.case.prompt,
                        "template": signatures[item.case.case_id][:260],
                    }
                    for item in planned
                },
            })
    return findings


# ---------------------------------------------------------------- 兼容语料
def compatibility_corpus() -> list[str]:
    """行为快照语料：覆盖既有规划器已支持的主要形态。

    从既有各矩阵里挑出有代表性的请求，用于证明新一轮修复没有改变既有行为。
    """
    return [
        "近7天各平台的销售额",
        "近7天各平台的销售额和销量",
        "本月各部门的销售额",
        "上月各销售小组的销售额",
        "近30天各渠道的广告费",
        "近7天各大组的销售额",
        "近7天各国家的销量",
        "近7天各品牌的销售额",
        "近7天销售额最高的前5个平台",
        "近7天销售额最低的前3个平台",
        "近7天各平台的销售额，按日趋势",
        "近7天每天的销售额",
        "本月各平台的销售额，环比上一周期",
        "上个月各平台的销售额，同比去年同期",
        "近7天各平台的销售额，用美元口径",
        "近7天各平台的销售额，分别用人民币和加拿大元展示",
        "近7天九部的销售额",
        "近7天项目九部的销售额",
        "近7天一部-B组的销售额",
        "近7天各销售小组的销售额，排除一部-B组",
        "近7天各平台销售额，排除亚马逊VC",
        "近7天各渠道销售额，排除TikTok和Temu",
        "近7天亚马逊的销售额",
        "近7天亚马逊SC的销售额",
        "近7天TikTok的销售额",
        "有哪些渠道可选",
        "列出当前可见的部门",
        "列出当前可见的销售小组",
        "今年第一季度各平台的销售额",
        "2026年8月15日各平台的销售额",
        "前天各平台的销售额",
        "近７天各平台的销售额",
        "近7天各平台卖了多少钱",
        "近7天各平台的销售量",
        "近7天各销售的销售额",
        "近7天各平台的营业额",
        "近7天各平台的GMV",
        "近7天各平台的广告支出",
        "即时综合数据集近7天各平台的平台库存",
        "库存周转数据集近7天各部门的总库存",
        "退款产地数据集上月销售额最高的前5个平台",
        "转运预估和实际账单近7天调拨数量的按日趋势",
        "净利分解数据集上月各美国或非美的关税",
        "物控库存周转近7天各目的国的国内中转仓库存",
        "广告费数据集本月的SP广告占比",
        "净利分解数据集昨天的毛利率",
        "即时综合数据集昨天每个新/老品(物控编码)的星级",
        "入库预估和实际账单上月各品牌的物流部承担金额",
        "SKU仓库库龄明细上月各事业部每天的31-60天库龄走势",
        "Wayfair退货退款昨天各产品名称和各销售小组的退款金额(原币)",
        "近7天各平台的净推荐值",
        "近7天各仓库的销售额",
        "近7天各平台的销售额，用港币口径",
        "近7天只看亚马逊SC，同时排除亚马逊SC的销售额",
        "即时综合数据集近7天各平台的总库存和销售额",
        "各平台的销售额",
        "近7天各平台的销量，取销售额最高的前5个",
        "近7天卖得最好的3个平台",
        "近7天各平台的销售额跟上个周期比怎么样",
        "近7天销售额排前5的平台是哪些",
    ]


def snapshot_signature(contract: dict) -> dict[str, Any]:
    """行为快照只记录会影响查询语义的字段。"""
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    scope = er.get("time_scope") or {}
    templates = er.get("query_templates") or []
    return {
        "status": contract.get("status"),
        "table_id": er.get("table_id"),
        "dimensions": list(mv.get("dimensions") or []),
        "metrics": list(mv.get("metrics") or []),
        "clarification_reason_codes": sorted(mv.get("clarification_reason_codes") or []),
        "time_scope": [scope.get("start"), scope.get("end")],
        "query_template": _tpl(contract),
        "multi_currency": sorted(
            str(item.get("globalCurrency")) for item in templates if isinstance(item, dict)
        ),
        "snapshot_policy": bool(er.get("snapshot_policy")),
    }


# ---------------------------------------------------------------- 执行
def run_case(case: Case, email: str) -> Result:
    try:
        contract = run_plan(case.prompt, user_email=email)
    except Exception as exc:  # noqa: BLE001
        return Result(case=case, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-400:]}")
    if case.suite in ("scenario", "composite_report", "multi_value"):
        fails = check_scenario(case, contract)
    else:
        fails = check_synonym(case, contract)
    return Result(case=case, status=str(contract.get("status")), failures=fails,
                  contract=contract)


def run_snapshot(email: str, workers: int) -> dict[str, Any]:
    corpus = compatibility_corpus()
    signatures: dict[str, Any] = {}

    def plan(prompt: str) -> tuple[str, Any]:
        try:
            return prompt, snapshot_signature(run_plan(prompt, user_email=email))
        except Exception as exc:  # noqa: BLE001
            return prompt, {"error": f"{type(exc).__name__}: {exc}"}

    with futures.ThreadPoolExecutor(workers) as pool:
        for prompt, signature in pool.map(plan, corpus):
            signatures[prompt] = signature
    return signatures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="chenbenli@aukeys.com")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/planner-audit-20260909")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--suite", action="append")
    parser.add_argument("--tag", default="synonym")
    parser.add_argument("--snapshot", type=Path, help="把兼容语料的规划结果写入该文件")
    parser.add_argument("--compare", type=Path, help="用兼容语料重跑并与该快照比对")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.snapshot:
        signatures = run_snapshot(args.email, args.workers)
        args.snapshot.write_text(
            json.dumps(signatures, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        print(f"已写入行为快照 {len(signatures)} 条：{args.snapshot}")
        return

    if args.compare:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        current = run_snapshot(args.email, args.workers)
        diffs = []
        for prompt, before in baseline.items():
            after = current.get(prompt)
            if after != before:
                diffs.append({"prompt": prompt, "before": before, "after": after})
        for prompt in current:
            if prompt not in baseline:
                diffs.append({"prompt": prompt, "before": None, "after": current[prompt]})
        print(f"兼容语料 {len(current)} 条，行为变化 {len(diffs)} 条")
        for item in diffs:
            print(f"[DIFF] {item['prompt']}")
            print(f"    before: {json.dumps(item['before'], ensure_ascii=False)[:300]}")
            print(f"    after : {json.dumps(item['after'], ensure_ascii=False)[:300]}")
        out = args.output_dir / f"{args.tag}-compat-diff.json"
        out.write_text(json.dumps(diffs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"明细：{out}")
        return

    cases = (
        build_synonym_cases()
        + build_scenario_cases()
        + build_composite_report_cases()
        + build_multi_value_cases()
    )
    if args.suite:
        want = set(args.suite)
        cases = [c for c in cases if c.suite in want]
    print(f"用例 {len(cases)}")

    results: list[Result] = []
    with futures.ThreadPoolExecutor(args.workers) as pool:
        for res in pool.map(lambda c: run_case(c, args.email), cases):
            results.append(res)
            if not res.ok:
                print(f"[{'ERR' if res.error else 'FAIL'}] {res.case.case_id} | {res.case.prompt[:60]}")
                for item in (res.failures or [res.error])[:3]:
                    print(f"        - {str(item)[:180]}")

    consistency = check_group_consistency(results)
    for finding in consistency:
        print(f"[REL] {finding['group']} 同义词组模板不一致")
        print(f"        {json.dumps(finding['detail'], ensure_ascii=False)[:520]}")

    out = args.output_dir / f"{args.tag}-results.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for res in results:
            handle.write(json.dumps({
                "case_id": res.case.case_id, "suite": res.case.suite,
                "group": res.case.group, "persona": res.case.persona,
                "prompt": res.case.prompt, "expect": res.case.expect,
                "status": res.status, "ok": res.ok,
                "failures": res.failures, "error": res.error,
                "model_view": (res.contract or {}).get("model_view"),
                "template": _tpl(res.contract or {}),
            }, ensure_ascii=False, default=str) + "\n")

    bad = [r for r in results if not r.ok]
    print("\n==== 汇总 ====")
    print(f"总用例 {len(results)}，失败 {len(bad)}，同义词组不一致 {len(consistency)}")
    for suite, count in Counter(r.case.suite for r in bad).most_common():
        total = sum(1 for r in results if r.case.suite == suite)
        print(f"  {suite}: {count}/{total}")
    for persona, count in Counter(r.case.persona for r in bad).most_common():
        print(f"  persona {persona}: {count}")
    print(f"明细：{out}")


if __name__ == "__main__":
    main()
