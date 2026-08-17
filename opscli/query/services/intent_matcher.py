"""Dataset catalog intent matching helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True)
class IntentMatchOptions:
    """Scoring knobs for catalog intent matching."""

    min_score: int = 30
    ambiguous_delta: int = 20


def match_catalog_intents(
    catalog: dict[str, Any],
    query: str,
    *,
    options: IntentMatchOptions | None = None,
) -> dict[str, Any]:
    """Match a natural language query against catalog intents.

    The matcher is intentionally deterministic and lightweight so both CLI and
    MCP callers receive the same decision shape.
    """
    opts = options or IntentMatchOptions()
    normalized_query = _normalize(query)
    if not normalized_query:
        raise ValueError("query 不能为空")

    intents = catalog.get("intents")
    if not isinstance(intents, list) or not intents:
        return _fallback_result(query=query, reason="empty_catalog", catalog=catalog)

    # embedded_intent 解析用：table_id -> 意图行。父表信息只能从 catalog 自身反查，
    # 匹配器没有 datasets.csv 可用；查不到父表时退回自身表，宁可少一层跳转
    # 也不能产出解析不出 table_id 的候选（旧画像腐烂的教训）
    intents_by_table_id = {
        _safe_int(item.get("table_id")): item
        for item in intents if isinstance(item, dict) and item.get("table_id")
    }

    scored = []
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        score, matched_terms, reason_parts = _score_intent(intent, normalized_query)
        if score >= opts.min_score:
            scored.append(
                _candidate(
                    intent=intent,
                    score=score,
                    matched_terms=matched_terms,
                    reason="；".join(reason_parts),
                    intents_by_table_id=intents_by_table_id,
                )
            )

    if not scored:
        return _fallback_result(query=query, reason="no_intent_match", catalog=catalog)

    scored.sort(key=lambda item: (-int(item["score"]), -int(item.get("priority") or 0), item["intent_code"]))
    top_score = int(scored[0]["score"])
    candidates = [item for item in scored if top_score - int(item["score"]) <= opts.ambiguous_delta]
    ask_required = len(candidates) > 1

    return {
        "matched": True,
        "query": query,
        "catalog_version": catalog.get("version"),
        "intent_count": catalog.get("intent_count", len(intents)),
        "ask_user_question_required": ask_required,
        "fallback_required": False,
        "fallback_reason": None,
        "candidates": candidates,
        "selected": None if ask_required else candidates[0],
        "agent_instruction": (
            "后续构造查询时必须优先遵循 selected.intent_constraints 中的业务口径、规则和约束，"
            "再执行 query_metadata 字段校验；若约束与硬性查询铁律冲突，以硬性铁律为准。"
        ),
    }


def _fallback_result(*, query: str, reason: str, catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "matched": False,
        "query": query,
        "catalog_version": catalog.get("version"),
        "intent_count": catalog.get("intent_count", 0),
        "ask_user_question_required": False,
        "fallback_required": True,
        "fallback_reason": reason,
        "fallback_query_keywords": _fallback_keywords(query),
        "candidates": [],
        "selected": None,
        "agent_instruction": "catalog 未命中时应静默回退到本地关键词搜索，再按候选数量进行结构化确认。",
    }


def _candidate(
    *,
    intent: dict[str, Any],
    score: int,
    matched_terms: list[str],
    reason: str,
    intents_by_table_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    # embedded_intent 意图自身不可执行，实际查询必须落到 execution_dataset_id
    # 指向的父表——这与 local_fallback._resolve_execution_row 的路由契约一致。
    # intent_code/intent_name/priority/约束仍取原 intent：披露口径要保留
    # 用户认知里的意图名，只有执行落点（table_id/alias/dataset_name）切到父表。
    routing_status = str(intent.get("routing_status") or "direct_intent")
    execution = intent
    embedded_from = None
    if routing_status == "embedded_intent":
        parent = intents_by_table_id.get(_safe_int(intent.get("execution_dataset_id")))
        if parent is not None:
            execution = parent
            embedded_from = _safe_int(intent.get("table_id"))

    return {
        "intent_code": str(intent.get("intent_code") or ""),
        "intent_name": str(intent.get("intent_name") or ""),
        "dataset_alias": execution.get("dataset_alias"),
        "table_id": execution.get("table_id"),
        "dataset_name": execution.get("dataset_name"),
        "priority": _safe_int(intent.get("priority")),
        "score": score,
        "matched_terms": matched_terms,
        "reason": reason,
        "intent_constraints": _intent_constraints(intent),
        "routing_status": routing_status,
        "embedded_from_table_id": embedded_from,
    }


def _intent_constraints(intent: dict[str, Any]) -> dict[str, Any]:
    """Carry all intent-provided query guidance to downstream callers."""
    constraints = {
        "scenario_description": intent.get("scenario_description") or intent.get("scenario"),
        "notes": intent.get("notes"),
        "default_filters": _value_or_default(intent.get("default_filters"), []),
        "comparison_strategy": _value_or_default(intent.get("comparison_strategy"), {}),
        "recommended_dimensions": _value_or_default(intent.get("recommended_dimensions"), []),
        "recommended_metrics": _value_or_default(intent.get("recommended_metrics"), []),
        "select_columns": _value_or_default(intent.get("select_columns"), []),
        # 业务约束护栏：catalog 里未经人工复核的约束也必须原样透传给 Agent，
        # 丢在匹配层等于把防错数护栏静默吞掉（local_fallback 路径一直是带的，两侧必须一致）
        "hard_constraints": _value_or_default(intent.get("hard_constraints"), []),
        "avoid_when": _value_or_default(intent.get("avoid_when"), []),
        "clarify_when": _value_or_default(intent.get("clarify_when"), []),
    }

    extra_rules = {}
    for key in (
        "query_rules",
        "rules",
        "constraints",
        "query_constraints",
        "field_rules",
        "filter_rules",
        "metric_rules",
    ):
        if key in intent:
            extra_rules[key] = intent.get(key)
    constraints["extra_rules"] = extra_rules
    return constraints


def _score_intent(intent: dict[str, Any], normalized_query: str) -> tuple[int, list[str], list[str]]:
    score = 0
    matched_terms: list[str] = []
    reason_parts: list[str] = []

    field_specs = [
        ("keywords", intent.get("keywords") or [], 100),
        ("use_cases", intent.get("use_cases") or intent.get("use_case") or [], 70),
        ("scenario_description", [intent.get("scenario_description") or intent.get("scenario") or ""], 40),
        ("intent_name", [intent.get("intent_name") or ""], 30),
        ("dataset_name", [intent.get("dataset_name") or ""], 30),
        ("dataset_alias", [intent.get("dataset_alias") or ""], 30),
    ]

    for field_name, raw_values, weight in field_specs:
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        field_matches = []
        for raw in values:
            value = _normalize(str(raw or ""))
            if not value:
                continue
            match_score = _match_text_score(value, normalized_query, weight)
            if match_score <= 0:
                continue
            score += match_score
            field_matches.append(str(raw))
            matched_terms.append(str(raw))
        if field_matches:
            reason_parts.append(f"{field_name} 命中 {', '.join(field_matches[:3])}")

    if score > 0:
        score += min(max(_safe_int(intent.get("priority")), 0), 1000) // 100

    deduped_terms = list(dict.fromkeys(item for item in matched_terms if item))
    return score, deduped_terms, reason_parts


def _match_text_score(candidate: str, query: str, weight: int) -> int:
    if candidate == query:
        return weight
    if candidate in query or query in candidate:
        return max(weight - 15, 1)

    candidate_tokens = set(_tokens(candidate))
    query_tokens = set(_tokens(query))
    if not candidate_tokens or not query_tokens:
        return 0

    overlap = candidate_tokens & query_tokens
    if not overlap:
        return 0
    ratio = len(overlap) / max(len(candidate_tokens), 1)
    return max(int(weight * ratio), 1)


def _tokens(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value)


def _fallback_keywords(query: str) -> list[str]:
    tokens = _tokens(_normalize(query))
    return tokens or [query.strip()]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _value_or_default(value: Any, default: Any) -> Any:
    return default if value is None else value
