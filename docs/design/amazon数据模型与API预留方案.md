# Amazon 数据模型与 API 预留方案

## 1. 本期目标

本期目标不是打通后端，而是先把两件事做扎实：

1. 明确当前实际能抓回来的数据
2. 固化未来提交给 ops 的 payload 结构

这样后端在设计数据表和 API 时，就能基于真实结构，而不是先拍脑袋定 schema。

详细建表 SQL 草案与 API 请求体定义见：

- [amazon建表SQL草案与ops API请求体定义.md](/Users/mask/python3/opscli/docs/design/amazon建表SQL草案与ops API请求体定义.md:1)

## 2. 当前可抓取的数据

### 2.1 商品页快照

来自 `opscli amazon scrape` / `opscli amazon payload`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `asin` | string | 商品 ASIN |
| `zip_code` | string | 采集时使用的邮编 |
| `marketplace` | string | 当前固定为 `amazon.com` |
| `page_url` | string | 商品页 URL |
| `page_title` | string | 浏览器标题 |
| `product_name` | string | 商品标题 |
| `price_text` | string | 原始价格文案 |
| `price_amount` | number/null | 标准化价格 |
| `currency` | string/null | 当前通常是 `USD` |
| `rating_text` | string | 原始评分文案 |
| `rating_value` | number/null | 标准化评分 |
| `review_count_text` | string | 原始评论数字段 |
| `review_count_value` | integer/null | 标准化评论数 |
| `location` | string | 页面显示的配送位置 |
| `collected_at` | string | 采集时间 |
| `valid` | boolean | 页面是否有效 |
| `error` | string/null | 抓取失败说明 |
| `raw` | object/null | 原始抓取字段镜像 |

### 2.2 搜索结果快照

来自 `opscli amazon search`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `asin` | string | 结果商品 ASIN |
| `keyword` | string | 搜索关键词 |
| `zip_code` | string | 采集时使用的邮编 |
| `rank` | integer | 当前抓取结果中的顺序 |
| `title` | string | 标题 |
| `price_text` | string | 原始价格文案 |
| `price_amount` | number/null | 标准化价格 |
| `rating_text` | string | 原始评分文案 |
| `rating_value` | number/null | 标准化评分 |
| `review_count_text` | string | 原始评论数文案 |
| `review_count_value` | integer/null | 标准化评论数 |
| `is_best_seller` | boolean | 是否带 Best Seller 标识 |

## 3. 推荐的数据表设计

### 3.1 商品快照主表

表名建议：`amazon_product_snapshots`

用途：存每一次商品页抓取结果，适合做价格趋势、评论增长、页面失效监控。

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | bigint PK | 主键 |
| `asin` | varchar(16) | 商品 ASIN |
| `zip_code` | varchar(16) | 邮编 |
| `marketplace` | varchar(32) | 站点 |
| `page_url` | text | 商品页 URL |
| `product_name` | text | 商品标题 |
| `price_amount` | decimal(10,2) null | 标准价格 |
| `price_text` | varchar(128) | 原始价格文案 |
| `currency` | varchar(8) null | 币种 |
| `rating_value` | decimal(4,2) null | 标准评分 |
| `rating_text` | varchar(128) | 原始评分文案 |
| `review_count_value` | int null | 标准评论数 |
| `review_count_text` | varchar(128) | 原始评论数字段 |
| `location` | varchar(255) | 配送地址 |
| `page_title` | text | 页面标题 |
| `valid` | tinyint(1) | 页面是否有效 |
| `error_message` | varchar(255) null | 页面无效或抓取异常说明 |
| `raw_payload` | json | 原始抓取镜像 |
| `collected_at` | datetime | 抓取时间 |
| `created_at` | datetime | 入库时间 |

建议索引：

- `(asin, collected_at)`
- `(asin, zip_code, collected_at)`
- `(valid, collected_at)`

### 3.2 搜索结果表

表名建议：`amazon_search_result_snapshots`

用途：记录某次关键词搜索时抓到的结果集，用于竞品池分析。

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | bigint PK | 主键 |
| `search_batch_id` | varchar(64) | 一次搜索批次号 |
| `keyword` | varchar(255) | 搜索关键词 |
| `zip_code` | varchar(16) | 邮编 |
| `asin` | varchar(16) | 结果商品 ASIN |
| `rank_position` | int | 排名位置 |
| `title` | text | 标题 |
| `price_amount` | decimal(10,2) null | 标准价格 |
| `price_text` | varchar(128) | 原始价格文案 |
| `rating_value` | decimal(4,2) null | 标准评分 |
| `rating_text` | varchar(128) | 原始评分文案 |
| `review_count_value` | int null | 标准评论数 |
| `review_count_text` | varchar(128) | 原始评论数字段 |
| `is_best_seller` | tinyint(1) | 是否 Best Seller |
| `collected_at` | datetime | 抓取时间 |
| `created_at` | datetime | 入库时间 |

建议索引：

- `(keyword, collected_at)`
- `(asin, collected_at)`
- `(search_batch_id, rank_position)`

### 3.3 采集任务表

如果后续要做后端调度，再加：

表名建议：`amazon_collection_tasks`

本期可以先不建，只保留设计。

## 4. 预留 API 设计

### 4.1 商品快照提交

建议接口：

`POST /api/v1/amazon/product-snapshots`

请求体直接复用 `opscli amazon payload` 的输出结构：

```json
{
  "source": "opscli.amazon",
  "snapshot": {
    "asin": "B0XXXXXXX",
    "zip_code": "10001",
    "marketplace": "amazon.com",
    "page_url": "https://www.amazon.com/dp/B0XXXXXXX",
    "product_name": "Sample",
    "price_text": "$19.99",
    "price_amount": 19.99,
    "rating_text": "4.6 out of 5 stars",
    "rating_value": 4.6,
    "review_count_text": "1,234 ratings",
    "review_count_value": 1234,
    "location": "New York 10001",
    "collected_at": "2026-04-23 10:00:00",
    "valid": true,
    "raw": {}
  }
}
```

### 4.2 搜索结果批量提交

建议接口：

`POST /api/v1/amazon/search-snapshots`

请求体建议：

```json
{
  "source": "opscli.amazon",
  "keyword": "pool vacuum",
  "zip_code": "10001",
  "collected_at": "2026-04-23 10:00:00",
  "results": []
}
```

## 5. 当前 CLI 能力与后端协作方式

后端设计阶段建议直接使用以下命令取样：

```bash
opscli amazon scrape --asin B0XXXXXXX --include-raw --pretty
opscli amazon payload --asin B0XXXXXXX --pretty
opscli amazon search --keyword "pool vacuum" --limit 10 --pretty
opscli amazon schema --pretty
```

这四个命令已经足够支撑接口设计、表结构设计和联调字段确认。

## 6. 真实样本观测

2026-04-23 已基于真实 Amazon 页面补跑当前工作区代码，样本文件如下：

- `output/amazon-scrape-sample-shell.json`
- `output/amazon-payload-sample-shell.json`
- `output/amazon-search-sample-shell.json`

基于关键词 `usb c cable` 和商品 `B09LCJPZ1P`，当前真实样本可确认：

### 6.1 商品页快照是精确值

`opscli amazon scrape --asin B09LCJPZ1P` 实际拿到：

- `price_amount = 12.99`
- `rating_value = 4.8`
- `review_count_text = "(29,834)"`
- `review_count_value = 29834`
- `location = "New York 10001"`

这说明商品页链路已经可以作为后端商品快照表的主要依据。

### 6.2 搜索结果页评论数通常是近似值

`opscli amazon search --keyword "usb c cable" --limit 3` 的首条结果实际拿到：

- `asin = "B09LCJPZ1P"`
- `review_count_text = "(29.8K)"`
- `review_count_value = 29800`

这里的 `review_count_value` 是从 Amazon 搜索页展示的缩写值解析而来，通常是近似值，不一定和商品页精确评论数完全相同。

后端设计时建议明确以下语义：

- 商品页 `amazon_product_snapshots.review_count_value`：可视为商品页时点的精确值
- 搜索页 `amazon_search_result_snapshots.review_count_value`：应视为搜索结果页展示口径下的近似值

如果后续需要做严格统计分析，优先使用商品页快照；搜索结果页更适合做排序、竞品曝光和大盘观察。
