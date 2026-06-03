# ops-dataset-query 二期客户端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将结构化产物落地到 Skill data/ 目录，新增本地意图路由脚本，强化 SKILL.md / rules.md 规则，使 opscli 在 Catalog 未命中时能进行本地语义路由而非直接跌落到关键词搜索。

**Architecture:** 在现有 `scripts/` 目录新增 `route_intent.py`，读取 `data/intent_taxonomy.yml` + `data/dataset_profiles.yml` 做本地意图评分，输出标准 JSON；SKILL.md 铁律三-B 描述四层回退链，`references/rules.md` 零-A 章节补充字段语义解析流程。

**Tech Stack:** Python 3.10+，pyyaml>=6，pytest，PyPI opscli 模板文件

---

## 文件变更一览

| 动作 | 路径 | 说明 |
|------|------|------|
| 新增（复制） | `opscli/skills/templates/ops-dataset-query/data/intent_taxonomy.yml` | 草案目录落地 |
| 新增（复制） | `opscli/skills/templates/ops-dataset-query/data/dataset_profiles.yml` | 草案目录落地 |
| 新增（复制） | `opscli/skills/templates/ops-dataset-query/data/dataset_relationships.yml` | 草案目录落地 |
| 新增（复制） | `opscli/skills/templates/ops-dataset-query/data/field_semantic_index.yml` | 草案目录落地 |
| 新增（复制） | `opscli/skills/templates/ops-dataset-query/data/routing_eval_cases.yml` | 草案目录落地 |
| 新增（复制） | `opscli/skills/templates/ops-dataset-query/data/query_plan.schema.json` | 草案目录落地 |
| 修改 | `opscli/skills/templates/ops-dataset-query/data/VERSION.json` | 升版 + data_state=ready |
| 修改 | `pyproject.toml` | 新增 pyyaml>=6 依赖 |
| 新增 | `opscli/skills/templates/ops-dataset-query/scripts/route_intent.py` | 本地意图路由脚本 |
| 新增 | `tests/skills/test_route_intent.py` | route_intent 单元测试 |
| 修改 | `opscli/skills/templates/ops-dataset-query/SKILL.md` | 补充铁律三-B |
| 修改 | `opscli/skills/templates/ops-dataset-query/references/rules.md` | 补充零-A章节 |

---

## 环境准备

```bash
cd /Users/mask/python3/opscli
source .venv/bin/activate
SKIP_CYTHON=1 uv pip install -e ".[dev]"
```

---

## Task 1：落地结构化产物文件 + 升级 VERSION.json

**Files:**
- Create: `opscli/skills/templates/ops-dataset-query/data/intent_taxonomy.yml`
- Create: `opscli/skills/templates/ops-dataset-query/data/dataset_profiles.yml`
- Create: `opscli/skills/templates/ops-dataset-query/data/dataset_relationships.yml`
- Create: `opscli/skills/templates/ops-dataset-query/data/field_semantic_index.yml`
- Create: `opscli/skills/templates/ops-dataset-query/data/routing_eval_cases.yml`
- Create: `opscli/skills/templates/ops-dataset-query/data/query_plan.schema.json`
- Modify: `opscli/skills/templates/ops-dataset-query/data/VERSION.json`

- [ ] **Step 1: 复制 6 个结构化产物文件**

草案目录：`/Users/mask/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/4620F86B8673508337E9D3163224589C/Caches/Files/2026-05/d6801ef6ea1f75773dbb464cc5a4030a/ops-dataset-query-structured-artifacts/`

```bash
ARTIFACTS="/Users/mask/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/4620F86B8673508337E9D3163224589C/Caches/Files/2026-05/d6801ef6ea1f75773dbb464cc5a4030a/ops-dataset-query-structured-artifacts"
DATA_DIR="opscli/skills/templates/ops-dataset-query/data"

cp "$ARTIFACTS/intent_taxonomy.yml"       "$DATA_DIR/intent_taxonomy.yml"
cp "$ARTIFACTS/dataset_profiles.yml"      "$DATA_DIR/dataset_profiles.yml"
cp "$ARTIFACTS/dataset_relationships.yml" "$DATA_DIR/dataset_relationships.yml"
cp "$ARTIFACTS/field_semantic_index.yml"  "$DATA_DIR/field_semantic_index.yml"
cp "$ARTIFACTS/routing_eval_cases.yml"    "$DATA_DIR/routing_eval_cases.yml"
cp "$ARTIFACTS/query_plan.schema.json"    "$DATA_DIR/query_plan.schema.json"
```

- [ ] **Step 2: 验证文件已复制**

```bash
ls -la opscli/skills/templates/ops-dataset-query/data/
```
期望输出包含：`intent_taxonomy.yml`、`dataset_profiles.yml`、`dataset_relationships.yml`、`field_semantic_index.yml`、`routing_eval_cases.yml`、`query_plan.schema.json`

- [ ] **Step 3: 更新 VERSION.json**

将 `opscli/skills/templates/ops-dataset-query/data/VERSION.json` 改为：

```json
{
  "name": "ops-dataset-query",
  "version": "1.1.0",
  "data_state": "ready"
}
```

- [ ] **Step 4: 验证 data_state**

```bash
python3 -c "import json; d=json.load(open('opscli/skills/templates/ops-dataset-query/data/VERSION.json')); assert d['data_state']=='ready' and d['version']=='1.1.0'; print('OK')"
```
期望输出：`OK`

- [ ] **Step 5: Commit**

```bash
git add opscli/skills/templates/ops-dataset-query/data/
git commit -m "feat(ops-dataset-query): 落地结构化产物文件，升版 1.1.0 data_state=ready"
```

---

## Task 2：新增 pyyaml 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 在 pyproject.toml 的 dependencies 列表中添加 pyyaml**

在 `pyproject.toml` 的 `[project]` `dependencies` 列表尾部添加：

```toml
"pyyaml>=6",
```

完整位置示例（添加在 `"rich>=13",` 后）：

```toml
dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "cryptography>=38",
    "rich>=13",
    "keyring>=25",
    "pyyaml>=6",
]
```

- [ ] **Step 2: 重新安装依赖**

```bash
SKIP_CYTHON=1 uv pip install -e ".[dev]"
```

- [ ] **Step 3: 验证 pyyaml 可导入**

```bash
python3 -c "import yaml; print('pyyaml OK, version:', yaml.__version__)"
```
期望输出：`pyyaml OK, version: 6.x.x`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: 新增 pyyaml>=6 依赖（供 route_intent.py 加载 YAML 数据文件）"
```

---

## Task 3：创建 `scripts/route_intent.py`

**Files:**
- Create: `opscli/skills/templates/ops-dataset-query/scripts/route_intent.py`

- [ ] **Step 1: 创建脚本文件**

```python
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
```

- [ ] **Step 2: 手动冒烟测试（需先完成 Task 1）**

```bash
cd opscli/skills/templates/ops-dataset-query
python scripts/route_intent.py "近30天各部门销售额" --top-n 3
```
期望：top_results[0].intent_id == "billing_sales_review"，routing_status == "direct_intent"

```bash
python scripts/route_intent.py "今日实时销售监控"
```
期望：出现 routing_status == "embedded_intent" 的结果，execution_alias 不为 null

```bash
python scripts/route_intent.py "今天天气怎么样"
```
期望：fallback_needed == true 或 top_results 为空

---

## Task 4：为 route_intent.py 编写测试

**Files:**
- Create: `tests/skills/test_route_intent.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/skills/test_route_intent.py`：

```python
"""route_intent.py 的单元测试。

route_intent.py 是一个独立脚本，通过将 scripts 目录插入 sys.path 来导入。
测试依赖 data/ 目录中已落地的 intent_taxonomy.yml 和 dataset_profiles.yml（Task 1 完成后才能通过）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# 脚本所在目录（绝对路径）
SKILL_ROOT = (
    Path(__file__).parent.parent.parent
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
DATA_DIR = SKILL_ROOT / "data"

# 将 scripts/ 加入 sys.path，以便直接 import route_intent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import route_intent  # noqa: E402  — 必须在 sys.path 修改之后导入


@pytest.fixture(scope="module")
def check_data_ready():
    """确保 data_state=ready，否则跳过所有依赖数据文件的测试。"""
    version_file = DATA_DIR / "VERSION.json"
    if not version_file.exists():
        pytest.skip("VERSION.json 不存在，请先完成 Task 1")
    data = json.loads(version_file.read_text(encoding="utf-8"))
    if data.get("data_state") != "ready":
        pytest.skip("data_state 不是 ready，请先完成 Task 1")


# ──────────────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────────────

def _route(query: str, top_n: int = 3) -> dict:
    return route_intent.route(query, data_dir=DATA_DIR, top_n=top_n)


# ──────────────────────────────────────────────────────────────────────────────
# 测试：账单销售意图
# ──────────────────────────────────────────────────────────────────────────────

def test_billing_sales_top1(check_data_ready):
    """账单销售关键词组合应命中 billing_sales_review 意图。"""
    result = _route("近30天各部门销售额")
    top = result["top_results"]
    assert len(top) > 0, "应至少返回一个候选"
    assert top[0]["intent_id"] == "billing_sales_review"


def test_billing_sales_is_direct_intent(check_data_ready):
    """billing_sales_review 路由模式应为 direct_intent。"""
    result = _route("月度销售复盘趋势分析")
    ids = [r["intent_id"] for r in result["top_results"]]
    assert "billing_sales_review" in ids
    billing = next(r for r in result["top_results"] if r["intent_id"] == "billing_sales_review")
    assert billing["routing_status"] == "direct_intent"
    assert billing["execution_alias"] is not None


# ──────────────────────────────────────────────────────────────────────────────
# 测试：即时销售 embedded_intent 映射
# ──────────────────────────────────────────────────────────────────────────────

def test_realtime_sales_embedded_intent(check_data_ready):
    """即时销售应映射到即时综合数据集（embedded_intent）。"""
    result = _route("今日实时销售监控")
    realtime = next(
        (r for r in result["top_results"] if r["intent_id"] == "realtime_sales_monitoring"),
        None,
    )
    assert realtime is not None, "应命中 realtime_sales_monitoring 意图"
    assert realtime["routing_status"] == "embedded_intent"
    assert realtime["execution_alias"] is not None, "embedded_intent 必须有 execution_alias"
    # 实际执行数据集不应是即时销售数据集本身（其无独立入口）
    assert realtime["execution_dataset"] != realtime["primary_dataset"]


# ──────────────────────────────────────────────────────────────────────────────
# 测试：澄清触发
# ──────────────────────────────────────────────────────────────────────────────

def test_sp_word_requires_clarification(check_data_ready):
    """SP词组分析应触发澄清（SP广告数据集不含搜索词/关键词）。"""
    result = _route("SP词组分析近30天效果")
    # 应命中某个广告相关意图
    assert not result["fallback_needed"], "应找到至少一个候选意图"
    # 至少有一个候选触发了澄清
    any_clarification = any(r["requires_clarification"] for r in result["top_results"])
    assert any_clarification, "SP词组相关查询应触发至少一次澄清"


# ──────────────────────────────────────────────────────────────────────────────
# 测试：无关输入回退
# ──────────────────────────────────────────────────────────────────────────────

def test_unrelated_query_fallback(check_data_ready):
    """完全无关的输入应返回 fallback_needed=True 或空结果。"""
    result = _route("今天天气怎么样")
    assert result["fallback_needed"] is True or len(result["top_results"]) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 测试：top_n 限制
# ──────────────────────────────────────────────────────────────────────────────

def test_top_n_limits_results(check_data_ready):
    """top_n 参数应严格限制返回数量。"""
    result = _route("销售广告数据", top_n=1)
    assert len(result["top_results"]) <= 1


def test_top_n_default_three(check_data_ready):
    """默认 top_n=3，结果不超过 3 个。"""
    result = _route("广告ACOS分析")
    assert len(result["top_results"]) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# 测试：返回字段完整性
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_KEYS = {
    "intent_id",
    "intent_name",
    "primary_dataset",
    "execution_dataset",
    "execution_alias",
    "table_id",
    "confidence",
    "matched_keywords",
    "routing_status",
    "requires_clarification",
    "clarification_reasons",
    "avoid_when",
    "hard_constraints",
}


def test_result_has_required_fields(check_data_ready):
    """每个候选结果必须包含所有约定字段。"""
    result = _route("广告费ACOS分析")
    for item in result["top_results"]:
        missing = REQUIRED_KEYS - set(item.keys())
        assert not missing, f"结果缺少字段: {missing}"


def test_confidence_in_range(check_data_ready):
    """confidence 必须在 [0.0, 1.0] 范围内。"""
    result = _route("销售额趋势")
    for item in result["top_results"]:
        assert 0.0 <= item["confidence"] <= 1.0, f"confidence 超出范围: {item['confidence']}"


def test_routing_status_valid_values(check_data_ready):
    """routing_status 只能是 direct_intent 或 embedded_intent。"""
    result = _route("综合运营销售广告库存")
    valid = {"direct_intent", "embedded_intent"}
    for item in result["top_results"]:
        assert item["routing_status"] in valid


# ──────────────────────────────────────────────────────────────────────────────
# 测试：CLI 接口（通过 subprocess 调用，验证主入口正常）
# ──────────────────────────────────────────────────────────────────────────────

def test_cli_entrypoint_returns_json(check_data_ready):
    """命令行入口应输出合法 JSON。"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "route_intent.py"), "近30天各部门销售额"],
        capture_output=True,
        text=True,
        cwd=str(SKILL_ROOT),
    )
    assert result.returncode == 0, f"脚本退出码非0: {result.stderr}"
    data = json.loads(result.stdout)
    assert "top_results" in data
    assert "fallback_needed" in data
```

- [ ] **Step 2: 运行测试，确认失败（Task 3 完成之前可能会有导入错误，Task 1 完成后跳过数据依赖测试）**

```bash
pytest tests/skills/test_route_intent.py -v 2>&1 | head -40
```
期望：导入 `route_intent` 成功（Task 3 已完成），所有数据依赖测试通过（Task 1 已完成）

- [ ] **Step 3: 确认全部通过**

```bash
pytest tests/skills/test_route_intent.py -v
```
期望输出（关键通过项）：
```
PASSED tests/skills/test_route_intent.py::test_billing_sales_top1
PASSED tests/skills/test_route_intent.py::test_billing_sales_is_direct_intent
PASSED tests/skills/test_route_intent.py::test_realtime_sales_embedded_intent
PASSED tests/skills/test_route_intent.py::test_result_has_required_fields
PASSED tests/skills/test_route_intent.py::test_cli_entrypoint_returns_json
```

- [ ] **Step 4: Commit**

```bash
git add tests/skills/test_route_intent.py
git commit -m "test(ops-dataset-query): 新增 route_intent.py 单元测试"
```

---

## Task 5：Commit route_intent.py

- [ ] **Step 1: Commit 脚本**

```bash
git add opscli/skills/templates/ops-dataset-query/scripts/route_intent.py
git commit -m "feat(ops-dataset-query): 新增 route_intent.py 本地意图路由脚本"
```

---

## Task 6：更新 SKILL.md — 补充铁律三-B

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/SKILL.md`

- [ ] **Step 1: 在铁律三（Catalog 意图匹配）后插入铁律三-B**

在 `SKILL.md` 的"### 铁律三：Catalog 意图匹配"段落下方，找到铁律三最后一行（`catalog_not_available` 部分结尾或铁律三-A 结尾），插入以下内容：

```markdown
### 铁律三-B：Catalog 未命中完整回退链

远端 Catalog 未命中时，按以下顺序回退，**禁止直接跳到 search.py**：

```
1. 远端 catalog (query_intent_match / opscli query intent) → 命中 → 遵循 intent_constraints
   ↓ 未命中（静默，不向用户提示）
2. 本地 intent_taxonomy.yml 关键词匹配：
   CLI 模式：python scripts/route_intent.py "<用户问题>"
     → 命中 direct_intent → 正常路由到 table_id / dataset_alias
     → 命中 embedded_intent → 使用 execution_alias 执行，向用户说明口径映射
     → 命中 requires_clarification=true → 先用 AskUserQuestion 澄清，禁止直接执行查询
   ↓ 未命中（fallback_needed=true）
3. search.py 本地关键词搜索（现有逻辑）
   → 匹配到 1 个 → AskUserQuestion 确认后执行
   → 匹配到 ≥2 个 → AskUserQuestion 列出候选
   → 匹配到 0 个 → 提示无匹配，询问是否查看全量数据集列表
```

**embedded_intent 执行说明**：若 `routing_status=embedded_intent`，使用 `execution_alias` 和 `table_id` 构造查询，并向用户说明实际使用的数据集及其口径差异（如"即时销售意图实际使用即时综合数据集中的 order_sale_trend_set 销售口径，以订单下单时间统计"）。
```

- [ ] **Step 2: 运行现有 Skill 相关测试确认无破坏**

```bash
pytest tests/skills/ -v -x
```
期望：全部通过

- [ ] **Step 3: Commit**

```bash
git add opscli/skills/templates/ops-dataset-query/SKILL.md
git commit -m "docs(ops-dataset-query): SKILL.md 补充铁律三-B 本地路由回退链"
```

---

## Task 7：更新 rules.md — 补充零-A 字段语义解析流程

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/references/rules.md`

- [ ] **Step 1: 在"零、AskUserQuestion 结构化澄清总则"后插入零-A 章节**

在 `references/rules.md` 的第零章（`## 零、AskUserQuestion 结构化澄清总则`）的 `### 0.2 候选展示规则` 小节结尾后，追加以下内容：

```markdown
---

## 零-A、字段语义解析流程（强制）

> **适用时机**：用户给出字段名称或业务术语（如"库存"、"销售额"、"SP"、"转化率"）时，在构造查询参数前必须执行本流程。

**解析顺序（严格按序）**：

1. **先查 `data/field_semantic_index.yml` 的 `semantic_groups`**
   - 按 `business_domain` 过滤候选字段（不只做字段名关键词匹配）
   - 查 `disambiguation.possible_meanings`：若存在多个含义且无法从上下文判断 → 执行步骤 2

2. **多义词触发 AskUserQuestion**
   - 命中 `disambiguation` 且含义数 ≥ 2 → 按 `disambiguation.possible_meanings` 列出选项，禁止猜测

3. **标记字段特殊属性**
   - `formula_rule=true`（ACOS/ROAS/转化率/平均CPC 等）→ 构造查询时**不传 `aggregation` 参数**，使用字段的 `summary_expression`
   - `snapshot_rule=true`（总库存/海外仓库存/在途库存等）→ 只能用于明细表，禁止在有维度分组的聚合查询中使用

4. **校验字段真实存在**
   - 语义索引只提供候选推荐，仍需通过 `data/dataset_fields.csv`（CLI）或 `query_metadata(dataset=alias)`（MCP）确认字段真实存在

**高风险多义词快查**（必须澄清，不可猜测）：

| 术语 | 可能含义 | 处理 |
|------|---------|------|
| SP | SPU 产品编码 / Sponsored Products 广告 | 广告上下文→SP广告；销售上下文→SPU；不明确→澄清 |
| 销售额 | 账单销售额 / 即时销售额 / 广告销售额 / 总销售额 | 先判断时间口径和平台，再确认数据集 |
| 库存 | 物控库存 / 快照库存（聚合受限）/ 补货计划 / 库龄 | 必须澄清库存类型 |
| 转化率 | 广告转化率（CVR）/ 自然转化率（页面转化率）| 确认口径来源 |
| 部门 | 销售部门（dept_name）/ 物控组织（org_name）| 看数据集类型 |
```

- [ ] **Step 2: 验证文件格式正常**

```bash
python3 -c "
import re, pathlib
content = pathlib.Path('opscli/skills/templates/ops-dataset-query/references/rules.md').read_text()
assert '零-A' in content, '零-A 章节未找到'
assert 'formula_rule' in content, 'formula_rule 标记未找到'
assert 'snapshot_rule' in content, 'snapshot_rule 标记未找到'
print('OK')
"
```
期望输出：`OK`

- [ ] **Step 3: Commit**

```bash
git add opscli/skills/templates/ops-dataset-query/references/rules.md
git commit -m "docs(ops-dataset-query): rules.md 补充零-A字段语义解析流程"
```

---

## Task 8：全量测试验证

- [ ] **Step 1: 运行所有测试**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
期望：所有测试通过，无新增失败

- [ ] **Step 2: 运行 opscli skills list 确认版本**

```bash
opscli skills list
```
期望输出包含：`ops-dataset-query ... 1.1.0 ... ready`

- [ ] **Step 3: 路由回归冒烟（验证 3 个典型用例）**

```bash
cd opscli/skills/templates/ops-dataset-query

# 用例1：账单销售（direct_intent）
python scripts/route_intent.py "季度销售复盘"
# 期望：top1 intent_id=billing_sales_review，routing_status=direct_intent

# 用例2：即时销售（embedded_intent）
python scripts/route_intent.py "今日大促实时销售异常"
# 期望：出现 realtime_sales_monitoring，routing_status=embedded_intent

# 用例3：SP广告（无澄清）
python scripts/route_intent.py "SP广告活动ACOS分析"
# 期望：命中 amazon_sp_ads_detail，requires_clarification=false
```

- [ ] **Step 4: 最终 Commit（如有残留未提交文件）**

```bash
git status
# 确认无未提交文件
```

---

## 验收标准

| 项目 | 验证方式 | 期望 |
|------|---------|------|
| data/ 文件完整 | `ls opscli/skills/templates/ops-dataset-query/data/` | 包含 6 个新文件 |
| data_state=ready | `opscli skills list` | 显示 1.1.0 ready |
| pyyaml 可用 | `python3 -c "import yaml"` | 无报错 |
| route_intent.py CLI | `python scripts/route_intent.py "..."` | 输出合法 JSON |
| 账单销售路由 | route_intent.py 输出 | top1=billing_sales_review |
| embedded_intent 映射 | route_intent.py 输出 | execution_alias≠null，routing_status=embedded_intent |
| 单元测试全通过 | `pytest tests/skills/test_route_intent.py -v` | 全部 PASSED |
| 全量测试无破坏 | `pytest tests/ -v` | 无新增 FAIL |
