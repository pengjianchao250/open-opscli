#!/usr/bin/env python3
"""
本地意图路由脚本：不依赖网络，从本地 YAML 文件匹配用户问题到业务意图和数据集。

用法：
    python scripts/route_intent.py "<用户自然语言问题>" [--top-n 3] [--data-dir data/]

输出（JSON）：
    {
      "query": "...",
      "top_results": [
        {
          "intent_id": "billing_sales_review",
          "intent_name": "...",
          "primary_dataset": "账单销售数据集",
          "execution_dataset": "账单销售数据集",
          "execution_alias": "ds_9e288aa0df06",
          "table_id": 2,
          "confidence": 0.85,
          "matched_keywords": ["销售额", "月度"],
          "routing_status": "direct_intent",
          "requires_clarification": false,
          "clarification_reasons": [],
          "avoid_when": [],
          "hard_constraints": []
        }
      ],
      "fallback_needed": false
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import]
except ImportError:
    print(
        json.dumps({"error": "缺少依赖 pyyaml，请执行: pip install 'pyyaml>=6'"}),
        file=sys.stderr,
    )
    sys.exit(1)

# 默认数据目录：scripts/ 的上级目录下的 data/
DATA_DIR = Path(__file__).parent.parent / "data"


def load_yaml(path: Path) -> dict:
    """加载 YAML 文件，文件不存在返回空字典。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _score_intent(query: str, intent: dict) -> tuple[float, list[str]]:
    """计算用户问题与意图的匹配得分，返回 (得分, 命中关键词列表)。

    评分策略：
    - trigger_keywords 每命中一个 +1.0
    - user_intent 描述中的词命中 query +0.3（辅助加成）
    """
    score = 0.0
    matched: list[str] = []
    query_lower = query.lower()

    for kw in intent.get("trigger_keywords", []):
        if str(kw).lower() in query_lower:
            score += 1.0
            matched.append(str(kw))

    # 用 user_intent 文本辅助加分
    for word in str(intent.get("user_intent", "")).replace("、", " ").split():
        if len(word) >= 2 and word in query_lower:
            score += 0.3

    return score, matched


def _find_profile(dataset_name: str, profiles: list[dict]) -> dict:
    """在 dataset_profiles.yml 的 datasets 列表中按 standard_name 查找画像。"""
    for profile in profiles:
        if profile.get("standard_name") == dataset_name:
            return profile
    return {}


def _check_clarification(query: str, intent: dict, profile: dict) -> tuple[bool, list[str]]:
    """判断是否需要澄清，返回 (requires_clarification, reasons)。

    合并 intent.clarify_when + profile.clarify_when，
    对条件文本中出现特定高风险词（如 SP词、SBV、报告周期）做启发式匹配。
    """
    # 高风险词：出现在条件描述中时，若 query 也含该词则触发澄清
    trigger_patterns = [
        "sp词", "sp 词", "词组", "sbv", "搜索词", "关键词", "投放词",
        "报告周期", "spu",
    ]
    conditions: list[str] = list(intent.get("clarify_when", [])) + list(
        profile.get("clarify_when", [])
    )
    query_lower = query.lower()
    reasons: list[str] = []

    for condition in conditions:
        cond_lower = condition.lower()
        # 若条件描述中包含某高风险词，且该词也在 query 中，则触发
        for pattern in trigger_patterns:
            if pattern in cond_lower and pattern in query_lower:
                reasons.append(condition)
                break

    return bool(reasons), reasons


def route(query: str, data_dir: Path = DATA_DIR, top_n: int = 3) -> dict:
    """执行本地意图路由，返回候选意图列表。

    Args:
        query:    用户自然语言问题
        data_dir: 包含 intent_taxonomy.yml 和 dataset_profiles.yml 的目录
        top_n:    最多返回的候选数量

    Returns:
        包含 query、top_results、fallback_needed 的字典
    """
    taxonomy = load_yaml(data_dir / "intent_taxonomy.yml")
    profiles_raw = load_yaml(data_dir / "dataset_profiles.yml")
    all_profiles = profiles_raw.get("datasets", [])

    scored: list[dict] = []

    for intent in taxonomy.get("intents", []):
        score, matched = _score_intent(query, intent)
        if score <= 0:
            continue

        primary_dataset = intent.get("primary_dataset", "")
        profile = _find_profile(primary_dataset, all_profiles)

        # 路由模式与执行数据集解析
        routing_status: str = profile.get("routing_status", "direct_intent")
        execution_dataset: str = primary_dataset
        execution_alias: str | None = profile.get("dataset_alias")
        table_id: int | None = profile.get("table_id")

        if routing_status == "embedded_intent":
            exec_name: str = profile.get("execution_dataset", "")
            exec_profile = _find_profile(exec_name, all_profiles)
            execution_dataset = exec_name
            execution_alias = exec_profile.get("dataset_alias")
            table_id = exec_profile.get("table_id")

        requires_clarification, clarification_reasons = _check_clarification(
            query, intent, profile
        )

        # confidence 归一化：命中关键词数 / 总关键词数的一半，上限 1.0
        kw_total = max(len(intent.get("trigger_keywords", [])), 1)
        confidence = round(min(score / (kw_total * 0.5), 1.0), 2)

        scored.append({
            "intent_id": intent.get("intent_id"),
            "intent_name": intent.get("user_intent", intent.get("intent_id")),
            "primary_dataset": primary_dataset,
            "execution_dataset": execution_dataset,
            "execution_alias": execution_alias,
            "table_id": table_id,
            "confidence": confidence,
            "matched_keywords": matched,
            "routing_status": routing_status,
            "requires_clarification": requires_clarification,
            "clarification_reasons": clarification_reasons,
            "avoid_when": profile.get("avoid_when", []),
            "hard_constraints": profile.get("hard_constraints", []),
        })

    scored.sort(key=lambda x: x["confidence"], reverse=True)

    return {
        "query": query,
        "top_results": scored[:top_n],
        "fallback_needed": len(scored) == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ops-dataset-query 本地意图路由（不依赖网络）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", help="用户自然语言问题")
    parser.add_argument(
        "--top-n", type=int, default=3, dest="top_n", help="最多返回候选数（默认 3）"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(DATA_DIR),
        dest="data_dir",
        help=f"数据目录路径（默认 {DATA_DIR}）",
    )
    args = parser.parse_args()

    result = route(args.query, Path(args.data_dir), args.top_n)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
