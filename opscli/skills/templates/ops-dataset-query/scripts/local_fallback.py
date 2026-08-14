#!/usr/bin/env python3
"""规划器降级路径：纯本地确定数据集与字段，绝不猜测。

什么时候用：只在 `query_flow.py` / `query_plan.py` 返回非 planned（blocked /
clarify_required）且合同里也拿不到可用目录时使用。规划器正常出模板时不要用本脚本。

为什么需要：规划器一旦因网络、枚举或元数据未就绪而失败，Agent 手上没有权威的
表名字段名，就会凭记忆编造数据集与字段（线上实测形态：转投其他 Skill 或改用 MCP
重来，中途自行编表名）。本脚本把旧版 ops-dataset-query 的本地索引能力接回来：
意图路由 + 字段搜索全部读本地文件，不依赖网络，也不依赖第三方库。

用法：
    python3 scripts/local_fallback.py "<用户原文>"                # 输出候选与下一步
    python3 scripts/local_fallback.py "<用户原文>" --field 渠道 --field ASIN
    python3 scripts/local_fallback.py "<用户原文>" --dataset ds_xxx --emit-plan plan.json

输出为 JSON 合同，字段含义见 README-字段使用.md。
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Sequence

import core

# 候选返回上限：候选太多等于没有候选，Agent 会退回猜测
MAX_DATASET_CANDIDATES = 5
MAX_FIELD_CANDIDATES = 20


def _normalize(value: object) -> str:
    """匹配用归一化：NFKC + 去空白 + 转小写。"""
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _load_catalog(data_dir: Path) -> dict:
    """加载服务端意图目录（意图触发词 + 数据集业务约束）；缺失时返回空结构。

    为什么用 dataset_catalog.json 而不是过去的人工画像 dataset_profiles.json：
    画像靠人工维护且从不随 upgrade 刷新，实测 15 份画像的 dataset_alias 只剩 2 份
    还能在 datasets.csv 里查到——路由中文名看着还对，产出的候选却解析不出 table_id，
    Agent 拿到手也执行不了。catalog 由服务端生成、随 upgrade 原子刷新，
    41 条意图覆盖 36 个数据集，alias 全部有效。
    """
    path = data_dir / "dataset_catalog.json"
    if not path.is_file():
        return {"intents": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"intents": []}
    return payload if isinstance(payload, dict) else {"intents": []}


def _data_state(data_dir: Path) -> str:
    """读 VERSION.json 的 data_state；缺失按 unknown 处理。"""
    path = data_dir / "VERSION.json"
    if not path.is_file():
        return "unknown"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("data_state", "unknown"))
    except (OSError, json.JSONDecodeError):
        return "unknown"


def _metadata_version(data_dir: Path) -> str:
    """读 VERSION.json 的 version，用于在结果里标注目录快照版本。"""
    path = data_dir / "VERSION.json"
    if not path.is_file():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("version", ""))
    except (OSError, json.JSONDecodeError):
        return ""


def _score_intent(query: str, intent: dict) -> tuple[float, list[str], float]:
    """给意图打分，返回 (得分, 命中词, 归一化置信度)。

    逐条沿用旧版 route_intent.py 的策略，两处细节都不能省：
    - 触发词每命中一个 +1.0；意图名里的词命中再 +0.3。少了后者，
      「今天销售怎么样」这类不含任何触发词的问法会一个候选都产不出来。
    - 排序按 score/(触发词总数*0.5) 归一化后的置信度，而不是原始分。少了归一化，
      触发词多的宽口径数据集会靠数量压过更精准的窄口径数据集（实测「亚马逊目录
      绩效点击率」会被广告费数据集顶掉）。

    只吃 keywords 与 intent_name 两个信号：catalog 另有 use_cases /
    scenario_description 两组自然语言长句，实测把它们也纳入打分对 21 条历史用例
    零增益，反而把「沃尔玛平台广告活动明细」的首选从活动数据集带偏到即时综合数据集。
    """
    normalized = _normalize(query)
    triggers = intent.get("keywords") or []
    matched = [
        str(term) for term in triggers if _normalize(term) and _normalize(term) in normalized
    ]
    score = float(len(matched))
    for word in str(intent.get("intent_name", "")).replace("、", " ").split():
        if len(word) >= 2 and _normalize(word) in normalized:
            score += 0.3
    confidence = round(min(score / (max(len(triggers), 1) * 0.5), 1.0), 2)
    return score, matched, confidence


def _dataset_rows(data_dir: Path) -> list[dict]:
    """读 datasets.csv，得到 table_id / dataset_alias / 中文名的权威对应。"""
    return core.load_csv_rows(data_dir / "datasets.csv")


def _resolve_execution_row(intent: dict, own_row: dict, by_table_id: dict) -> dict:
    """解析意图的实际执行数据集：embedded_intent 要落到承接它的父数据集。

    按 execution_dataset_id（table_id）解析而不是按中文名：中文名这条链没有 ID
    保护，数据集一改名就静默断裂，正是旧画像腐烂的根因。父表查不到时退回自身表，
    宁可少一层跳转也不能产出一个解析不出 table_id 的候选。
    """
    if intent.get("routing_status") != "embedded_intent":
        return own_row
    return by_table_id.get(str(intent.get("execution_dataset_id") or ""), own_row)


def _default_field_labels(data_dir: Path, dataset_alias: str, field_type: str, limit: int = 8) -> list:
    """实时从 CSV 取该数据集的代表性字段中文名。

    为什么不从静态文件读：默认维度指标完全可由元数据派生，
    写进静态文件只会与后端漂移——旧画像时期实测 15 份已有 5 份对不上。
    """
    if not dataset_alias:
        return []
    labels = [
        str(row.get("verbose_name", ""))
        for row in core.load_csv_rows(Path(data_dir) / "dataset_fields.csv")
        if str(row.get("dataset_alias", "")) == dataset_alias
        and str(row.get("field_type", "")) == field_type
        and row.get("verbose_name")
    ]
    return list(dict.fromkeys(labels))[:limit]


def _dataset_candidates(query: str, data_dir: Path, catalog: dict) -> list[dict]:
    """本地确定数据集候选：先意图路由，未命中再退关键词匹配数据集描述。"""
    rows = _dataset_rows(data_dir)
    by_alias = {str(row.get("dataset_alias", "")): row for row in rows}
    by_table_id = {str(row.get("table_id", "")): row for row in rows}

    scored: list[dict] = []
    for intent in catalog.get("intents") or []:
        score, matched, confidence = _score_intent(query, intent)
        if score <= 0:
            continue
        # 中文名与 table_id 一律取自 datasets.csv：catalog 自带 table_id/dataset_name，
        # 但 CSV 才是本次授权范围的权威快照，用 CSV 回查能在 catalog 落后于元数据时
        # 直接暴露成候选缺 table_id，而不是把一个查不到的表交给 Agent
        own_row = by_alias.get(str(intent.get("dataset_alias") or ""), {})
        target = _resolve_execution_row(intent, own_row, by_table_id)
        alias = str(target.get("dataset_alias") or "")
        constraints = intent.get("hard_constraints") or []
        scored.append(
            {
                "source": "intent_route",
                "intent_id": intent.get("intent_code"),
                "matched_terms": matched,
                "score": score,
                "confidence": confidence,
                "name_zh": own_row.get("description") or intent.get("intent_name"),
                "execution_dataset": target.get("description"),
                "dataset_alias": alias or None,
                "table_id": target.get("table_id"),
                "routing_status": intent.get("routing_status") or "direct_intent",
                # catalog 的业务约束同样未经人工复核（39/41 条 notes 明写
                # "require manual review"），因此维持与画像时期一致的两桶口径：
                # 一律走 uncertified_hints_zh 提示，不冒充 hard_constraints 权威规则
                "hard_constraints": [],
                "uncertified_hints_zh": constraints,
                "avoid_when": intent.get("avoid_when") or [],
                "clarify_when": intent.get("clarify_when") or [],
                # 默认维度指标实时取，不从静态文件读
                "default_dimensions": _default_field_labels(data_dir, alias, "dimension"),
                "default_metrics": _default_field_labels(data_dir, alias, "metric"),
            }
        )

    if not scored:
        # 意图未命中：退化为按数据集中文名/描述做关键词匹配
        normalized = _normalize(query)
        for row in rows:
            label = str(row.get("description") or row.get("dataset_name") or "")
            if not label:
                continue
            if _normalize(label) and _normalize(label) in normalized:
                scored.append(
                    {
                        "source": "dataset_name_match",
                        "matched_terms": [label],
                        "score": 1.0,
                        "confidence": 1.0,
                        "name_zh": label,
                        "dataset_alias": row.get("dataset_alias"),
                        "table_id": row.get("table_id"),
                        "hard_constraints": [],
                        "avoid_when": [],
                        "clarify_when": [],
                    }
                )

    # 按归一化置信度排序，同分再看原始得分，与旧版排序口径一致
    scored.sort(key=lambda item: (item.get("confidence", 0.0), item["score"]), reverse=True)
    return scored[:MAX_DATASET_CANDIDATES]


def _field_candidates(
    query: str,
    data_dir: Path,
    dataset_alias: str | None,
    requested: Sequence[str],
    candidate_aliases: Sequence[str] = (),
) -> list[dict]:
    """在授权字段表里找候选字段：点名字段优先，其次按原文关键词。

    只返回 CSV 里真实存在的字段——这正是降级路径存在的意义：
    宁可返回空候选让 Agent 去问用户，也不许它编一个字段名出来。
    """
    rows = core.load_csv_rows(data_dir / "dataset_fields.csv")
    # 已定数据集时只看该表；未定时限定在候选数据集内——不限定会把全部数据集的
    # 同名字段（如 5 张表都有的「销售」）一起刷出来，候选列表失去参考价值
    scope = {dataset_alias} if dataset_alias else {a for a in candidate_aliases if a}
    if scope:
        rows = [row for row in rows if str(row.get("dataset_alias", "")) in scope]

    terms = [term for term in requested if str(term).strip()]
    normalized_query = _normalize(query)
    hits: list[dict] = []
    for row in rows:
        verbose = str(row.get("verbose_name", ""))
        field_name = str(row.get("field_name", ""))
        if not field_name:
            continue
        matched_by = ""
        if terms and any(_normalize(term) == _normalize(verbose) for term in terms):
            matched_by = "requested_field"
        elif terms and any(_normalize(term) == _normalize(field_name) for term in terms):
            matched_by = "requested_field"
        elif verbose and _normalize(verbose) in normalized_query:
            matched_by = "query_term"
        if not matched_by:
            continue
        hits.append(
            {
                "field_name": field_name,
                "verbose_name": verbose,
                "field_type": row.get("field_type", ""),
                "dataset_alias": row.get("dataset_alias", ""),
                "matched_by": matched_by,
            }
        )
    # 同名字段会横跨多个数据集，按 (数据集, 字段) 去重，否则候选列表被同一字段刷满
    unique: dict[tuple, dict] = {}
    for item in hits:
        unique.setdefault((item["dataset_alias"], item["field_name"]), item)
    ordered = sorted(
        unique.values(),
        key=lambda item: 0 if item["matched_by"] == "requested_field" else 1,
    )
    return ordered[:MAX_FIELD_CANDIDATES]


def _filter_components(data_dir: Path, dataset_alias: str | None) -> list[dict]:
    """列出该数据集的查询组件字段：筛选值必须先在组件里枚举校验权限。"""
    if not dataset_alias:
        return []
    rows = core.load_csv_rows(data_dir / "dataset_select_columns.csv")
    return [
        {
            "field_name": row.get("column_name", ""),
            "label_zh": row.get("verbose_name", ""),
            "component_dataset_alias": row.get("component_dataset_alias", ""),
        }
        for row in rows
        if str(row.get("current_dataset_alias", "")) == dataset_alias
    ]


def audit_profiles(*, data_dir: Path | None = None) -> dict:
    """巡检意图目录覆盖率：哪些数据集没有意图、哪些意图已对不上元数据。

    为什么需要：catalog 由服务端生成，与本地 datasets.csv 是两次独立下发，
    两者之间仍可能漂移（意图指向的表已下线、新表还没配意图），
    没有巡检就只能等降级路径产不出候选时才发现。

    这是只读巡检，不做任何查询、不修改任何目录或元数据文件。
    """
    resolved = Path(data_dir) if data_dir else core.discover_data_dir()
    if resolved is None or not resolved.is_dir():
        # blocked 载荷字段形状对齐 build_fallback() 的同类分支（data_state +
        # recovery_command），避免同一文件里两份 blocked 合同长得不一样让人误读
        return {
            "status": "blocked",
            "data_state": "missing",
            "next_action_zh": "本地数据目录不存在，先执行 opscli skills upgrade ops-dataset-query。",
            "recovery_command": "opscli skills upgrade ops-dataset-query",
        }
    state = _data_state(resolved)
    if state in ("placeholder", "empty"):
        # 占位态下 datasets.csv 是空模板，统计出来的覆盖率数字全是假的（分子分母同时
        # 归零），必须先挡住并给出恢复指引，否则巡检结果会被误读成"意图已全部失效"
        return {
            "status": "blocked",
            "data_state": state,
            "next_action_zh": "本地索引是空模板，无法统计真实覆盖率。先执行 opscli skills upgrade ops-dataset-query 刷新后重跑。",
            "recovery_command": "opscli skills upgrade ops-dataset-query",
        }
    datasets = core.load_csv_rows(resolved / "datasets.csv")
    aliases = {str(row.get("dataset_alias", "")) for row in datasets if row.get("dataset_alias")}
    table_ids = {str(row.get("table_id", "")) for row in datasets if row.get("table_id")}
    intents = _load_catalog(resolved).get("intents") or []
    profiled = {str(item.get("dataset_alias", "")) for item in intents if item.get("dataset_alias")}
    # 追加范围：embedded_intent 按 execution_dataset_id 回指父表，父表下线后
    # 这条跳转会静默失效——巡检必须把这类断链也报出来，不能只查数据集覆盖率
    broken_intent_links = [
        {
            "intent_id": intent.get("intent_code"),
            "execution_dataset_id": intent.get("execution_dataset_id"),
        }
        for intent in intents
        if intent.get("routing_status") == "embedded_intent"
        and str(intent.get("execution_dataset_id") or "") not in table_ids
    ]
    return {
        "status": "ok",
        "total_datasets": len(aliases),
        "profiled": len(profiled & aliases),
        "missing_profiles": sorted(aliases - profiled),
        "stale_profiles": sorted(profiled - aliases),
        "broken_intent_links": broken_intent_links,
        "next_action_zh": (
            "missing_profiles 中的数据集尚无意图入口，降级路径路由不到，需要服务端补配；"
            "stale_profiles 已对不上元数据，说明 catalog 落后于 datasets.csv，先重跑 upgrade；"
            "broken_intent_links 中的意图 execution_dataset_id 找不到对应表，需要服务端修复。"
        ),
    }


def build_fallback(
    query: str,
    *,
    requested_fields: Sequence[str] = (),
    dataset_alias: str | None = None,
    data_dir: Path | None = None,
) -> dict:
    """构建降级合同：本地能确定什么就给什么，确定不了就要求澄清。"""
    resolved_dir = Path(data_dir) if data_dir else core.discover_data_dir()
    if resolved_dir is not None and not resolved_dir.is_dir():
        resolved_dir = None
    if resolved_dir is None:
        return {
            "contract": "local_fallback_v1",
            "fallback_level": "L3_metadata_refresh",
            "status": "blocked",
            "data_state": "missing",
            "next_action_zh": "本地数据目录不存在，先执行 recovery_command 再重试；此前不得构造任何查询。",
            "recovery_command": "opscli skills upgrade ops-dataset-query",
        }

    state = _data_state(resolved_dir)
    if state in ("placeholder", "empty"):
        return {
            "contract": "local_fallback_v1",
            "fallback_level": "L3_metadata_refresh",
            "status": "blocked",
            "data_state": state,
            "metadata_version": _metadata_version(resolved_dir),
            "next_action_zh": (
                "本地索引是空模板，无法确认任何数据集与字段。先执行 recovery_command "
                "刷新后重跑；在此之前禁止凭记忆构造数据集名或字段名。"
            ),
            "recovery_command": "opscli skills upgrade ops-dataset-query",
        }

    catalog = _load_catalog(resolved_dir)
    if dataset_alias:
        # 用户已点名数据集：直接按 CSV 权威记录确认，不再走意图路由
        row = next(
            (
                item
                for item in _dataset_rows(resolved_dir)
                if str(item.get("dataset_alias", "")) == dataset_alias
            ),
            None,
        )
        datasets = (
            [
                {
                    "source": "user_specified",
                    "score": 1.0,
                    "matched_terms": [dataset_alias],
                    "name_zh": row.get("description") or row.get("dataset_name"),
                    "dataset_alias": dataset_alias,
                    "table_id": row.get("table_id"),
                    "hard_constraints": [],
                    "avoid_when": [],
                    "clarify_when": [],
                }
            ]
            if row
            else []
        )
    else:
        datasets = _dataset_candidates(query, resolved_dir, catalog)
    chosen_alias = dataset_alias or (
        datasets[0].get("dataset_alias") if len(datasets) == 1 else None
    )
    fields = _field_candidates(
        query,
        resolved_dir,
        chosen_alias,
        requested_fields,
        candidate_aliases=[str(item.get("dataset_alias") or "") for item in datasets],
    )

    # 数据集或字段不唯一时一律要求澄清：降级路径尤其不能替用户做主
    needs_clarify = len(datasets) != 1 or (bool(requested_fields) and not fields)
    result = {
        "contract": "local_fallback_v1",
        "fallback_level": "L2_local_index",
        "status": "clarify_required" if needs_clarify else "ready",
        "data_state": state,
        "metadata_version": _metadata_version(resolved_dir),
        "data_dir": str(resolved_dir),
        "dataset_candidates": datasets,
        "selected_dataset_alias": chosen_alias,
        "field_candidates": fields,
        "filter_components": _filter_components(resolved_dir, chosen_alias),
        "no_guess_policy_zh": (
            "只能使用本结果中出现的 table_id、dataset_alias 与 field_name；"
            "禁止凭记忆或推测编造任何数据集名、字段名与枚举值。"
            "候选为空或多于一个时，必须用 AskUserQuestion 让用户选择后再继续。"
        ),
        "filter_value_policy_zh": (
            "filter_components 中的字段属于查询组件，其筛选值必须先查 component_dataset_alias "
            "对应组件表枚举当前账号授权原值，完整等值命中后才能写入 filters；"
            "枚举不到就停止，不得放大为全范围查询。"
        ),
    }
    result["next_action_zh"] = (
        "候选不唯一，用 AskUserQuestion 让用户在候选中选择后再继续。"
        if needs_clarify
        else "数据集与字段已在本地确认，可据此构造查询；筛选值仍需按 filter_value_policy_zh 校验权限。"
    )
    return result


def _emit_plan(result: dict, path: Path) -> None:
    """把降级结果写成最小 plan 文件，供 run_query.py --plan-file 消费。

    走执行器的好处是保留 _assert_fields 字段校验闸：payload 里出现目录之外的
    字段会被直接拒绝，降级路径因此仍受「不许猜」约束。
    """
    plan = {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "status": "planned",
        "data_state": result.get("data_state", ""),
        "metadata_version": result.get("metadata_version", ""),
        "plan_source": "local_fallback",
        "model_view": {
            "dataset_name_zh": (result.get("dataset_candidates") or [{}])[0].get("name_zh", ""),
            "dimensions": [
                item["verbose_name"]
                for item in result.get("field_candidates") or []
                if item.get("field_type") == "dimension"
            ],
            "metrics": [
                item["verbose_name"]
                for item in result.get("field_candidates") or []
                if item.get("field_type") == "metric"
            ],
            "next_action": "construct_query",
        },
        "execution_ref": {
            # 执行器要求 plan 带 query_template 才肯放行（否则视为规划未完成）。
            # 降级模板只填已确认的表与字段，不含任何日期或筛选条件——
            # 筛选值仍须 Agent 按 filter_value_policy_zh 校验权限后自行补入 payload，
            # 补入的字段会被执行器的 _assert_fields 逐个比对授权目录。
            "query_template": {
                "tableId": (result.get("dataset_candidates") or [{}])[0].get("table_id"),
                "dimensions": [
                    {"field": item["field_name"], "alias": item["field_name"]}
                    for item in result.get("field_candidates") or []
                    if item.get("field_type") == "dimension"
                ],
                "metrics": [
                    {"field": item["field_name"], "alias": item["field_name"]}
                    for item in result.get("field_candidates") or []
                    if item.get("field_type") == "metric"
                ],
                "filters": [],
                "orderBy": None,
                "limit": None,
            },
            "table_id": (result.get("dataset_candidates") or [{}])[0].get("table_id"),
            "dataset_alias": result.get("selected_dataset_alias"),
            "dimensions": [
                {"field_name": item["field_name"], "label_zh": item["verbose_name"]}
                for item in result.get("field_candidates") or []
                if item.get("field_type") == "dimension"
            ],
            "metrics": [
                {"field_name": item["field_name"], "label_zh": item["verbose_name"]}
                for item in result.get("field_candidates") or []
                if item.get("field_type") == "metric"
            ],
            "filter_components": result.get("filter_components") or [],
        },
    }
    path.write_text(
        json.dumps(plan, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：输出降级合同 JSON；失败也返回结构化结果而非裸 traceback。"""
    core.force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="用户查询原文")
    parser.add_argument("--field", action="append", default=[], help="用户点名字段，可重复")
    parser.add_argument("--dataset", default=None, help="已确认的 dataset_alias")
    parser.add_argument("--data-dir", default=None, help="指定本地数据目录")
    parser.add_argument("--emit-plan", default=None, help="把结果写成 plan 文件路径")
    parser.add_argument("--audit", action="store_true", help="巡检意图目录覆盖率，不做查询")
    args = parser.parse_args(argv)

    # 巡检模式：只读检查意图目录覆盖率与断链意图，不构造降级合同、不做任何查询
    if args.audit:
        print(
            json.dumps(
                audit_profiles(data_dir=Path(args.data_dir) if args.data_dir else None),
                ensure_ascii=False,
            )
        )
        return 0

    try:
        result = build_fallback(
            args.query,
            requested_fields=args.field,
            dataset_alias=args.dataset,
            data_dir=Path(args.data_dir) if args.data_dir else None,
        )
        if args.emit_plan and result.get("status") == "ready":
            _emit_plan(result, Path(args.emit_plan))
            result["plan_file"] = args.emit_plan
            result["execute_command"] = (
                f"python3 scripts/run_query.py --plan-file {args.emit_plan} "
                '--json \'{"tableId": <table_id>, "dimensions": [...], "metrics": [...]}\''
            )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 —— 降级入口不能再抛裸 traceback
        print(
            json.dumps(
                {
                    "contract": "local_fallback_v1",
                    "status": "error",
                    "error": str(error)[:200],
                    "next_action_zh": "降级路径本身失败：如实告知用户并停止，禁止凭猜测构造查询。",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
