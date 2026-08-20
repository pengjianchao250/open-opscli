# Keepa Seller Object 格式化合同

> 实现文件：`opscli/keepa/seller_formatter.py`；接入场景：`seller`。

- 主表保留卖家业务标量，地址数组合并为 `addressText` / `customerServicesAddressText`，`trackedSince`（兼容历史 `trackingSince`）、`lastUpdate`、`lastRatingUpdate` 派生 UTC 与 Unix 时间。
- `ratingCount`、`positiveRating`、`neutralRating`、`negativeRating` 按 30 天、90 天、365 天、lifetime 四个窗口展开，并同时输出 `seller_ratings`。
- `csv[0]` 为评分百分比历史，`csv[1]` 为评分数量历史，输出 `seller_rating_history`。
- `recentFeedback` 输出 `seller_feedback`，评分除以 10，日期转换为可读时间。
- `asinList` 与 `asinListLastSeen` 按索引配对到 `seller_storefront`。
- `sellerCategoryStatistics`、`sellerBrandStatistics`、`competitors` 分别输出 `seller_categories`、`seller_brands`、`seller_competitors`。
- `totalStorefrontAsins` 按 `[lastUpdate, count]` 解析到主表。
- 完整原始对象只存于 `raw.json`，避免主表出现高基数 JSON 单元格。
- 2026-08-20 真实查询 `ATVPDKIKX0DER` 验证：返回 10 条类目统计、10 条品牌统计、10 条竞对记录，主表及明细表无嵌套单元格。
