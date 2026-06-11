# Keepa Statistics Object 字段格式化方案

> 实现状态：已接入默认格式化导出。实现文件：`opscli/keepa/stats_formatter.py`；接入场景：`product` 返回 `stats` 对象；默认 XLSX 会派生 stats 主表字段，并按需追加 `stats_price_types`、`stats_extremes`、`stats_buy_box_sellers`、`stats_offer_snapshot` sheet。

> 参考：Keepa Statistics Object 官方讨论页 `https://keepa.com/#!discuss/t/statistics-object/1308`。本文用于指导 `opscli keepa` 后续对 Product Object 内 `stats` 对象的展示、导出与结构化解析；原始响应仍应完整保留。

## 1. 返回条件与总体原则

- `stats` 对象由 Product Request 在使用 `stats` 参数时返回，是 Product Object 的一部分。
- `stats` 是聚合快照，适合展示当前价、均价、极值、缺货率、Buy Box 归属等摘要指标；完整历史仍以 Product Object 的 `csv` 为准。
- 部分字段只有请求使用 `offers` 或 `buybox` 参数，并且商品的 `offersSuccessful` 为真时才可靠。
- `stockAmazon`、`stockBuyBox` 只有请求使用 `stock` 参数时才可能出现。
- `raw.json` 保留 Keepa 原始返回，不改字段、不改单位、不丢结构。
- 展示层、`result.json`、`xlsx` 只增加派生字段，必须能追溯到 `stats.<field>` 原字段。
- 未知字段、未知价格类型索引、未知枚举值保留原值，不因解析失败中断。

## 2. 通用格式化规则

| 数据类型 | 典型字段 | 原始格式 | 展示/导出格式 |
| --- | --- | --- | --- |
| Keepa Time | `lastOffersUpdate`、`lastBuyBoxUpdate`、`min[*][0]`、`max[*][0]`、`lightningDealInfo[*]`、`buyBoxStats.*.lastSeen` | 分钟整数 | 保留原值，追加 `*UnixSeconds`、`*UnixMilliseconds`、`*Utc`。公式：`(keepaTime + 21564000) * 60`。`-1` 不转换。 |
| 金额 | `current` 中价格索引、`avg*` 中价格索引、`buyBoxPrice`、`buyBoxShipping`、`buyBoxSavingBasis`、`buyBoxUsedPrice`、`buyBoxStats.*.avgPrice` | 站点最小货币单位整数 | 保留原值，派生十进制金额；`-1` / `-2` 视为不可用。JPY 等无小数币种按站点配置处理。 |
| 排名 | `current[3]`、`avg[3]`、`min[3]`、`max[3]` | 整数 | 保持整数；`-1` 为空。 |
| 计数 | `totalOfferCount`、`retrievedOfferCount`、`offerCountFBA`、`salesRankDrops30` | 整数 | 保持整数；按字段语义处理 `0`。 |
| 百分比 | `outOfStockPercentage30`、`buyBoxSavingPercentage`、`buyBoxStats.*.percentageWon` | 整数或浮点 | 追加 `%` 展示；导出可保留数值列与文本列。 |
| 评分 | `current[16]`、`avg[16]` | 评分乘以 10 的整数 | 派生真实评分：`rating = value / 10`；`-1` 为空。 |
| 布尔 | `buyBoxIsFBA`、`buyBoxIsAmazon`、`buyBoxIsPrimeEligible` | `true` / `false` / `null` / 缺失 | 导出布尔或“是/否”；缺失与 `null` 区分保留。 |
| 字符串 | `buyBoxSellerId`、`buyBoxAvailabilityMessage`、`buyBoxShippingCountry` | 字符串或特殊值 | 保留原值；特殊字符串 `"-1"`、`"-2"` 不自动转空。 |

## 3. Price Type 索引数组

以下字段都是“按 Price Type 索引”的数组，第一维索引与 Product Object 的 `csv` 索引一致，详见 `PRODUCT_OBJECT_FORMATTING.md` 的 `csv` 索引映射。

| 字段 | 含义 | 时间范围 |
| --- | --- | --- |
| `current` | 最近更新的价格、排名、评分、offer 数等当前值 | 当前快照 |
| `avg` | Product Request `stats` 参数指定区间内的历史加权均值 | 请求区间 |
| `avg30` | 近 30 天加权均值 | 固定 30 天 |
| `avg90` | 近 90 天加权均值 | 固定 90 天 |
| `avg180` | 近 180 天加权均值 | 固定 180 天 |
| `avg365` | 近 365 天加权均值 | 固定 365 天 |
| `atIntervalStart` | 请求区间开始时的价格、排名、评分、offer 数等 | 请求区间起点 |

解析要求：

- 数组长度不可固定，Keepa 可能新增索引；未知索引用 `CSV_<index>` 或 `priceType_<index>` 保留。
- 价格索引按金额转换；排名、计数索引保持整数；`RATING` 索引 `16` 需除以 `10`。
- `-1` 表示该 Price Type 在对应区间没有 offer、数据不足或不可用；展示为空，但保留原始值。
- 不要把所有索引都当价格：例如 `SALES` 是排名，`COUNT_NEW` 是 offer 数，`COUNT_REVIEWS` 是评论数。
- 主商品表建议只展开常用字段，完整数组保留为 JSON。

常用索引建议先支持：

| 索引 | 名称 | 类型 | 建议派生字段示例 |
| --- | --- | --- | --- |
| `0` | `AMAZON` | 价格 | `statsCurrentAmazonPrice`、`statsAvg30AmazonPrice` |
| `1` | `NEW` | 价格 | `statsCurrentNewPrice`、`statsAvg90NewPrice` |
| `2` | `USED` | 价格 | `statsCurrentUsedPrice` |
| `3` | `SALES` | 排名 | `statsCurrentSalesRank`、`statsAvg30SalesRank` |
| `10` | `NEW_FBA` | 价格 | `statsCurrentNewFbaPrice` |
| `11` | `COUNT_NEW` | 计数 | `statsCurrentNewOfferCount` |
| `16` | `RATING` | 评分 | `statsCurrentRating` |
| `17` | `COUNT_REVIEWS` | 计数 | `statsCurrentReviewCount` |
| `18` | `BUY_BOX_SHIPPING` | 价格 | `statsCurrentBuyBoxPrice` |
| `34` | `COUNT_NEW_FBA` | 计数 | `statsCurrentNewFbaOfferCount` |
| `35` | `COUNT_NEW_FBM` | 计数 | `statsCurrentNewFbmOfferCount` |

字段命名建议：

- 原始数组：保留 `stats.current`、`stats.avg30`。
- 展开字段：`statsCurrent<PriceType><Metric>`、`statsAvg30<PriceType><Metric>`。
- 金额字段可同时输出原始最小货币单位与十进制金额：`statsCurrentAmazonPriceRaw`、`statsCurrentAmazonPrice`。

## 4. 极值二维数组

`min`、`max`、`minInInterval`、`maxInInterval` 均为二维数组：第一维是 Price Type 索引，第二维为 `null` 或 `[keepaTime, value]`。

| 字段 | 含义 | 范围 |
| --- | --- | --- |
| `min` | 商品历史最低值 | 全历史 |
| `max` | 商品历史最高值 | 全历史 |
| `minInInterval` | 请求区间最低值 | Product Request `stats` 参数指定区间 |
| `maxInInterval` | 请求区间最高值 | Product Request `stats` 参数指定区间 |

解析要求：

- `null` 表示该 Price Type 没有可用极值，不应输出 `[null, null]`。
- `[keepaTime, value]` 中第一个元素转换时间，第二个元素按 Price Type 类型转换。
- 对价格索引，`value` 转金额；对 `RATING`，`value / 10`；对排名和计数，保持整数。
- `keepaTime = -1` 或 `value = -1` 时按不可用处理，但原始值保留。

建议明细表字段：

| 字段 | 说明 |
| --- | --- |
| `asin` | 商品 ASIN |
| `statField` | `min` / `max` / `minInInterval` / `maxInInterval` |
| `priceTypeIndex` | Price Type 索引 |
| `priceTypeName` | Price Type 名称 |
| `keepaTime` | 原始 Keepa Time |
| `utc` | 派生 UTC |
| `rawValue` | 原始值 |
| `formattedValue` | 按类型转换后的值 |
| `valueType` | `price` / `rank` / `count` / `rating` / `unknown` |

## 5. 缺货率数组

以下字段也是 Price Type 索引数组，但值为缺货百分比，不是价格。

| 字段 | 含义 |
| --- | --- |
| `outOfStockPercentageInInterval` | 请求区间内缺货时间占比 |
| `outOfStockPercentage30` | 近 30 天缺货时间占比 |
| `outOfStockPercentage90` | 近 90 天缺货时间占比 |
| `outOfStockPercentage180` | 近 180 天缺货时间占比 |
| `outOfStockPercentage365` | 近 365 天缺货时间占比 |

解析要求：

- `0` 表示区间内从未缺货。
- `100` 表示区间内一直缺货。
- `25` 表示区间内约 25% 时间缺货。
- `-1` 表示数据不足或该 Price Type 不是价格类型。
- 只对价格类索引输出业务结论；排名、评论数、offer 数等非价格索引不应参与缺货率分析。

## 6. 销售排名下降与 Offer 更新时间

| 字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `salesRankDrops30` | 整数 | 近 30 天销售排名从高值下降到低值的次数，通常可作为销量信号。 |
| `salesRankDrops90` | 整数 | 同上，近 90 天。 |
| `salesRankDrops180` | 整数 | 同上，近 180 天。 |
| `salesRankDrops365` | 整数 | 同上，近 365 天。 |
| `lastOffersUpdate` | Keepa Time | 最后一次 offers 信息更新时间，追加 Unix 秒、毫秒与 UTC。 |
| `totalOfferCount` | 整数 | 商品全部条件合计 offer 数；分条件 offer 数优先看 `current` 中对应 `COUNT_*` 索引。 |

注意：`salesRankDrops*` 不是实际销量，只能作为趋势和活跃度参考，不应直接等同于订单数。

## 7. Lightning Deal 信息

`lightningDealInfo` 用于识别历史、当前或即将开始的秒杀活动。

原始格式：

```text
[startDate, endDate]
```

解析要求：

- 字段为 `null`：商品从未记录到 Lightning Deal。
- 数组长度固定为 2：`startDate`、`endDate` 均为 Keepa Time 分钟。
- 即将开始：`startDate` 有值，`endDate = -1`。
- 当前进行中：`startDate` 早于当前时间，`endDate` 晚于当前时间。
- 历史活动：`startDate`、`endDate` 均早于当前时间。
- 对非 `-1` 时间追加 UTC 派生字段。
- 不要与 `csv[8] LIGHTNING_DEAL` 价格历史混淆；`lightningDealInfo` 是活动时间窗口，`csv[8]` 是价格序列。

建议派生字段：

| 字段 | 说明 |
| --- | --- |
| `lightningDealStatus` | `none` / `upcoming` / `active` / `past` / `unknown` |
| `lightningDealStartUtc` | 开始时间 UTC |
| `lightningDealEndUtc` | 结束时间 UTC；即将开始时为空 |
| `hasLightningDealHistory` | 是否有秒杀记录 |

## 8. Buy Box 字段（`offers` 或 `buybox` 参数）

以下字段只有使用 `offers` 或 `buybox` 参数时才可能返回；可靠性需结合 Product Object 的 `offersSuccessful` 判断。

### 8.1 Buy Box 基础字段

| 字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `lastBuyBoxUpdate` | Keepa Time | 最近 Buy Box 更新时间，追加 UTC。 |
| `buyBoxSellerId` | 字符串 | Buy Box 卖家 ID；可能为 `"-1"`、`"-2"` 或 `null`，保留原值并追加状态字段。 |
| `buyBoxPrice` | 金额 | New Buy Box 商品价格；`-1` / `-2` 为空。 |
| `buyBoxShipping` | 金额 | New Buy Box 运费；`-1` / `-2` 为空。 |
| `buyBoxSavingBasis` | 金额 | New Buy Box 划线参考价；缺失或不可用为空。 |
| `buyBoxSavingBasisType` | 字符串 | 参考价类型，常见 `LIST_PRICE`、`WAS_PRICE`；未知值保留。 |
| `buyBoxSavingPercentage` | 整数百分比 | New Buy Box 标示折扣百分比。 |
| `buyBoxMinOrderQuantity` | 整数 | 最小下单量；`-1` 不可用，`0` 表示无最小限制。 |
| `buyBoxMaxOrderQuantity` | 整数 | 最大下单量；`-1` 不可用，`0` 表示无限制。 |

建议派生：

- `buyBoxLandedPrice = buyBoxPrice + buyBoxShipping`，仅当两个值都可用时计算。
- `buyBoxSellerStatus`：`seller` / `special_-1` / `special_-2` / `missing`。
- `hasBuyBox`：仅当 `buyBoxSellerId` 是正常 seller id 且价格可用时为真。

### 8.2 Buy Box 状态布尔字段

| 字段 | 含义 |
| --- | --- |
| `buyBoxIsUnqualified` | 是否没有卖家合格赢得 Buy Box。 |
| `buyBoxIsShippable` | Buy Box 是否可配送。 |
| `buyBoxIsPreorder` | 是否预售。 |
| `buyBoxIsBackorder` | 是否延期交货 / 缺货可下单。 |
| `buyBoxIsFBA` | Buy Box 是否 FBA。 |
| `buyBoxIsAmazon` | Buy Box 卖家是否 Amazon。 |
| `buyBoxIsMAP` | New Buy Box 价格是否因 MAP 限制隐藏。 |
| `buyBoxIsPrimeExclusive` | 是否 Prime 专享。 |
| `buyBoxIsPrimeEligible` | 是否 Prime 可用。 |
| `buyBoxIsPrimePantry` | 是否 Prime Pantry offer。 |

布尔字段处理要求：

- `false` 是有效值，不要当作空。
- `null` 和字段缺失表示数据不可用或请求参数未返回，需与 `false` 区分。
- 业务判断不要只依赖单个布尔字段，应结合价格、sellerId、`offersSuccessful`。

### 8.3 Buy Box 配送与库存表达

| 字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `buyBoxAvailabilityMessage` | 字符串 | 可用性文案；2026-04-20 起预期变为 `IN_STOCK`、`BACKORDER_NO_ETA`、`BACKORDER_WITH_ETA` 三类枚举之一；兼容历史自由文本。 |
| `buyBoxShippingTime` | 整数数组 | `[minHours, maxHours]`，派生为 `1-2 days` 等展示文本；`null` 为空。 |
| `buyBoxShippingCountry` | 字符串 | Buy Box 卖家默认配送国家，如 `US`；Amazon 自营或不可用时可能为 `null`。 |

### 8.4 Buy Box 统计对象

`buyBoxStats` 和 `buyBoxUsedStats` 是按 sellerId 分组的对象，key 是 sellerId，value 是该卖家在请求区间内赢得 Buy Box 的统计。

常见子字段：

| 子字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `avgNewOfferCount` | 数值 | 该卖家赢得 Buy Box 期间的平均 New offer 数。 |
| `avgPrice` | 金额 | 该卖家 Buy Box offer 平均价格。 |
| `isFBA` | 布尔 | 是否 FBA。 |
| `lastSeen` | Keepa Time | 该卖家最近一次赢得 Buy Box 时间，追加 UTC。 |
| `percentageWon` | 百分比 | 该卖家在区间内赢得 Buy Box 的时间占比。 |

建议输出：

- 主商品表保留 `buyBoxStats`、`buyBoxUsedStats` JSON，并追加 Top seller 派生字段。
- 明细表 `stats_buy_box_sellers` 每个 seller 一行：`asin`、`boxType`、`sellerId`、`avgPrice`、`avgNewOfferCount`、`isFBA`、`lastSeenUtc`、`percentageWon`。
- `percentageWon` 可用于判断 Buy Box 集中度，但不要直接等同于销量占比。

### 8.5 Used Buy Box 字段

| 字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `buyBoxUsedPrice` | 金额 | Used Buy Box 商品价格；`-1` 或 `null` 为空。 |
| `buyBoxUsedShipping` | 金额 | Used Buy Box 运费；`-1` 或 `null` 为空。 |
| `buyBoxUsedSellerId` | 字符串 | Used Buy Box 卖家 ID；不可用时可能为 `null`。 |
| `buyBoxUsedIsFBA` | 布尔 | Used Buy Box 是否 FBA。 |
| `buyBoxUsedCondition` | 整数 | Used Buy Box 子成色枚举。 |

`buyBoxUsedCondition` 映射：

| 值 | 含义 |
| --- | --- |
| `2` | Used - Like New |
| `3` | Used - Very Good |
| `4` | Used - Good |
| `5` | Used - Acceptable |

建议派生 `buyBoxUsedLandedPrice = buyBoxUsedPrice + buyBoxUsedShipping`，仅当两个值都可用时计算。

## 9. Offers 参数专属字段

以下字段只有请求使用 `offers` 参数时才可能返回。

| 字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `retrievedOfferCount` | 整数 | 本次请求实际获取到的 offer 数。 |
| `sellerIdsLowestFBA` | 字符串数组 | 当前最低 New FBA offer 的卖家 ID；多个卖家同价时包含多个 ID。 |
| `sellerIdsLowestFBM` | 字符串数组 | 当前最低 New FBM offer 的卖家 ID；多个卖家同价时包含多个 ID。 |
| `offerCountFBA` | 整数 | 已获取的当前 live New FBA offer 数；`-2` 表示不可用。 |
| `offerCountFBM` | 整数 | 已获取的当前 live New FBM offer 数；`-2` 表示不可用。 |

处理要求：

- `retrievedOfferCount` 小于 `totalOfferCount` 时，说明当前只拿到部分 offers，不应把未返回卖家判断为不存在。
- `sellerIdsLowestFBA` / `sellerIdsLowestFBM` 建议保留数组，并追加 `join` 字段便于 XLSX 阅读。
- `offerCountFBA = -2`、`offerCountFBM = -2` 不等同于 0。

## 10. Stock 参数专属字段

| 字段 | 类型 | 格式化策略 |
| --- | --- | --- |
| `stockAmazon` | 整数 | Amazon offer 库存；字段缺失表示未请求或不可用。 |
| `stockBuyBox` | 整数 | Buy Box offer 库存；字段缺失表示未请求或不可用。 |

库存字段注意事项：

- `0` 可能是有效库存结果，不要自动转空。
- 字段缺失、`null` 与 `-1` 需分别保留语义。
- 库存通常有获取限制和时效性，导出时建议同时保留请求时间。

## 11. 缺失值与特殊值

| 原始值 | 典型字段 | 语义 | 导出建议 |
| --- | --- | --- | --- |
| 字段缺失 | `buyBox*`、`stock*` | 请求参数未使用或 Keepa 未提供 | 不补默认值；可派生 `has<Field>=false`。 |
| `null` | `buyBoxShippingTime`、`buyBoxUsedSellerId` | 明确无数据或不可用 | 保留空单元格或 JSON `null`。 |
| `-1` | 价格、时间、缺货率 | 多数情况下表示不可用、无 offer、数据不足 | 展示为空，保留原始字段。 |
| `-2` | Buy Box 价格、offer count | Keepa 特殊不可用状态 | 不等同于 0 或缺货，保留原值并派生状态。 |
| `0` | 百分比、计数、库存、下单限制 | 可能是有效值 | 按字段语义处理；不要统一转空。 |
| `"-1"` / `"-2"` | `buyBoxSellerId` | 字符串特殊状态 | 保留字符串，不自动转数字。 |

## 12. 建议输出结构

### 12.1 主商品表

主商品表建议保留完整 `stats` JSON，并展开以下高频字段：

- 当前价：`currentAmazonPrice`、`currentNewPrice`、`currentBuyBoxPrice`、`currentNewFbaPrice`。
- 排名与评价：`currentSalesRank`、`currentRating`、`currentReviewCount`。
- 均值：`avg30NewPrice`、`avg90NewPrice`、`avg30SalesRank`、`avg90SalesRank`。
- 缺货率：`outOfStockPercentage30Amazon`、`outOfStockPercentage90New`。
- Offer：`totalOfferCount`、`retrievedOfferCount`、`offerCountFBA`、`offerCountFBM`。
- Buy Box：`buyBoxSellerId`、`buyBoxLandedPrice`、`buyBoxIsFBA`、`buyBoxIsAmazon`、`buyBoxIsPrimeEligible`。
- 活动：`lightningDealStatus`、`lightningDealStartUtc`、`lightningDealEndUtc`。

### 12.2 明细表

建议按需生成多 sheet：

| Sheet | 粒度 | 来源字段 |
| --- | --- | --- |
| `stats_price_types` | 每个 ASIN + Price Type 一行 | `current`、`avg*`、`outOfStockPercentage*` |
| `stats_extremes` | 每个 ASIN + 极值字段 + Price Type 一行 | `min`、`max`、`minInInterval`、`maxInInterval` |
| `stats_buy_box_sellers` | 每个 ASIN + sellerId 一行 | `buyBoxStats`、`buyBoxUsedStats` |
| `stats_offer_snapshot` | 每个 ASIN 一行 | `retrievedOfferCount`、`sellerIdsLowestFBA`、`sellerIdsLowestFBM`、`offerCountFBA`、`offerCountFBM` |

## 13. 与当前 `opscli` 实现的对应关系

- `opscli/keepa/export/xlsx.py` 当前会把 dict/list JSON 字符串化，`stats` 仍以原始 JSON 输出。
- `PRODUCT_OBJECT_FORMATTING.md` 已约定 `stats.current` 等数组复用 `csv` Price Type 索引映射；后续实现应把该映射抽为共享常量。
- 当前 `_title_for_field` 保持 Keepa API 字段名，不做中文表头翻译；新增派生字段时建议命名稳定、含 Price Type 与时间窗口。
- `opscli/keepa/time.py` 已有 Keepa Time 转换能力；Statistics formatter 应复用该逻辑，不重复实现时间公式。
- 新增 formatter 不应覆盖 Product Object 原字段，建议作为展示/导出层的派生模块。

## 14. 后续实现建议

1. 新增 `stats_formatter.py`，输入 Product Object 或 `stats` 对象，输出 `main_stats` 与可选子表。
2. 将 `csv` Price Type 索引映射抽为 `price_types.py`，统一标注 `price`、`rank`、`count`、`rating`、`event` 等类型。
3. 新增站点货币配置，按 `domainId` / site 处理币种、小数位与展示符号。
4. 优先支持常用字段展开，完整 `stats` JSON 永远保留。
5. 对 `offersSuccessful=false` 或缺失的商品，Buy Box / offer 派生字段应标记 `dataFreshness=unverified`，避免误判为无竞争。
6. XLSX 多 sheet 导出先支持 `stats_price_types`、`stats_extremes`、`stats_buy_box_sellers`，大数据量时可通过参数关闭明细表。
7. 所有特殊值 `-1`、`-2`、`null`、字段缺失分别处理，禁止统一转成空字符串。
