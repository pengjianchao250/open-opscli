# ASIN取数服务参数精简与Keepa封装对比

## 最终结论

`asin-data` 公共 CLI 采用直接业务子命令，不再使用 Keepa 风格的 `run <scenario> --params`，也不再把基础数据和 BI 数据混在 `live-data --data-scope` 中。

面向用户和 Skill 的主入口固定为：

```powershell
opscli asin-data basic
opscli asin-data bi
opscli asin-data category-top
```

三个命令默认只返回 JSON，不生成工作簿、不上传 OSS。旧 `live-data` 仅作为隐藏兼容入口保留，不出现在帮助信息和新 Skill 文档中。

## 服务参数

| 封装服务 | CLI 子命令 | 必填查询项 | 可选过滤条件 | 取数来源 |
| --- | --- | --- | --- | --- |
| 基础数据查询 | `basic` | `--asin` 或 `--asins` | `--site`、`--source` | 北极星 BI 刊登系统、OPS crawler-details |
| BI数据查询 | `bi` | `--asin` 或 `--asins` | `--site`、`--date-from`、`--date-to`、`--domain` | OPS sales-traffic、SP搜索词、SQP、活动、物控库存接口 |
| 类目Top查询 | `category-top` | `--category` | `--site`、`--date-from`、`--date-to`、`--limit` | OPS internal-category-top10 |

公共输入规则：

- `--asin` 可以重复传入。
- `--asins` 接受 JSON 数组，例如 `["B086M58PQ3","B0TEST1234"]`。
- ASIN 自动转为大写、去重，并校验为 10 位字母数字编码。
- 支持站点：`US`、`UK`、`CA`、`DE`、`FR`、`IT`、`ES`、`JP`、`AU`、`MX`、`BR`、`AE`、`SA`。
- 所有日期使用 `YYYY-MM-DD`，开始日期不得晚于结束日期，且不得包含未来日期。

## 基础数据查询

### 能拿到什么数据

- `listing_basic`：标题、五点、产品描述、商品亮点、品牌、类目等基础刊登字段。
- `crawler_details`：A+图片、A+描述、QA、Review List 等爬虫补充字段。
- 刊登与爬虫字段冲突时，以基础刊登数据为准；爬虫仅补充非冲突字段。
- 未明确 SC/VC 渠道时，刊登查询先尝试 `account_type=1`，未找到后自动尝试 VC 的 `account_type=2`。

### 怎么用

```powershell
opscli asin-data basic --asin B086M58PQ3 --site US
opscli asin-data basic --asins '["B086M58PQ3","B0TEST1234"]' --site US
opscli asin-data basic --asin B086M58PQ3 --source listing
opscli asin-data basic --asin B086M58PQ3 --source crawler
```

`--source` 可重复传入，支持 `listing`、`crawler`；不传时返回两类数据。

### 注意事项

- 默认直接返回完整源 JSON，不生成拆包文件。
- VC 回退由服务内部完成，不向用户暴露 `account_type`。
- 查询结果受当前登录用户的数据权限和上游数据可用性影响。

### 取数来源

- 北极星 BI 刊登列表：`/listing/getAmazonListing`。
- 北极星 BI 刊登详情：`/listing/amazonlisdet`。
- 北极星刊登模板：`/amazon/feed/getTemplate`。
- OPS 爬虫详情：`/dataMetrics/v1/asin-report-files/crawler-details`。

## BI数据查询

### 能拿到什么数据

| domain | 数据范围 |
| --- | --- |
| `sales_traffic` | 销售、流量、广告、库存数据 |
| `sp_search_term` | SP广告搜索词数据 |
| `sqp` | Brand Analytics Search Query Performance 数据 |
| `deals` | 活动数据 |
| `turnover_inventory` | 物控版库存和周转数据 |

### 怎么用

```powershell
opscli asin-data bi --asin B086M58PQ3 --site US
opscli asin-data bi --asin B086M58PQ3 --date-from 2026-07-01 --date-to 2026-07-15
opscli asin-data bi --asin B086M58PQ3 --domain sqp
```

不传日期时默认查询最近30天；不传 `--domain` 时返回全部 BI 数据域。

### 注意事项

- 不同数据域的统计口径和更新时间可能不同，调用方应保留响应中的数据域标识。
- 查询结果受当前登录用户的数据权限约束。
- `bi` 不查询刊登或爬虫基础数据。

### 取数来源

- 销售/库存/广告/流量：`/dataMetrics/v1/asin-report-files/sales-traffic-data`。
- SP广告搜索词：`/api/v1/sp-search-term/query`。
- Brand Analytics搜索查询表现：`/api/v1/brand-analytics-search-query/query`，数据域名称为 `sqp`。
- 活动数据：`/dataMetrics/v1/asin-report-files/deals-data`。
- 物控版库存：`/dataMetrics/v1/asin-report-files/turnover-inventory-data`。

## 类目Top查询

### 能拿到什么数据

返回指定站点、类目和日期范围内的内部类目 Top ASIN 排名明细，包括排名、ASIN、渠道及接口提供的销售指标等原始字段。

结果只包含 `category_top`：

```json
{
  "success": true,
  "command": "asin-data category-top",
  "data": {
    "category": "Bed Frames",
    "site": "US",
    "date_from": "2026-07-01",
    "date_to": "2026-07-15",
    "limit": 10,
    "row_count": 10,
    "category_top": []
  },
  "error": null
}
```

### 怎么用

```powershell
opscli asin-data category-top --category "Bed Frames" --site US
opscli asin-data category-top --category "Bed Frames" --site US --date-from 2026-07-01 --date-to 2026-07-15 --limit 10
```

### 注意事项

- 类目名称按内部平台类目 `amazon_cat` 精确匹配。
- 默认日期范围为当月1日至当天。
- `limit` 默认10，允许1至100。
- 不查询刊登、爬虫或 BI 数据，不生成 Excel，不上传 OSS。

### 取数来源

- OPS 内部类目 Top 接口：`/dataMetrics/v1/asin-report-files/internal-category-top10`。

## 请求检测与日志

项目已有全局 CLI 遥测，会把命令路径、原始 CLI 参数、状态、耗时、用户和设备标识异步上报到：

```text
{ops_url}/v1/cli/telemetry
```

本次为 `basic`、`bi`、`category-top` 增加本地结构化审计日志：

```text
~/.config/opscli/asin-data/usage.jsonl
```

每条 JSONL 包含：

```json
{
  "timestamp": "2026-07-16T01:00:00+00:00",
  "command": "category-top",
  "status": "success",
  "elapsed_seconds": 0.321,
  "params": {
    "category": "Bed Frames",
    "site": "US",
    "date_from": "2026-07-01",
    "date_to": "2026-07-15",
    "limit": 10
  }
}
```

安全规则：

- `jwt`、`session_id`、`Authorization`、Cookie、密码、Token、Secret、API Key 等字段递归替换为 `[REDACTED]`。
- 日志写入失败不会影响取数结果。
- 设置 `OPSCLI_ASIN_DATA_USAGE_LOG_DISABLED=1` 可以关闭本地日志。
- 设置 `OPSCLI_ASIN_DATA_USAGE_LOG_PATH` 可以覆盖日志路径。

## 与Keepa封装的差异

Keepa 面向多个外部 API 场景，适合 `run <scenario> --params`；`asin-data` 当前稳定业务入口只有基础数据、BI数据和类目Top三类，直接子命令更便于用户记忆，也更利于 Skill 生成明确参数。

内部仍复用统一查询服务和远端客户端，但不把数据集别名、table ID、上传、并发、轮询或 `skip_*` 参数暴露给公共 CLI。
