# ASIN 爬虫多站点取数实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `crawler-details` 在 CLI、MCP 和类目 Top10 链路中始终携带 `country`，并支持批量 ASIN 按站点分组请求后合并。

**Architecture:** 在 `AsinBiReportDataClient` 内增加 `crawler_details` 专用获取方法，统一消费现有 `site_by_asin/default_site`。入口层不新增参数；CLI、MCP 和 Top10 继续传递现有站点信息并复用统一实现。

**Tech Stack:** Python 3.10+、httpx、Typer、FastMCP、pytest。

## Global Constraints

- 未提供站点时 `country` 必须为 `US`。
- 多站点按标准化 `country` 分组，不允许一个 ASIN 出现在错误站点请求中。
- 保持 `crawler_details.rows` 为统一数组，不能新增破坏性嵌套。
- 部分站点失败时保留成功数据并返回 `country_errors`。
- 不修改卖家精灵、Rufus、listing_basic 或其他 BI 数据源。
- Python 新增注释和公开方法 docstring 使用中文。

---

### Task 1: crawler-details 按站点分组请求与合并

**Files:**
- Modify: `opscli/asin_data/services/bi_report_data.py`
- Test: `tests/asin_data/test_bi_report_data.py`

**Interfaces:**
- Consumes: `AsinBiReportDataClient.fetch(asins, site_by_asin, default_site)` 和 `_site_code_for_asin()`。
- Produces: `AsinBiReportDataClient._fetch_crawler_details_source(...) -> dict[str, Any]`，返回兼容现有 source 的 `status/rows/raw`，并在失败时增加 `country_errors`。

- [x] **Step 1: 更新现有默认站点断言并新增多站点失败测试**

在 `test_bi_report_data_client_fetches_all_sources_and_filters_by_asin` 中把爬虫请求断言改为：

```python
assert crawler_call["params"] == {
    "asins": "B0TEST1234,B0OTHER123",
    "country": "US",
}
```

新增测试，使用 `site_by_asin={"B0TEST5678": "CA"}`，断言请求拆成：

```python
[
    {"asins": "B0TEST1234,B0TEST9999", "country": "US"},
    {"asins": "B0TEST5678", "country": "CA"},
]
```

同时断言合并 source：

```python
assert source["status"] == "success"
assert [row["asin"] for row in source["rows"]] == [
    "B0TEST1234",
    "B0TEST9999",
    "B0TEST5678",
]
assert set(source["raw"]) == {"US", "CA"}
```

新增部分失败和全部失败测试。部分失败断言 `status == "partial"`、成功 `rows` 保留、`country_errors["CA"]` 存在；全部失败断言 `status == "failed"` 且 `rows == []`。

- [x] **Step 2: 运行测试确认旧实现失败**

Run:

```powershell
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/asin_data/test_bi_report_data.py -k "crawler or fetches_all_sources" -q
```

Expected: FAIL，旧实现缺少 `country` 且不会按站点拆分。

- [x] **Step 3: 实现最小分组与合并逻辑**

在 `_fetch_source()` 的 `sp_search_term` 分支前增加：

```python
if key == "crawler_details":
    return self._fetch_crawler_details_source(
        key=key,
        config=config,
        asins=asins,
        headers=headers,
        cookies=cookies,
        site_by_asin=site_by_asin,
        default_site=default_site,
    )
```

新增私有方法，按 country 分组后使用最多 4 个线程并发请求。每组请求固定参数：

```python
params = {
    "asins": ",".join(country_asins),
    "country": country,
}
```

每组成功时用 `parse_remote_response()` 和 `extract_rows()` 解析；失败时用 `_error_dict()` 写入 `country_errors`。最终状态计算：

```python
if not country_errors:
    status = "success"
elif rows:
    status = "partial"
else:
    status = "failed"
```

返回结构必须包含：

```python
{
    "key": key,
    "label": config["label"],
    "endpoint": config["endpoint"],
    "status": status,
    "row_count": len(rows),
    "rows": rows,
    "raw": raw_by_country,
    "country_errors": country_errors,
}
```

- [x] **Step 4: 运行定向测试确认通过**

Run:

```powershell
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/asin_data/test_bi_report_data.py -k "crawler or fetches_all_sources" -q
```

Expected: PASS。

- [x] **Step 5: 提交统一客户端实现**

```powershell
git add opscli/asin_data/services/bi_report_data.py tests/asin_data/test_bi_report_data.py
git commit -m "feat: add crawler country grouping"
```

### Task 2: Top10 与 MCP 站点链路回归

**Files:**
- Modify: `opscli/mcp/tools/asin_data.py`
- Test: `tests/asin_data/test_category_top.py`
- Test: `tests/mcp/test_asin_data_tools.py`
- Modify: `docs/change-log-pending.md`

**Interfaces:**
- Consumes: MCP 现有 `site` 参数、Top10 现有 `_site_by_asin()` 和统一 BI 客户端。
- Produces: 对外参数不变；MCP docstring 明确 `site` 同时作为爬虫 `country` 默认值，Top10 继续输出兼容的 `crawler_details` dataset。

- [x] **Step 1: 增加 Top10 站点映射回归断言**

在 Top10 服务测试的 `DummyBiClient.fetch()` 中记录：

```python
calls["site_by_source"][source_key] = kwargs["site_by_asin"]
calls["default_site_by_source"][source_key] = kwargs["default_site"]
```

断言爬虫数据源收到：

```python
assert calls["site_by_source"]["crawler_details"] == {
    "B0TEST1234": "US",
    "B0TEST5678": "CA",
}
assert calls["default_site_by_source"]["crawler_details"] == "US"
```

- [x] **Step 2: 增加 MCP live-data 与 category-top 参数透传断言**

在 `tests/mcp/test_asin_data_tools.py` 的服务替身中记录 `site`，分别调用：

```python
asin_data_live_data(asin="B0TEST1234", site="CA", data_scope="basic")
asin_data_category_top(category="Bed Frames", site="CA", limit=10)
```

断言两个服务的 `run()` 均收到 `site == "CA"`。这些测试锁定 MCP schema 与统一客户端之间的站点契约。

- [x] **Step 3: 运行集成测试确认当前链路**

Run:

```powershell
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/asin_data/test_category_top.py tests/mcp/test_asin_data_tools.py -q
```

Expected: 新增断言 PASS；若站点透传断裂则 FAIL。

- [x] **Step 4: 更新 MCP 参数说明和变更记录**

将 `asin_data_live_data.site` 说明改为“站点，默认 US，同时作为 crawler-details 的 country 默认值”；将 `asin_data_category_top.site` 说明补充为“无法从渠道推断站点时使用，并作为 crawler-details country”。

更新 `docs/change-log-pending.md` 当前条目，记录实际代码、测试结果、影响范围和回滚方式，不新增重复日期条目。

- [x] **Step 5: 运行完整定向回归**

Run:

```powershell
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/asin_data/test_bi_report_data.py tests/asin_data/test_category_top.py tests/asin_data/test_asin_data_cli.py tests/mcp/test_asin_data_tools.py -q
D:\workspace\open-opscli\.venv\Scripts\python.exe -m py_compile opscli/asin_data/services/bi_report_data.py opscli/mcp/tools/asin_data.py
git diff --check
```

Expected: 全部通过，且无格式错误。

- [x] **Step 6: 提交集成回归与文档**

```powershell
git add opscli/mcp/tools/asin_data.py tests/asin_data/test_category_top.py tests/mcp/test_asin_data_tools.py docs/change-log-pending.md docs/plans/ASIN爬虫多站点取数实施计划.md
git commit -m "test: cover crawler country integrations"
```

- [ ] **Step 7: 合并并推送 release**

在所有验证通过后，将功能分支快进合并到本地 `release`，确认远程没有新增提交后推送 `origin/release`。若远程已推进，先 rebase 功能分支到最新 `origin/release` 并重新运行定向回归。
