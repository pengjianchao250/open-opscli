# Seller Sprite Competitor Filter Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent `competitor-lookup` from silently querying SellerSprite defaults when the user omitted all competitor filters, while allowing an explicitly confirmed default query.

**Architecture:** Keep the existing browser-context API request path. Add a declarative `required_any_params` contract to `SellerSpriteScenario`, enforce it before payload construction, and expose it through scenario metadata so Agents know to ask for missing input. A local-only `allowDefaultQuery` flag bypasses the guard after explicit user confirmation and is never copied into the SellerSprite request payload.

**Tech Stack:** Python 3.10+, dataclasses, pytest, Typer/FastMCP scenario metadata, Markdown Skill templates.

---

## File Map

- Modify `opscli/seller_sprite/api/scenarios.py`: declare and enforce the one-of parameter contract.
- Modify `opscli/seller_sprite/api/payloads.py`: map singular `asin` and resolved `category` aliases into the existing SellerSprite fields.
- Modify `tests/seller_sprite/test_payloads.py`: lock down empty, blank, valid-filter, explicit-confirmation, and metadata behavior.
- Modify `opscli/skills/templates/ops-seller-sprite/SKILL.md`: require clarification before a filterless competitor lookup.
- Modify `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`: keep MCP guidance identical to the installed Skill.
- Modify `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`: document categories as valid competitor filters and the explicit default-query confirmation.
- Modify `docs/guide/卖家精灵模块外部项目调用指南.md`: replace the inaccurate “无必填参数” entry.

### Task 1: Add Failing One-Of Contract Tests

**Files:**
- Modify: `tests/seller_sprite/test_payloads.py:14-63`
- Test: `tests/seller_sprite/test_payloads.py`

- [ ] **Step 1: Replace the filterless happy-path test with an explicit-confirmation test**

Change the existing first test so its empty query is deliberately authorized and verify the internal flag does not leak:

```python
def test_competitor_payload_allows_explicit_default_query_without_leaking_confirmation():
    scenario = get_scenario("competitor-lookup")

    payload = scenario.build_payload(
        params={"allowDefaultQuery": True},
        site="DE",
        period="2026-04",
        page_size=100,
    )

    assert payload["market"] == "DE"
    assert payload["monthName"] == "bsr_sales_monthly_202604"
    assert payload["size"] == 100
    assert payload["nodeIdPaths"] == []
    assert payload["asins"] == []
    assert "brand" not in payload
    assert "sellerName" not in payload
    assert "allowDefaultQuery" not in payload
```

- [ ] **Step 2: Add tests for missing and semantically blank filters**

Add these tests after the explicit-confirmation test:

```python
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"keyword": "   "},
        {"asins": []},
        {"nodeIdPaths": ["", "   "]},
        {"market": "US", "page": 1, "orderField": "amz_unit"},
    ],
)
def test_competitor_payload_rejects_missing_business_filters(params):
    scenario = get_scenario("competitor-lookup")

    with pytest.raises(
        SellerSpriteConfigError,
        match="查竞品需要至少提供一种筛选条件",
    ):
        scenario.build_payload(
            params=params,
            site="US",
            period="30d",
            page_size=100,
        )
```

- [ ] **Step 3: Add a parameterized test for every accepted filter alias**

```python
@pytest.mark.parametrize(
    ("field", "value", "payload_field", "expected"),
    [
        ("keyword", "flashlight", "keywords", "flashlight"),
        ("keywords", "flashlight", "keywords", "flashlight"),
        ("brand", "Anker", "brand", "Anker"),
        ("sellerName", "AnkerDirect", "sellerName", "AnkerDirect"),
        ("asin", "B00FLYWNYQ", "asins", ["B00FLYWNYQ"]),
        ("asins", ["B00FLYWNYQ"], "asins", ["B00FLYWNYQ"]),
        ("node", "3375251:375540011", "nodeIdPaths", ["3375251:375540011"]),
        ("category", "3375251:375540011", "nodeIdPaths", ["3375251:375540011"]),
        ("nodeIdPath", "3375251:375540011", "nodeIdPaths", ["3375251:375540011"]),
        ("nodeIdPaths", ["3375251:375540011"], "nodeIdPaths", ["3375251:375540011"]),
    ],
)
def test_competitor_payload_accepts_each_business_filter_alias(field, value, payload_field, expected):
    scenario = get_scenario("competitor-lookup")

    payload = scenario.build_payload(
        params={field: value},
        site="US",
        period="30d",
        page_size=100,
    )

    assert payload["market"] == "US"
    assert payload[payload_field] == expected
```

- [ ] **Step 4: Add a public metadata contract test**

```python
def test_competitor_scenario_exposes_required_any_params():
    metadata = get_scenario("competitor-lookup").to_public_dict()

    assert metadata["required_any_params"] == (
        "keyword",
        "keywords",
        "brand",
        "sellerName",
        "asin",
        "asins",
        "node",
        "category",
        "nodeIdPath",
        "nodeIdPaths",
    )
```

- [ ] **Step 5: Run the focused tests and verify they fail for the missing contract**

Run:

```powershell
uv run pytest tests/seller_sprite/test_payloads.py -k "competitor" -v
```

Expected: the new rejection tests fail because empty filters are still accepted, and the metadata test fails because `required_any_params` does not exist.

- [ ] **Step 6: Commit the red tests**

```powershell
git add tests/seller_sprite/test_payloads.py
git commit -m "test: define competitor lookup filter guard"
```

### Task 2: Enforce the Scenario Contract

**Files:**
- Modify: `opscli/seller_sprite/api/scenarios.py:24-93`
- Modify: `opscli/seller_sprite/api/payloads.py:198-221`
- Test: `tests/seller_sprite/test_payloads.py`

- [ ] **Step 1: Add the declarative one-of field to `SellerSpriteScenario`**

Add the defaulted field after `method` so existing scenario declarations remain valid:

```python
@dataclass(frozen=True)
class SellerSpriteScenario:
    """单个卖家精灵接口场景定义。"""

    scenario_id: str
    title: str
    endpoint: str
    required_params: tuple[str, ...]
    payload_builder: PayloadBuilder
    method: str = "POST"
    required_any_params: tuple[str, ...] = ()
    high_frequency_endpoint: str | None = None
    task_result_endpoint: str | None = None
```

`to_public_dict()` already uses `dataclasses.asdict`, so the new contract will automatically appear in `seller_sprite_scenarios` output.

- [ ] **Step 2: Add semantic blank-value detection**

Add this module-level helper above `SCENARIOS`:

```python
def _is_blank(value: Any) -> bool:
    """判断场景参数是否缺少可用业务值。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return not any(not _is_blank(item) for item in value)
    return False
```

This treats `0` and `False` as supplied values for general scenario compatibility, while rejecting empty strings and collections.

- [ ] **Step 3: Extend `_validate_required` with explicit-confirmation bypass**

Replace the method with:

```python
def _validate_required(self, payload: dict[str, Any]) -> None:
    """校验逐项必填参数和至少一项参数组。"""
    missing = [key for key in self.required_params if _is_blank(payload.get(key))]
    if missing:
        raise SellerSpriteConfigError(f"场景 {self.scenario_id} 缺少参数：{', '.join(missing)}")
    if payload.get("allowDefaultQuery") is True:
        return
    if self.required_any_params and not any(
        not _is_blank(payload.get(key)) for key in self.required_any_params
    ):
        choices = "、".join(self.required_any_params)
        raise SellerSpriteConfigError(
            f"查竞品需要至少提供一种筛选条件：{choices}；"
            "如需按默认条件查询全部商品，请先明确确认"
        )
```

The confirmation flag remains in the merged local input only. Existing payload builders use explicit allowlists, so it is not copied into the SellerSprite request.

- [ ] **Step 4: Declare the competitor lookup filter aliases**

Update only the `competitor-lookup` registration:

```python
"competitor-lookup": SellerSpriteScenario(
    scenario_id="competitor-lookup",
    title="选竞品",
    endpoint="/v3/api/competing-lookup",
    required_params=(),
    required_any_params=(
        "keyword",
        "keywords",
        "brand",
        "sellerName",
        "asin",
        "asins",
        "node",
        "category",
        "nodeIdPath",
        "nodeIdPaths",
    ),
    payload_builder=make_competitor_payload,
),
```

- [ ] **Step 5: Map the accepted singular ASIN and category aliases**

Update the two alias mappings in `make_competitor_payload()`:

```python
payload: dict[str, Any] = {
    "market": market,
    "monthName": input_data.get("monthName") or month_name(month),
    "asins": csv(input_data.get("asins") or input_data.get("asin")),
    "page": _int(input_data.get("page") or input_data.get("startPage"), 1),
    "nodeIdPaths": csv(
        input_data.get("node")
        or input_data.get("nodeIdPaths")
        or input_data.get("nodeIdPath")
        or input_data.get("category")
    ),
    "symbolFlag": False,
    "size": _int(input_data.get("size") or input_data.get("pageSize"), 100),
    "order": {
        "field": input_data.get("orderField") or "amz_unit",
        "desc": order_desc(input_data.get("orderDesc")),
    },
    "lowPrice": input_data.get("lowPrice") or "N",
}
```

Only these two field expressions change; retain the rest of the existing builder.

- [ ] **Step 6: Run focused tests and verify they pass**

Run:

```powershell
uv run pytest tests/seller_sprite/test_payloads.py -k "competitor or required_params" -v
```

Expected: all selected tests pass; existing `keyword-reverse` required-parameter validation remains green.

- [ ] **Step 7: Commit the implementation**

```powershell
git add opscli/seller_sprite/api/scenarios.py opscli/seller_sprite/api/payloads.py tests/seller_sprite/test_payloads.py
git commit -m "fix: guard filterless competitor lookups"
```

### Task 3: Align Agent Instructions and User Documentation

**Files:**
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL.md:39-59,73-81`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md:85-105,119-127`
- Modify: `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md:12-25`
- Modify: `docs/guide/卖家精灵模块外部项目调用指南.md:58`

- [ ] **Step 1: Correct the general missing-parameter policy in both Skill files**

Replace:

```markdown
- If a scenario has no required params, run it with defaults after mapping the intent.
```

with:

```markdown
- If a scenario has neither `required_params` nor `required_any_params`, run it with defaults after mapping the intent.
- For `competitor-lookup`, require at least one of keyword, brand, seller, ASIN/product link, or category. If all are missing, ask whether the user omitted a filter; do not call `seller_sprite_run` yet.
- Only after the user explicitly asks to query all products with defaults may the Agent call `seller_sprite_run` with `params.allowDefaultQuery=true`.
```

Apply the same text to `SKILL.md` and `SKILL_MCP.md` so installed and MCP-delivered instructions cannot diverge.

- [ ] **Step 2: Update the competitor clarification example and required-params table**

Use this clarification example in both Skill files:

```markdown
- `查竞品还缺少筛选条件。请提供关键词、品牌、卖家、ASIN/亚马逊产品链接或类目中的至少一种；也可以明确要求按默认条件查询全部商品。`
```

Change the `competitor-lookup` required cell to:

```markdown
one of `keyword`, `brand`, `sellerName`, `asins`, product link, `node` / `category`; or explicit `allowDefaultQuery=true` after user confirmation
```

- [ ] **Step 3: Correct the Chinese parameter reference**

Replace the competitor section in `SCENARIO_PARAMS_ZH.md` with:

```markdown
## 查竞品 `competitor-lookup`

必填，任选一种：

- `keyword` / `keywords`：关键词
- `brand`：品牌名
- `sellerName`：卖家名称
- `asin` / `asins`：ASIN 或 ASIN 列表
- Amazon 商品链接：Agent 从链接提取 ASIN 后传入 `asins`
- `node` / `category` / `nodeIdPath` / `nodeIdPaths`：类目名称、完整类目路径或节点 ID 路径

如果用户没有提供上述条件，先询问是否遗漏。仅当用户明确要求按默认条件查询全部商品时，传 `allowDefaultQuery=true`；该字段只用于本地确认，不会发送给卖家精灵。
```

- [ ] **Step 4: Correct the external-project guide table**

Replace the `competitor-lookup` row with:

```markdown
| `competitor-lookup` | 竞品查询 | `keyword`、`brand`、`sellerName`、`asin(s)`、类目任选一种；明确默认全量查询时传 `allowDefaultQuery=true` | `node`、`orderField` |
```

- [ ] **Step 5: Verify documentation consistency**

Run:

```powershell
rg -n "If a scenario has no required params|竞品查询 \| 无|查竞品需要 keyword" opscli/skills/templates/ops-seller-sprite docs/guide/卖家精灵模块外部项目调用指南.md
```

Expected: no output.

Run:

```powershell
rg -n "required_any_params|allowDefaultQuery|查竞品还缺少筛选条件" opscli/skills/templates/ops-seller-sprite docs/guide/卖家精灵模块外部项目调用指南.md
```

Expected: both Skill files describe the same guard, and the Chinese reference plus external guide document the explicit confirmation path.

- [ ] **Step 6: Commit the documentation contract**

```powershell
git add opscli/skills/templates/ops-seller-sprite/SKILL.md opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md docs/guide/卖家精灵模块外部项目调用指南.md
git commit -m "docs: require competitor lookup filters"
```

### Task 4: Run Regression Verification

**Files:**
- Verify: `opscli/seller_sprite/api/scenarios.py`
- Verify: `opscli/seller_sprite/api/payloads.py`
- Verify: `tests/seller_sprite/`
- Verify: SellerSprite Skill and guide files from Task 3

- [ ] **Step 1: Run the complete SellerSprite test suite**

```powershell
uv run pytest tests/seller_sprite -q
```

Expected: all SellerSprite tests pass.

- [ ] **Step 2: Run formatting and lint checks on changed Python files**

```powershell
uv run ruff check opscli/seller_sprite/api/scenarios.py opscli/seller_sprite/api/payloads.py tests/seller_sprite/test_payloads.py
```

Expected: no lint errors.

- [ ] **Step 3: Verify whitespace and inspect the final diff**

```powershell
git diff --check
git diff -- opscli/seller_sprite/api/scenarios.py opscli/seller_sprite/api/payloads.py tests/seller_sprite/test_payloads.py opscli/skills/templates/ops-seller-sprite/SKILL.md opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md docs/guide/卖家精灵模块外部项目调用指南.md
```

Expected: `git diff --check` is silent; the diff contains only the filter guard, tests, and matching documentation changes.

- [ ] **Step 4: Perform a final behavior audit**

Confirm from tests and diff:

```text
1. Empty competitor filters fail before any browser/API call.
2. Site, period, pagination, and sorting do not count as competitor filters.
3. Keyword, brand, seller, ASIN, or category each satisfy the contract.
4. Explicit allowDefaultQuery=true permits a default query.
5. allowDefaultQuery is absent from the SellerSprite payload.
6. Other SellerSprite scenarios retain their existing behavior.
```

- [ ] **Step 5: Commit any verification-only fixes if required**

If verification required code or documentation corrections, stage only those files and commit:

```powershell
git add opscli/seller_sprite/api/scenarios.py opscli/seller_sprite/api/payloads.py tests/seller_sprite/test_payloads.py opscli/skills/templates/ops-seller-sprite/SKILL.md opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md docs/guide/卖家精灵模块外部项目调用指南.md
git commit -m "test: verify competitor lookup filter guard"
```

If no corrections were needed, do not create an empty commit.
