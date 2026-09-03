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

# 全时段触发词：命中后返回空窗口，上层不注入任何日期筛选。
# 只收明确指向时间维度的表述——「全部数据」「全部ASIN」这类泛指不在其中，
# 否则「查傲彼瑞的全部ASIN」会被误判成不限时间。
_ALL_TIME_RE = re.compile(
    r"历史以来|有史以来|所有时间|全部时间|全时段|全部历史|历史全量|全量历史|"
    r"不限时间|不限日期|不卡时间|不卡日期|"
    r"不[加添]加?(?:任何)?(?:日期|时间)|不需要(?:任何)?(?:日期|时间)筛选"
)

# 否定语境：用户明确拒绝某个时间口径时，该口径不能被当成显式请求。
# 典型踩坑：「用户已明确拒绝默认近30天」里的「近30天」曾被识别为显式要求近30天，
# 导致越强调不要越被锁死。屏蔽范围只到最近的标点，
# 保证「不要近30天，查上月」的后半句仍能正常识别。
# 该词表同时被 query_plan 的字段标签匹配复用（见 negated_spans），
# 统一维护一份，避免时间口径与字段标签两处否定判定漂移。
# 词条选取有两条实测约束（2038 个真实字段标签统计）：
# ① 没有任何标签以 不/非/勿/别/无 开头，所以这些否定前缀不会吞掉标签开头；
# ② 「别」「不含」出现在标签内部（税别 / 币别 / 系统别名 / 周转天数(不含在途)），
#    因此禁止收裸「别」——它会让「查税别和日期」从「别」起屏蔽、连带吃掉日期。
# ③ 「别用/别加」与裸「非」还会被合成词从中间切中，必须加左边界断言（见下方注释）。
#    这类误判比漏判危险得多：它不是少屏蔽一段，而是把用户没说过的排除意图凭空造出来。
_NEGATED_SPAN_RE = re.compile(
    r"(?:拒绝|排除|不要|不用|不加|不添加|不需要|不按|不含|不带|不分|不显示|不展示"
    r"|无需|禁止"
    # 「分别用 A 和 B…」是多币种、多口径对比的标准问法，其中的「别用」曾被判为否定，
    # 把随后 12 字内的平台名当成排除项——语义直接反转。实测：
    # 「分别用人民币和美元查询亚马逊搜索词绩效」被读成「已按用户要求排除亚马逊SC、亚马逊VC」。
    r"|(?<![分区辨识差性特派级个类])别[用加]"
    r"|忽略|去掉|去除"
    # 裸「非」同理会被「非常」和「除非/并非/若非/是非/无非」从中间切中。实测：
    # 「查询非常规渠道亚马逊SC近7天」整段被判否定，亚马逊SC 被误排除。
    # 「非亚马逊VC」这类真否定不受影响。
    r"|(?<![除并莫若是无绝])非(?!常)"
    r"|勿)"
    r"[^，。；！？,;!?]{0,12}"
)


def negated_spans(text: str) -> list[tuple[int, int]]:
    """否定语境的字符区间，供按区间判定的调用方使用。

    为什么给区间而不是只给替换后的文本：真实元数据里存在
    「周转天数(不含在途)」这类自带否定词的合法字段标签，
    直接替换会把标签自身从中间撕开，用户点名的字段反而漏掉。
    改由调用方判断"标签是否整体落在否定区间内"，标签起点早于否定词时不受影响。
    """
    return [match.span() for match in _NEGATED_SPAN_RE.finditer(text)]


def mask_negated_spans(query: str) -> str:
    """把否定语境整段替换为空格（只适用于不需要保留原文位置的场景）。"""
    return _NEGATED_SPAN_RE.sub(" ", query)

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
_MONTH_THRESHOLD_LEFT_RE = re.compile(
    r"(?:超(?:过)?|大于|高于|多于|不少于|至少|库龄|账龄|货龄|周转)\s*$"
)
_MONTH_THRESHOLD_RIGHT_RE = re.compile(
    r"^\s*(?:个|以上|以下|以内|区间|分段|数量|采购金额)"
)
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


def _calendar_month_matches(query: str):
    """只返回自然月表达，排除“超6月/库龄6个月以上”等业务阈值。"""
    for match in _MONTH_RE.finditer(query):
        # 显式年份足以证明是日历月份，不受附近业务词影响。
        if match.group(1):
            yield match
            continue
        left = query[max(0, match.start() - 8) : match.start()]
        right = query[match.end() : match.end() + 8]
        if _MONTH_THRESHOLD_LEFT_RE.search(left) or _MONTH_THRESHOLD_RIGHT_RE.search(right):
            continue
        yield match


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
    for month_match in _calendar_month_matches(comparison_text):
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


def _window(query: str, today: date) -> tuple[date | None, date | None, str, bool]:
    """解析主周期窗口，返回 (start, end, 中文标签, 是否默认)。

    start/end 为 None 表示用户明确要求全时段，上层据此不注入日期筛选。
    """
    # 全时段判断必须在否定屏蔽之前：「不加日期筛选」「不限时间」本身就是否定形式，
    # 先屏蔽会把这类表述连同否定词一起清掉，导致全时段请求反被当成未识别。
    if _ALL_TIME_RE.search(query):
        return None, None, "全部时间（用户明确要求不加日期筛选）", False
    # 再剔除否定语境里的时间口径，避免「拒绝近30天」被当成「要近30天」
    query = _NEGATED_SPAN_RE.sub(" ", query)
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
    month_match = next(_calendar_month_matches(query), None)
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
        "start": None if start is None else _fmt(start),
        "end": None if end is None else _fmt(end),
        "unbounded": start is None or end is None,
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
    # 全时段：没有起止日期就没有环比/同比基准，直接返回空窗口合同
    if start is None or end is None:
        return result
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
