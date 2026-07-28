#!/usr/bin/env python3
"""为规划器执行合同生成并校验稳定摘要，防止计划在执行前被意外改写。"""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from typing import Any


ALGORITHM = "sha256"


def _canonical_payload(plan: dict[str, Any]) -> bytes:
    """移除摘要自身后生成稳定、与键顺序无关的 UTF-8 表示。"""
    canonical = deepcopy(plan)
    execution = canonical.get("execution_ref")
    if isinstance(execution, dict):
        execution.pop("plan_integrity", None)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def calculate_digest(plan: dict[str, Any]) -> str:
    """计算完整规划合同的 SHA-256 摘要。"""
    return hashlib.sha256(_canonical_payload(plan)).hexdigest()


def attach(plan: dict[str, Any]) -> dict[str, Any]:
    """把摘要附加到执行引用并返回原规划合同。"""
    execution = plan.setdefault("execution_ref", {})
    execution["plan_integrity"] = {
        "algorithm": ALGORITHM,
        "digest": calculate_digest(plan),
    }
    return plan


def verify(plan: dict[str, Any]) -> bool:
    """校验规划合同是否仍与规划器生成时一致。"""
    execution = plan.get("execution_ref")
    if not isinstance(execution, dict):
        return False
    integrity = execution.get("plan_integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != ALGORITHM:
        return False
    expected = str(integrity.get("digest") or "")
    actual = calculate_digest(plan)
    return bool(expected) and hmac.compare_digest(expected, actual)
