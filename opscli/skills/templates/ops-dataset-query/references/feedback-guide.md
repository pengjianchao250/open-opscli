---
name: ops-dataset-query-feedback
description: 查询闭环反馈规范 — ops-feedback 调用方式、参数模板与示例
---

# 查询闭环：调用 ops-feedback 提交反馈

> **铁律十一的执行入口**：每次查询完成后，通过 `ops-feedback` Skill 提交结果反馈，形成闭环。

## 何时触发

| 触发场景 | 必须提交 |
|---------|---------|
| 查询成功，有数据返回 | 是 |
| 查询成功，返回 0 行 | 是 |
| 查询失败（报错、超时等） | 是（失败尤其重要） |
| dry_run 模式（仅验证） | 否，可跳过 |

## MCP 模式调用方式

> **`feedback_type` 可选值**：`bug` / `feature` / `data_issue` / `ux` / `docs` / `query_result` / `other`
> 查询场景固定使用 `query_result`；发现数据问题时改用 `data_issue`；功能建议用 `feature`。

### 成功场景

```python
feedback_submit(
    feedback_type="query_result",
    title="广告数据查询 - ACOS趋势分析（table_id=15）",
    content="查询成功，返回 20 行。ACOS 范围 12%~35%，各部门数据正常。",
    source="mcp",
    payload={
        "actual": "查询返回 20 行，ACOS 范围 12%~35%",
        "expected": "按部门统计广告 ACOS 趋势，近30天数据"
    },
    execution_summary={
        "summary": "通过 query_simple 查询 advertising_list_set（table_id=15），按部门维度统计 ACOS，近30天数据正常返回。",
        "successful_calls": [
            {"tool": "query_simple", "result": "success, 20 rows, 1348ms"}
        ],
        "failed_calls": [],
        "final_resolution": "查询成功，已将 ACOS 趋势数据输出给用户。"
    }
)
```

### 降级场景 — 查询执行成功但结果不符合预期

```python
feedback_submit(
    feedback_type="query_result",
    severity="medium",
    title="广告数据-dataComparison对比列缺失（table_id=15）",
    content="dataComparison 参数传入成功但对比列未返回，最终通过两次独立查询手动完成对比。",
    source="mcp",
    payload={
        "actual": "返回结果缺少 last_f_spend/diff_f_spend/pct_f_spend 等对比列",
        "expected": "传入 data_comparison 参数后应返回 last_*/diff_*/pct_* 对比列"
    },
    execution_summary={
        "summary": "通过 query_simple 查询 advertising_list_set（table_id=15），使用 dataComparison 进行2月 vs 1月对比，对比列未返回，最终两次独立查询手动完成。",
        "failed_calls": [
            {
                "tool": "query_simple",
                "reason": "推测：table_id=15 为 sql 类型数据集，dataComparison 逻辑未正确拼接到子查询 SQL 中",
                "call_params": {
                    "table_id": 15,
                    "filters": [{"field": "date_id", "operator": "between", "value": ["2026-02-01", "2026-02-28"]}],
                    "data_comparison": {"field": "date_id", "startDate": "2026-01-01", "endDate": "2026-01-31"}
                },
                "error_message": "无报错，但返回结果缺少 last_*/diff_*/pct_* 对比列",
                "fix_suggestion": "检查 SimpleQueryBuilder 对 sql 类型数据集的 dataComparison 处理逻辑；临时方案：分别查询两时间段在客户端合并对比"
            }
        ],
        "successful_calls": [
            {"tool": "query_simple（2月数据）", "result": "success, 2 rows, 1205ms"},
            {"tool": "query_simple（1月数据）", "result": "success, 2 rows, 1348ms"}
        ],
        "final_resolution": "通过分别查询1月和2月数据，在客户端手动完成环比计算和对比分析。"
    }
)
```

### 工具报错场景 — 查询工具抛出异常/返回 success=false

```python
feedback_submit(
    feedback_type="bug",
    severity="medium",
    title="query_simple 查询失败 - QS-EXE-005（table_id=1）",
    content="缺少主周期 filters 导致 QS-EXE-005 报错，补上日期条件后重试成功。",
    source="mcp",
    payload={
        "actual": "QS-EXE-005 missing ')' at '{'",
        "expected": "query_simple 正常返回数据"
    },
    execution_summary={
        "summary": "调用 query_simple 时未传主周期日期 filters，触发 QS-EXE-005 SQL 解析错误。",
        "failed_calls": [
            {
                "tool": "query_simple",
                "call_params": {"table_id": 1, "data_comparison": {"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"}},
                "error_message": "QS-EXE-005: missing ')' at '{'",
                "reason": "缺少主周期日期 filters，dataComparison 单独传入导致 SQL 解析失败",
                "fix_suggestion": "补上 filters 主周期日期后重试"
            }
        ],
        "successful_calls": [{"tool": "query_simple（补上 filters 后）", "result": "success, 10 rows, 980ms"}],
        "final_resolution": "补上主周期日期 filters 后重试成功，结果已返回用户。"
    }
)
```

## CLI 模式调用方式

```bash
# 成功场景
opscli feedback submit \
  --feedback-type query_result \
  --title "广告数据-ACOS趋势查询（table_id=15）" \
  --content "查询成功，返回 20 行，ACOS 范围 12%~35%" \
  --source cli \
  --payload '{"actual":"返回20行，ACOS范围12%~35%","expected":"按部门统计广告ACOS趋势，近30天数据"}' \
  --execution-summary '{"summary":"通过opscli query simple查询table_id=15，成功返回20行","successful_calls":[{"tool":"opscli query simple","result":"success, 20 rows"}],"failed_calls":[],"final_resolution":"查询成功"}'

# 失败 / 降级场景
opscli feedback submit \
  --feedback-type query_result \
  --severity medium \
  --title "广告数据-dataComparison对比列缺失" \
  --content "dataComparison参数传入成功但对比列未返回，已通过两次查询手动完成对比" \
  --source cli \
  --payload '{"actual":"返回结果缺少last_*/diff_*/pct_*对比列","expected":"传入data_comparison后应返回对比列"}' \
  --execution-summary '{"summary":"opscli query simple传入dataComparison参数，对比列未返回，最终两次查询手动完成","failed_calls":[{"tool":"opscli query simple","error_message":"无报错但缺少对比列","fix_suggestion":"检查SimpleQueryBuilder对sql类型数据集的dataComparison处理逻辑"}],"successful_calls":[{"tool":"opscli query simple（2月）","result":"success, 2 rows"},{"tool":"opscli query simple（1月）","result":"success, 2 rows"}],"final_resolution":"两次独立查询手动完成对比"}'
```

## ops-feedback Skill 详细用法

如需了解 `ops-feedback` Skill 的完整参数、错误处理和高级用法，直接调用该 Skill：

```
/oh-my-claudecode:ops-feedback
```

或在任务中直接触发：`ops-feedback submit`。
