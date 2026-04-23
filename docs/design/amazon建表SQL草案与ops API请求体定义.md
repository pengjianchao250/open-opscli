# Amazon 建表 SQL 草案与 ops API 请求体定义

## 1. 目标

本文基于当前 `opscli amazon` 的真实抓取结果，给出一版可直接用于后端评审的：

- SQL 建表草案
- ops API 请求体定义

本期仍以“先抓数据、API 预留”为原则，因此以下内容以稳定落库和字段语义清晰为优先，不追求一次性把调度、补采、幂等治理全部做完。

## 2. 设计前提

### 2.1 当前真实数据来源

当前 CLI 已可稳定产出两类数据：

- 商品页快照：`opscli amazon scrape` / `opscli amazon payload`
- 搜索结果快照：`opscli amazon search`

真实样本见：

- [amazon-scrape-sample-shell.json](/Users/mask/python3/opscli/output/amazon-scrape-sample-shell.json:1)
- [amazon-payload-sample-shell.json](/Users/mask/python3/opscli/output/amazon-payload-sample-shell.json:1)
- [amazon-search-sample-shell.json](/Users/mask/python3/opscli/output/amazon-search-sample-shell.json:1)

### 2.2 字段语义约束

- 商品页 `review_count_value`：按商品详情页展示，视为精确值
- 搜索页 `review_count_value`：按搜索结果页展示，视为近似值
- `location`：已做零宽字符清洗
- `collected_at`：当前由 CLI 生成，为本地抓取时间
- `raw` / `raw_payload`：建议保留，用于后续字段回溯和解析规则迭代

### 2.3 建库假设

以下 SQL 草案按 MySQL 8.0 / InnoDB / `utf8mb4` 编写。如果后端最终使用其他数据库，字段语义建议保持不变。

## 3. 建表 SQL 草案

### 3.1 商品页快照表

```sql
CREATE TABLE `amazon_product_snapshots` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `source` VARCHAR(64) NOT NULL DEFAULT 'opscli.amazon' COMMENT '采集来源',
  `asin` VARCHAR(16) NOT NULL COMMENT 'Amazon ASIN',
  `zip_code` VARCHAR(16) NOT NULL COMMENT '采集邮编',
  `marketplace` VARCHAR(32) NOT NULL DEFAULT 'amazon.com' COMMENT '站点',
  `page_url` TEXT NOT NULL COMMENT '商品页 URL',
  `page_title` TEXT NOT NULL COMMENT '浏览器标题',
  `product_name` TEXT NOT NULL COMMENT '商品标题',
  `price_text` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始价格文案',
  `price_amount` DECIMAL(10,2) NULL COMMENT '标准化价格',
  `currency` VARCHAR(8) NULL COMMENT '币种',
  `rating_text` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始评分文案',
  `rating_value` DECIMAL(4,2) NULL COMMENT '标准化评分',
  `review_count_text` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始评论数字段',
  `review_count_value` INT NULL COMMENT '标准化评论数',
  `location` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '配送地址',
  `valid` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '页面是否有效',
  `error_message` VARCHAR(255) NULL COMMENT '抓取失败或页面失效说明',
  `raw_payload` JSON NULL COMMENT '原始抓取镜像',
  `collected_at` DATETIME NOT NULL COMMENT '抓取时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  PRIMARY KEY (`id`),
  KEY `idx_aps_asin_collected_at` (`asin`, `collected_at`),
  KEY `idx_aps_asin_zip_collected_at` (`asin`, `zip_code`, `collected_at`),
  KEY `idx_aps_valid_collected_at` (`valid`, `collected_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Amazon 商品页抓取快照';
```

### 3.2 搜索批次表

推荐把搜索请求的公共信息单独建一张批次表，和 API 的天然结构一致，也更方便后续做一次搜索对应多条结果的追踪。

```sql
CREATE TABLE `amazon_search_batches` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `batch_key` VARCHAR(64) NOT NULL COMMENT '批次号，可由服务端生成',
  `source` VARCHAR(64) NOT NULL DEFAULT 'opscli.amazon' COMMENT '采集来源',
  `keyword` VARCHAR(255) NOT NULL COMMENT '搜索关键词',
  `zip_code` VARCHAR(16) NOT NULL COMMENT '采集邮编',
  `marketplace` VARCHAR(32) NOT NULL DEFAULT 'amazon.com' COMMENT '站点',
  `result_count` INT NOT NULL DEFAULT 0 COMMENT '结果数量',
  `collected_at` DATETIME NOT NULL COMMENT '抓取时间',
  `request_payload` JSON NULL COMMENT '原始请求体镜像',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_asb_batch_key` (`batch_key`),
  KEY `idx_asb_keyword_collected_at` (`keyword`, `collected_at`),
  KEY `idx_asb_zip_collected_at` (`zip_code`, `collected_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Amazon 搜索抓取批次';
```

### 3.3 搜索结果表

```sql
CREATE TABLE `amazon_search_result_snapshots` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `batch_id` BIGINT UNSIGNED NOT NULL COMMENT '关联搜索批次',
  `asin` VARCHAR(16) NOT NULL COMMENT 'Amazon ASIN',
  `rank_position` INT NOT NULL COMMENT '搜索结果排序位置',
  `title` TEXT NOT NULL COMMENT '标题',
  `price_text` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始价格文案',
  `price_amount` DECIMAL(10,2) NULL COMMENT '标准化价格',
  `rating_text` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始评分文案',
  `rating_value` DECIMAL(4,2) NULL COMMENT '标准化评分',
  `review_count_text` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始评论数字段',
  `review_count_value` INT NULL COMMENT '标准化评论数，通常为近似值',
  `is_best_seller` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否带 Best Seller 标识',
  `collected_at` DATETIME NOT NULL COMMENT '抓取时间，冗余保留便于查数',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_asrs_batch_rank` (`batch_id`, `rank_position`),
  KEY `idx_asrs_asin_collected_at` (`asin`, `collected_at`),
  KEY `idx_asrs_batch_id` (`batch_id`),
  CONSTRAINT `fk_asrs_batch_id`
    FOREIGN KEY (`batch_id`) REFERENCES `amazon_search_batches` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Amazon 搜索结果快照';
```

## 4. ops API 草案

## 4.1 商品页快照提交接口

### 接口建议

`POST /api/v1/amazon/product-snapshots`

### 请求体定义

```json
{
  "source": "opscli.amazon",
  "snapshot": {
    "asin": "B09LCJPZ1P",
    "zip_code": "10001",
    "marketplace": "amazon.com",
    "page_url": "https://www.amazon.com/dp/B09LCJPZ1P",
    "page_title": "Amazon.com: Anker USB C to USB C Cable, 2-Pack 6 FT (1.8 m) Type C 100W Charger Cord, Fast Charging for iPhone 17 Series, MacBook Pro 2020, Pixel, and More (Black, Not for Video Output)",
    "product_name": "Anker USB C to USB C Cable, 2-Pack 6 FT (1.8 m) Type C 100W Charger Cord, Fast Charging for iPhone 17 Series, MacBook Pro 2020, Pixel, and More (Black, Not for Video Output)",
    "price_text": "$12.99",
    "price_amount": 12.99,
    "currency": "USD",
    "rating_text": "4.8 out of 5 stars",
    "rating_value": 4.8,
    "review_count_text": "(29,834)",
    "review_count_value": 29834,
    "location": "New York 10001",
    "collected_at": "2026-04-23 16:00:00",
    "valid": true,
    "error": null,
    "raw": {
      "productName": "Anker USB C to USB C Cable, 2-Pack 6 FT (1.8 m) Type C 100W Charger Cord, Fast Charging for iPhone 17 Series, MacBook Pro 2020, Pixel, and More (Black, Not for Video Output)",
      "price": "$12.99",
      "rating": "4.8 out of 5 stars",
      "reviewCount": "(29,834)",
      "location": "New York 10001"
    }
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `source` | 是 | 当前固定为 `opscli.amazon` |
| `snapshot.asin` | 是 | 商品 ASIN |
| `snapshot.zip_code` | 是 | 抓取邮编 |
| `snapshot.marketplace` | 是 | 当前固定 `amazon.com` |
| `snapshot.page_url` | 是 | 商品页 URL |
| `snapshot.page_title` | 是 | 页面标题 |
| `snapshot.product_name` | 是 | 商品标题 |
| `snapshot.price_text` | 是 | 原始价格文案，可为空字符串 |
| `snapshot.price_amount` | 否 | 标准价格，抓不到时为 `null` |
| `snapshot.currency` | 否 | 币种，抓不到时为 `null` |
| `snapshot.rating_text` | 是 | 原始评分文案，可为空字符串 |
| `snapshot.rating_value` | 否 | 标准评分 |
| `snapshot.review_count_text` | 是 | 原始评论数字段，可为空字符串 |
| `snapshot.review_count_value` | 否 | 标准评论数 |
| `snapshot.location` | 是 | 配送地址 |
| `snapshot.collected_at` | 是 | 抓取时间 |
| `snapshot.valid` | 是 | 页面是否有效 |
| `snapshot.error` | 否 | 页面失效或抓取异常时的说明 |
| `snapshot.raw` | 否 | 原始抓取镜像 |

### 服务端落库建议

- `source -> amazon_product_snapshots.source`
- `snapshot.error -> amazon_product_snapshots.error_message`
- `snapshot.raw -> amazon_product_snapshots.raw_payload`

## 4.2 搜索结果批量提交接口

### 接口建议

`POST /api/v1/amazon/search-snapshots`

### 请求体定义

```json
{
  "source": "opscli.amazon",
  "keyword": "usb c cable",
  "zip_code": "10001",
  "marketplace": "amazon.com",
  "collected_at": "2026-04-23 16:05:00",
  "results": [
    {
      "asin": "B09LCJPZ1P",
      "rank": 1,
      "title": "Anker USB C to USB C Cable, 2-Pack 6 FT (1.8 m) Type C 100W Charger Cord, Fast Charging for iPhone 17 Series, MacBook Pro 2020, Pixel, and More (Black, Not for Video Output)",
      "price_text": "$12.99",
      "price_amount": 12.99,
      "rating_text": "4.8 out of 5 stars",
      "rating_value": 4.8,
      "review_count_text": "(29.8K)",
      "review_count_value": 29800,
      "is_best_seller": false
    }
  ]
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `source` | 是 | 当前固定为 `opscli.amazon` |
| `keyword` | 是 | 搜索关键词 |
| `zip_code` | 是 | 抓取邮编 |
| `marketplace` | 是 | 当前固定 `amazon.com` |
| `collected_at` | 是 | 搜索抓取时间 |
| `results` | 是 | 搜索结果数组，允许为空数组 |
| `results[].asin` | 是 | 商品 ASIN |
| `results[].rank` | 是 | 当前抓取排序位置 |
| `results[].title` | 是 | 商品标题 |
| `results[].price_text` | 是 | 原始价格文案，可为空字符串 |
| `results[].price_amount` | 否 | 标准价格 |
| `results[].rating_text` | 是 | 原始评分文案，可为空字符串 |
| `results[].rating_value` | 否 | 标准评分 |
| `results[].review_count_text` | 是 | 原始评论数字段，可为空字符串 |
| `results[].review_count_value` | 否 | 标准评论数，通常为近似值 |
| `results[].is_best_seller` | 是 | 是否带 Best Seller 标识 |

### 服务端落库建议

1. 服务端先生成 `batch_key`，写入 `amazon_search_batches`
2. 将 `results` 展开后写入 `amazon_search_result_snapshots`
3. `rank -> rank_position`
4. `collected_at` 同时写入批次表和结果表

## 5. 推荐的服务端返回结构

虽然本期主要是预留 API，但建议提前统一返回格式，减少后续 CLI 对接成本。

### 5.1 商品页快照返回

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "snapshot_id": 12345
  }
}
```

### 5.2 搜索批次返回

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "batch_id": 67890,
    "batch_key": "asb_20260423160500_0001",
    "result_count": 10
  }
}
```

## 6. 实施建议

### 6.1 第一阶段

- 后端先建 `amazon_product_snapshots`
- 后端先建 `amazon_search_batches` 和 `amazon_search_result_snapshots`
- CLI 继续只负责抓取与输出 payload，不直接提交

### 6.2 第二阶段

- 后端确认接口路径和鉴权方式
- CLI 增加 `amazon submit` 或恢复 `payload -> submit` 编排
- 补充幂等键、失败重试和批次追踪

### 6.3 字段稳定性建议

- 商品页以 `scrape/payload` 字段为主契约
- 搜索页字段允许后续少量扩展，但不建议轻易改名
- `raw_payload` 建议至少保留 30 天，方便解析规则调整时回放验证
