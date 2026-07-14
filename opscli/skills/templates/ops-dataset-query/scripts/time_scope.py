#!/usr/bin/env python3
"""自然语言时间口径本地解析：把「近N天/昨天/本周/上月/环比/同比」解析为绝对日期窗口。

为什么需要：日期窗口靠模型心算是历史高频错误源（rules.md 自认），
沙箱多为 UTC 时区还会额外偏一天。本模块在规划合同内一次算出
Asia/Shanghai 口径的绝对日期与对比窗口，模型只做展示与填充、不再自算。

只用标准库；解析失败时返回 matched=False 并给出默认窗口（近30天含今天，
is_default=True，消费方必须向用户披露默认口径）。
"""

from __future__ import annotations

import re
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


def _window(query: str, today: date) -> tuple[date, date, str, bool]:
    """解析主周期窗口，返回 (start, end, 中文标签, 是否默认)。"""
    m = re.search(r"[近最][近]?\s*([0-9]+|[一两二三四五六七八九十]+)\s*(天|日|周|个?月)", query)
    if m:
        count = _num(m.group(1))
        unit = m.group(2)
        if count:
            if unit in ("天", "日"):
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
        return today.replace(day=1), today, "本月（1日至今天）", False
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
    start, end, label, is_default = _window(query or "", today)
    result: dict = {
        "start": _fmt(start),
        "end": _fmt(end),
        "label_zh": label,
        "timezone": TIMEZONE_NAME,
        "is_default": is_default,
        "matched": not is_default,
        "comparison": None,
    }
    text = query or ""
    if _COMPARE_YOY_RE.search(text):
        result["comparison"] = {
            "type": "yoy",
            "start": _fmt(_clamp_last_year(start)),
            "end": _fmt(_clamp_last_year(end)),
            "label_zh": "同比（去年同期）",
        }
    elif _COMPARE_PREV_RE.search(text):
        # 环比：紧邻的上一个等长周期
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
