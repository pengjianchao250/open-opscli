# ASIN 爬虫多站点取数设计

## 背景

ASIN 基础取数使用 `/dataMetrics/v1/asin-report-files/crawler-details` 获取爬虫详情。该接口新增 `country` 查询参数后，调用方需要明确传入站点。现有 `live-data`、MCP 和类目 Top10 链路已经持有 `site` 或 `site_by_asin`，但 `crawler_details` 请求尚未消费这些信息。

## 目标

- `crawler-details` 每次请求都携带 `country`，未提供站点时默认 `US`。
- 单站点批量 ASIN 合并为一次请求。
- 多站点批量 ASIN 按标准化站点分组，并行请求后合并结果。
- CLI、MCP 和类目 Top10 共用同一套实现和返回协议。
- 保持现有 `crawler_details.rows` 结构，避免破坏 AI Ready 数据集消费者。

## 非目标

- 不修改 `crawler-details` 服务端接口。
- 不新增独立 CLI 或 MCP 参数；继续使用现有 `site`、`site_column` 和 Top10 渠道站点映射。
- 不改变 `listing_basic`、BI 数据源、卖家精灵或 Rufus 的请求逻辑。

## 请求规则

### 单站点

```text
GET /dataMetrics/v1/asin-report-files/crawler-details
    ?asins=B0AAA,B0BBB
    &country=US
```

### 多站点

输入：

```text
B0AAA,US
B0BBB,CA
B0CCC,US
```

请求分组：

```text
GET crawler-details?asins=B0AAA,B0CCC&country=US
GET crawler-details?asins=B0BBB&country=CA
```

不同站点组之间允许并行请求。组内 ASIN 保持输入顺序，最终合并行按站点首次出现顺序和接口返回顺序排列。

## 站点来源

优先级如下：

1. `site_by_asin` 中对应 ASIN 的站点。
2. 当前调用的 `default_site`。
3. 固定默认值 `US`。

站点统一复用 `bi_report_data.py` 现有标准化逻辑。`美国`、`USA`、`美国站` 等别名转换为 `US`，其他已支持别名按现有映射转换。

## 实现边界

在 `AsinBiReportDataClient` 内为 `crawler_details` 增加专用获取方法。`_fetch_source()` 识别该 source 后转入专用方法，避免 CLI、MCP 和 Top10 分别维护重复逻辑。

调用链保持为：

```text
CLI live-data / MCP asin_data_live_data / MCP asin_data_category_top
  -> AsinDataCollector 或 AsinCategoryTopService
  -> AsinBiReportDataClient.fetch(... site_by_asin, default_site)
  -> crawler_details 按 country 分组请求
  -> 合并为一个 crawler_details source
```

## 返回协议

成功结果继续使用现有 source 结构：

```json
{
  "key": "crawler_details",
  "label": "爬虫ASIN详情数据",
  "endpoint": "/dataMetrics/v1/asin-report-files/crawler-details",
  "status": "success",
  "row_count": 2,
  "rows": [],
  "raw": {
    "US": {},
    "CA": {}
  }
}
```

`rows` 仍是所有站点的统一数组。CLI、MCP、AI Ready 和 Top10 的 `crawler_details` dataset 不增加额外嵌套层级。

## 错误处理

- 所有站点成功：source `status=success`。
- 部分站点失败：保留成功站点的 `rows`，source `status=partial`，并在 `country_errors` 中按站点记录结构化错误。
- 所有站点失败：source `status=failed`，`rows=[]`，保留全部 `country_errors`。
- 单个请求的 HTTP、业务码和 JSON 解析继续复用现有异常类型。
- 一个站点失败不得取消其他站点请求或丢弃已成功数据。

部分失败示例：

```json
{
  "status": "partial",
  "row_count": 1,
  "rows": [
    {
      "asin": "B0AAA",
      "country": "US"
    }
  ],
  "raw": {
    "US": {}
  },
  "country_errors": {
    "CA": {
      "code": "ASIN_BI_REPORT_DATA_HTTP_ERROR",
      "message": "crawler_details request failed",
      "status_code": 500
    }
  }
}
```

## CLI 与 MCP 行为

- `opscli asin-data live-data --asin ... --site CA --data-scope basic` 传递 `country=CA`。
- 未传 `--site` 时传递 `country=US`。
- 文件输入继续读取 `--site-column`，多站点时自动拆分请求。
- `asin_data_live_data(site="CA")` 使用 `country=CA`。
- `asin_data_category_top(site="US")` 仅将 `site` 作为无法从 Top 数据推断站点时的默认值。

## Top10 行为

类目 Top10 继续通过 `_site_by_asin()` 从 `站点`、`site_code`、`country_iso_code` 或渠道国家推断站点。推断结果原样传给 `AsinBiReportDataClient`，由统一的爬虫分组逻辑生成请求。最终每个 item 的 `crawler_details` dataset 保持现有字段：`rows`、`preview_rows`、`columns`、`quality` 和 `diagnostics`。

## 测试范围

- 未提供站点时请求包含 `country=US`。
- 单个非 US 站点请求包含对应 `country`。
- 中文站点别名被标准化。
- 多站点 ASIN 按站点分组，且每个 ASIN 只出现于对应请求。
- 多站点结果正确合并到一个 source。
- 部分失败保留成功数据并输出 `country_errors`。
- 全部失败返回 `failed`。
- Top10 将推断后的站点传入爬虫请求。
- MCP `site` 参数经过现有服务链传递到爬虫请求。

## 验收标准

- `crawler-details` 不再出现缺少 `country` 的请求。
- 单 ASIN、批量文件和 Top10 均支持 US 以外站点。
- 现有 AI Ready `crawler_details.rows` 消费方式无需修改。
- 新增测试和相关 ASIN/MCP 回归测试全部通过。
