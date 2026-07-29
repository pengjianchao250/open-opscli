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


def best_fuzzy_score(query_text: str, labels: list) -> float:
    """取查询文本与一组字段标签的最高相似度，低于阈值归零。"""
    best = 0.0
    for label in labels:
        score = bigram_similarity(query_text, label)
        if score > best:
            best = score
    return best if best >= FUZZY_MATCH_THRESHOLD else 0.0
