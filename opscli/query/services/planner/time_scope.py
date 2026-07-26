#!/usr/bin/env python3
"""自然语言时间口径本地解析：把「近N天/昨天/本周/上月/环比/同比」解析为绝对日期窗口。

为什么需要：日期窗口靠模型心算是历史高频错误源（rules.md 自认），
沙箱多为 UTC 时区还会额外偏一天。本模块在规划合同内一次算出
Asia/Shanghai 口径的绝对日期与对比窗口，模型只做展示与填充、不再自算。

只用 Python 标准库；未显式年份的相对时间统一以 Asia/Shanghai 当前日期与当前年份
为计算基准，跨年边界按真实日历处理。解析失败时返回 matched=False 并给出默认窗口
（近30天含今天，is_default=True，消费方必须向用户披露默认口径）。
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

try:  # zoneinfo 3.9+ 标准库；极端环境缺 tzdata 时回落固定 UTC+8
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    _TZ = timezone(timedelta(hours=8))

TIMEZONE_NAME = "Asia/Shanghai"
DEFAULT_DAYS = 30

# 中文数字（时间表达常用范围）
_CN_NUM = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十五": 15,
    "二十": 20, "三十": 30, "六十": 60, "九十": 90,
}

# 环比/上期 与 同比 的触发词
_COMPARE_PREV_RE = re.compile(r"环比|上一个|上期|前一?周期|较上|与上|对比上")
_COMPARE_YOY_RE = re.compile(r"同比|去年同期")
_MONTH_RE = re.compile(
    r"(?:(20\d{2})\s*年\s*)?(1[0-2]|[1-9])\s*月份?",
    re.IGNORECASE,
)
_COMPARISON_CUE_RE = re.compile(r"对比期?|比较|与|较|vs\.?", re.IGNORECASE)
# 绝对日期区间：2026-07-01 至 2026-07-15 / 2026年7月1日~7月15日（主周期与对比期共用）
_ABSOLUTE_RANGE_RE = re.compile(
    r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?\s*"
    r"(?:至|到|~|～|—|–)\s*"
    r"(?:(20\d{2})[-/.年])?(\d{1,2})[-/.月](\d{1,2})日?"
)


def _num(text: str) -> int | None:
    """解析阿拉伯或中文数字。"""
    if text.isdigit():
        return int(text)
    return _CN_NUM.get(text)


def _fmt(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _clamp_last_year(value: date) -> date:
    """取去年同日，2/29 回退到 2/28。"""
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _quarter_window(year: int, quarter: int) -> tuple[date, date]:
    """返回指定自然季度首尾日期。"""
    month = (quarter - 1) * 3 + 1
    return date(year, month, 1), date(year, month + 2, monthrange(year, month + 2)[1])


def _parsed_date(year: str, month: str, day: str) -> date | None:
    """安全解析日期，非法日历日期返回 None 交由后续规则处理。"""
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _month_window(year: int, month: int) -> tuple[date, date]:
    """返回指定自然月首尾日期。"""
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _explicit_comparison(
    query: str, today: date, primary: tuple[date, date] | None = None
) -> dict | None:
    """解析用户明确给出的第二个对比日期范围或自然月。

    显式对比优先于“环比”自动平移，避免“2026年6月与2026年5月对比”
    被误算成全年或等长365天窗口。

    为什么要跳过主周期：对比线索词可能出现在主周期**之前**（“对比6月(2026-06-01
    ~2026-06-30)与5月(2026-05-01~2026-05-31)”），此时线索词之后的第一个区间正是
    主周期自身。若直接采纳，对比期将等于主周期——环比恒为 0、差值恒为空，且不报
    任何错（静默出错数）。故逐个遍历候选区间，跳过与主周期完全重合者取下一个；
    没有第二个可用区间时返回 None，交由上层的环比/同比规则处理，绝不伪造对比期。

    Args:
        primary: 已解析出的主周期 (start, end)，用于排除重合候选；None 表示不排除。
    """
    cue = _COMPARISON_CUE_RE.search(query)
    if not cue:
        return None
    comparison_text = query[cue.end() :]
    for absolute in _ABSOLUTE_RANGE_RE.finditer(comparison_text):
        start = _parsed_date(absolute.group(1), absolute.group(2), absolute.group(3))
        end = _parsed_date(
            absolute.group(4) or absolute.group(1),
            absolute.group(5),
            absolute.group(6),
        )
        if not (start and end and start <= end):
            continue
        if primary is not None and (start, end) == primary:
            continue
        return {
            "type": "explicit_period",
            "start": _fmt(start),
            "end": _fmt(end),
            "label_zh": "显式对比周期",
        }
    for month_match in _MONTH_RE.finditer(comparison_text):
        year = int(month_match.group(1) or today.year)
        start, end = _month_window(year, int(month_match.group(2)))
        if primary is not None and (start, end) == primary:
            continue
        return {
            "type": "explicit_period",
            "start": _fmt(start),
            "end": _fmt(end),
            "label_zh": "显式对比自然月",
        }
    return None


def _window(query: str, today: date) -> tuple[date, date, str, bool]:
    """解析主周期窗口，返回 (start, end, 中文标签, 是否默认)。"""
    # 明确绝对日期范围：2026-07-01 至 2026-07-15 / 2026年7月1日~7月15日
    absolute = _ABSOLUTE_RANGE_RE.search(query)
    if absolute:
        start = _parsed_date(absolute.group(1), absolute.group(2), absolute.group(3))
        end = _parsed_date(
            absolute.group(4) or absolute.group(1),
            absolute.group(5),
            absolute.group(6),
        )
        if start and end and start <= end:
            return start, end, f"明确日期范围 {_fmt(start)} 至 {_fmt(end)}", False

    # 指定自然季度：2026Q2 / 2026年第2季度 / 2026年第二季度
    quarter_match = re.search(
        r"(20\d{2})\s*(?:年)?\s*(?:Q([1-4])|第?([一二三四1-4])季度)",
        query,
        re.IGNORECASE,
    )
    if quarter_match:
        raw_quarter = quarter_match.group(2) or quarter_match.group(3)
        quarter = _num(raw_quarter)
        if quarter:
            start, end = _quarter_window(int(quarter_match.group(1)), quarter)
            return start, end, f"{start.year}年第{quarter}季度", False
    current_quarter = (today.month - 1) // 3 + 1
    if re.search(r"本季度|本季|这个季度", query):
        start, _end = _quarter_window(today.year, current_quarter)
        return start, today, "本季度（季度首日至今天）", False
    if re.search(r"上季度|上个季度|上一季度", query):
        year = today.year if current_quarter > 1 else today.year - 1
        quarter = current_quarter - 1 if current_quarter > 1 else 4
        start, end = _quarter_window(year, quarter)
        return start, end, f"上季度（{year}年第{quarter}季度）", False

    # 指定自然月必须优先于自然年匹配，否则“2026年6月”会被截断成全年。
    month_match = _MONTH_RE.search(query)
    if month_match:
        year = int(month_match.group(1) or today.year)
        month = int(month_match.group(2))
        start, end = _month_window(year, month)
        return start, end, f"{year}年{month}月（自然月）", False

    # 指定自然年与本年/去年。
    year_match = re.search(r"(20\d{2})年(?:全年)?", query)
    if year_match:
        year = int(year_match.group(1))
        return date(year, 1, 1), date(year, 12, 31), f"{year}年全年", False
    if re.search(r"今年|本年", query):
        return date(today.year, 1, 1), today, "今年（1月1日至今天）", False
    if re.search(r"去年|上年", query):
        year = today.year - 1
        return date(year, 1, 1), date(year, 12, 31), f"去年（{year}年全年）", False

    m = re.search(
        r"[近最][近]?\s*([0-9]+|[一两二三四五六七八九十]+)\s*"
        r"(天|日|tian|days?|周|个?月)",
        query,
        re.IGNORECASE,
    )
    if m:
        count = _num(m.group(1))
        unit = m.group(2).casefold()
        if count:
            if unit in ("天", "日", "tian", "day", "days"):
                start = today - timedelta(days=count - 1)
                return start, today, f"近{count}天（含今天）", False
            if unit == "周":
                start = today - timedelta(days=count * 7 - 1)
                return start, today, f"近{count}周（含今天）", False
            # 近N个月：按 N*30 天近似，标签中如实声明口径
            start = today - timedelta(days=count * 30 - 1)
            return start, today, f"近{count}个月（按{count * 30}天计，含今天）", False
    if re.search(r"昨天|昨日", query):
        day = today - timedelta(days=1)
        return day, day, "昨天", False
    if re.search(r"今天|今日|当天", query):
        return today, today, "今天", False
    if re.search(r"本周|这周", query):
        start = today - timedelta(days=today.weekday())
        return start, today, "本周（周一至今天）", False
    if re.search(r"上周", query):
        this_monday = today - timedelta(days=today.weekday())
        return this_monday - timedelta(days=7), this_monday - timedelta(days=1), "上周（周一至周日）", False
    if re.search(r"本月|这个月", query):
        # 整月口径：本月固定为 1 日至本月最后一天；月末未到时窗口尾部尚无数据，
        # 由消费方在结果中披露数据更新进度，不因此改回「至今天」或要求用户确认
        month_end = today.replace(day=monthrange(today.year, today.month)[1])
        return today.replace(day=1), month_end, "本月（整月，1日至月末）", False
    if re.search(r"上月|上个月", query):
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev, "上月（自然月）", False
    # 未识别：默认近30天含今天，消费方必须披露
    start = today - timedelta(days=DEFAULT_DAYS - 1)
    return start, today, f"默认近{DEFAULT_DAYS}天（含今天，未识别到明确时间表述）", True


def parse(query: str, *, today: date | None = None) -> dict:
    """解析查询文本的时间口径，返回绝对日期窗口合同。

    Args:
        query: 用户查询原文
        today: 仅测试注入用；缺省取 Asia/Shanghai 当天
    """
    if today is None:
        today = datetime.now(_TZ).date()
    text = query or ""
    start, end, label, is_default = _window(text, today)
    result: dict = {
        "start": _fmt(start),
        "end": _fmt(end),
        "label_zh": label,
        "timezone": TIMEZONE_NAME,
        "reference_date": _fmt(today),
        "reference_year": today.year,
        "resolution_source": "python_datetime_asia_shanghai",
        "year_source": (
            "explicit_query" if re.search(r"20\d{2}", text) else "python_current_date"
        ),
        "is_default": is_default,
        "matched": not is_default,
        "comparison": None,
    }
    # 传入主周期，避免把主周期自身当成对比期（“对比A与B”结构线索词在主周期之前）
    explicit_comparison = _explicit_comparison(text, today, primary=(start, end))
    if explicit_comparison:
        result["comparison"] = explicit_comparison
    elif _COMPARE_YOY_RE.search(text):
        result["comparison"] = {
            "type": "yoy",
            "start": _fmt(_clamp_last_year(start)),
            "end": _fmt(_clamp_last_year(end)),
            "label_zh": "同比（去年同期）",
        }
    elif _COMPARE_PREV_RE.search(text):
        # 环比：整自然月窗口（如本月/上月）固定对比上一个自然月，整月对整月，
        # 大小月天数差异属正常口径；其他窗口取紧邻的上一个等长周期
        is_natural_month = (
            start.day == 1
            and start.year == end.year
            and start.month == end.month
            and end.day == monthrange(end.year, end.month)[1]
        )
        if is_natural_month:
            prev_last = start - timedelta(days=1)
            result["comparison"] = {
                "type": "period_over_period",
                "start": _fmt(prev_last.replace(day=1)),
                "end": _fmt(prev_last),
                "label_zh": "环比（上一个自然月）",
            }
        else:
            length = (end - start).days + 1
            result["comparison"] = {
                "type": "period_over_period",
                "start": _fmt(start - timedelta(days=length)),
                "end": _fmt(start - timedelta(days=1)),
                "label_zh": f"环比（上一个等长{length}天周期）",
            }
    return result


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(parse(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
