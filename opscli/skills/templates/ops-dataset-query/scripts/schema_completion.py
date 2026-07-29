#!/usr/bin/env python3
"""确定性 schema 补全规则：纯标准库、无网络、可离线。

为什么需要：主规划器的字段打分末端是 token 集合交集，业务词与字段
中文名只是部分重叠时（「点击份额」对「购买份额」）会直接得 0 分，
整条查询因此零候选。本模块提供字符二元组相似度作为最后一层兜底，
按「召回优先于精确率」的原则设计——宁可多带候选交由澄清，
也不要因为匹配不上而完全没有候选。

阈值 0.5 取自 EDBT'26 schema linking 论文的近似字符串匹配规则。
"""

from __future__ import annotations

import re
import unicodedata

# 低于该相似度不视为命中：0.5 以下基本是偶然共享一两个字，
# 放进候选只会稀释排序而不会提升召回
FUZZY_MATCH_THRESHOLD = 0.5
# 少于两个字符无法构成二元组，直接判不匹配，避免单字命中一片字段
MIN_FUZZY_LENGTH = 2


def _normalize(value: object) -> str:
    """NFKC + casefold + 去首尾空白，与 dataset_guidance 的归一化口径一致。"""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _bigrams(text: str) -> set[str]:
    """切成相邻字符二元组集合，中文按字切、英文按字符切。"""
    return {text[index : index + 2] for index in range(len(text) - 1)}


def bigram_similarity(left: str, right: str) -> float:
    """字符二元组 Jaccard 相似度，返回 0.0~1.0。

    选二元组而不是编辑距离：中文业务词的差异通常是整词替换
    （「点击份额」/「购买份额」），二元组能保住共享的「份额」，
    而编辑距离会把它算成一半不同。
    """
    left_text, right_text = _normalize(left), _normalize(right)
    if len(left_text) < MIN_FUZZY_LENGTH or len(right_text) < MIN_FUZZY_LENGTH:
        return 0.0
    left_grams, right_grams = _bigrams(left_text), _bigrams(right_text)
    if not left_grams or not right_grams:
        return 0.0
    intersection = len(left_grams & right_grams)
    if not intersection:
        return 0.0
    return intersection / len(left_grams | right_grams)


# 查询按连词/标点切成「分句」用的分隔符。这里不含「的」——「X的Y」是极常见
# 的中文修饰结构（如「点击的份额」），如果把「的」当分句边界，会把修饰语
# 和中心词切断，剩下裸的「份额」这类短片段，靠双向包含会命中任何含
# 「份额」的字段（「退货份额」「曝光份额」都会被判定为 0.9 强命中），
# 判别力直接归零。因此分句阶段先不动「的」，交给 `_query_segments` 内部
# 针对每个分句单独处理。
_CLAUSE_SPLIT_RE = re.compile(r"[和与及或，,。.；;、\s]+")
_DE_RE = re.compile(r"的")


def _query_segments(query_text: str) -> list:
    """把查询切成候选业务词片段：每个分句生成「粘连版」+「核心词版」两类候选。

    - 粘连版：把分句内的「的」直接删掉拼接（「点击的份额」→「点击份额」）。
      保住「X的Y」整体语义的同时，避免裸「份额」这种通用词单独出现造成
      的误命中——「份额」不会再作为独立候选参与比对。
    - 核心词版：只取分句里最后一个「的」之后的部分（「搜索词的点击份额」
      →「点击份额」）。这一版是为了不让粘连版因为带上前面无关的修饰语
      （「搜索词」）而变长，进而在与更长字段名（如「ASIN点击份额」）
      比对时被稀释——粘连版整句拿去比对，长度差一拉大就会重演 Task 9
      最初要修的「整句稀释」问题，只是缩小到了分句级别。

    核心词版只有长度**大于** MIN_FUZZY_LENGTH（即至少 3 个字）才纳入候选：
    像「份额」这种长度正好等于 MIN_FUZZY_LENGTH 的通用业务名词单独拿出来
    几乎不具备判别力，任何以它结尾的字段都会被双向包含误判命中
    （这正是本函数要修的缺陷本身）；「点击份额」这种 4 字复合词判别力
    足够，可以放行。
    """
    segments = []
    for clause in _CLAUSE_SPLIT_RE.split(_normalize(query_text)):
        if not clause:
            continue
        glued = _DE_RE.sub("", clause)
        if len(glued) >= MIN_FUZZY_LENGTH:
            segments.append(glued)
        if "的" in clause:
            core = clause.rsplit("的", 1)[-1]
            if len(core) > MIN_FUZZY_LENGTH:
                segments.append(core)
    return segments


def best_fuzzy_score(query_text: str, labels: list) -> float:
    """取查询与一组字段标签的最高匹配度，低于阈值归零。

    为什么按片段而不是整句比对：整句会被长度稀释——实测
    「看一下搜索词的点击份额和购买份额」对完全同名的字段「点击份额」
    相似度只有 0.214，远低于 0.5 阈值，模糊分因此永不触发。

    为什么要双向包含：字段中文名常比用户说法长（字段「ASIN点击份额」
    对用户词「点击份额」），规划器既有的单向判断「字段名 in 查询」在这里
    不成立，只能靠 token 交集拿个位数分。双向包含按 0.9 计，
    仍低于 _field_score 的精确命中档位，不会挤掉准确字段。
    """
    segments = _query_segments(query_text)
    if not segments:
        return 0.0
    best = 0.0
    for label in labels:
        normalized_label = _normalize(label)
        if len(normalized_label) < MIN_FUZZY_LENGTH:
            continue
        for segment in segments:
            if segment in normalized_label or normalized_label in segment:
                best = max(best, 0.9)
                continue
            best = max(best, bigram_similarity(segment, normalized_label))
    return best if best >= FUZZY_MATCH_THRESHOLD else 0.0
