---
name: ops-google-trends-internal
mcp-version: v1.0.0
description: Google Trends MCP 中文使用规范，覆盖深度趋势、主题自动补全和当前热点三个场景。
visibility: internal
---

# Google Trends MCP

这是 `google_trends_spec_must_read` 读取的内部规范。

## 工具

- `google_trends_spec_must_read`：首次使用前读取本规范。
- `google_trends_scenarios`：列出 `trends`、`autocomplete`、`trending-now`。
- `google_trends_run`：执行场景并生成任务和导出文件。
- `google_trends_job_status`：按 `job_id` 查询结果。
- `google_trends_export`：获取可下载导出信息。

## 执行规则

1. 已知分析对象时使用 `trends`。
2. 需要实体消歧或 Topic ID 时先使用 `autocomplete`。
3. 需要发现当前热点时使用 `trending-now`。
4. 默认地区为 `US`，用户没有指定时不追问。
5. 默认导出 XLSX；用户明确要求原始结构时可用 JSON。
6. 不向用户展示 API Key、Key 状态、套餐额度、服务器本地路径和原始请求文件。
7. `trends` 的 0–100 指数是相对热度，不是绝对搜索量。

## `trends`

- `q`：关键词、Topic ID 或最多 5 个查询词。
- `data_type`：
  - `TIMESERIES`：时间趋势，支持 1～5 个查询词。
  - `GEO_MAP`：多查询词地域对比，要求 2～5 个查询词。
  - `GEO_MAP_0`：单查询词地域热度。
  - `RELATED_TOPICS`：单查询词相关主题。
  - `RELATED_QUERIES`：单查询词相关查询。
- 常用可选参数：`date`、`geo`、`tz`、`cat`、`gprop`、`region`、`include_low_search_volume`、`hl`、`no_cache`。

示例：

```text
google_trends_run(
  scenario="trends",
  geo="US",
  params={"q":"flashlight","data_type":"TIMESERIES","date":"today 12-m"}
)
```

## `autocomplete`

必填 `q`，可选 `hl`、`no_cache`。根据 `title` 和 `type` 选择正确候选，并把候选 `q` 中的 Topic ID 传给 `trends`。

```text
google_trends_run(
  scenario="autocomplete",
  params={"q":"Apple","hl":"en"}
)
```

## `trending-now`

默认 `geo=US`；`hours` 只支持 `4`、`24`、`48`、`168`，还可传 `category_id`、`only_active`、`hl`、`no_cache`。

```text
google_trends_run(
  scenario="trending-now",
  geo="US",
  params={"hours":24,"only_active":true}
)
```

## 结果回复

成功时给出场景、地区、查询对象、`job_id`、`row_count` 和 `export.url`。无下载 URL 时只说明当前没有可下载地址，不暴露服务器本地路径。空结果时提醒检查关键词、Topic、地区和时间范围。
