# Keepa Deal 与 Product 活动价格字段完善分析

> 调研日期：2026-08-25
> 调研范围：Keepa 官方 [Deal Object](https://keepa.com/api-docs/deal-object.html)、[Product Object](https://keepa.com/api-docs/product-object.html)，并补充核对官方 [Statistics Object](https://keepa.com/api-docs/statistics-object.html) 与 [Marketplace Offer Object](https://keepa.com/api-docs/offer-object.html)；对照 `opscli/keepa` 当前 formatter、MCP 摘要与导出链路。
> 本文只给出分析和完善建议，不修改代码。

## 1. 结论摘要

`B0DP4L8HBB` 这类“Amazon 页面有 Limited time deal，但 MCP 没有 Deal 价格”的问题，不能只靠新增一个 `currentDealPrice` 字段解决。官方对象实际区分了三种不同语义：

1. **Product `deals` 是活动徽标元数据，不是价格对象。** 它只包含 `accessType`、`dealType`、`badge`，没有 `dealPrice`。`LIMITED_TIME_DEAL` 只能证明 Buy Box 关联了该活动徽标，不能证明某个 Buy Box 价格字段就是 Keepa 独立返回的 Deal 价格。来源：[Product Object - Deal badges](https://keepa.com/api-docs/product-object.html#fields-deals)。当前实现只输出 `dealCount`，见 `opscli/keepa/product_formatter.py` 的 `_add_content_summary()`。
2. **Browsing Deals 返回的 Deal Object 是“近期发生价格或排名变化的商品摘要”，不是 Amazon 活动对象。** `current`、`currentSince`、`deltaLast`、`delta`、`deltaPercent`、`avg` 是按 Product `csv` price type 索引组织的变化指标；不能因对象名为 Deal 就把 `current[18]` 或 `deltaPercent` 命名为活动价或活动折扣。来源：[Deal Object](https://keepa.com/api-docs/deal-object.html)。当前映射见 `opscli/keepa/deal_formatter.py`。
3. **Keepa 有独立价格语义的活动类型目前是 `LIGHTNING_DEAL` 和 `PRIME_EXCL` price type。** Lightning Deal 使用 `csv[8]` / `stats.current[8]`，Prime exclusive New 使用 `csv[33]` / `stats.current[33]`。Limited Time Deal 没有对应的独立 price type。来源：[Product Object - csv History Array](https://keepa.com/api-docs/product-object.html#csv-array)。当前 `opscli/keepa/product_formatter.py` 已声明索引 8、33，但主表当前值映射遗漏二者；`opscli/keepa/stats_formatter.py` 还遗漏了 `PRIME_EXCL` 索引 33。
4. **Limited Time Deal 应输出“活动事实 + Buy Box 价格事实”，不要伪造 Keepa 原始 Deal 价。** 可以将两者组合成显式推导字段，如 `dealAssociatedBuyBoxLandedPrice`，同时输出 `priceSource=STATS_BUY_BOX`、`isDerived=true`、`isNativeDealPrice=false`。禁止无来源标记地输出 `currentDealPrice=BuyBox`。
5. **折前价优先读取 Statistics 的 Buy Box 划线价字段。** 官方提供 `buyBoxSavingBasis`、`buyBoxSavingBasisType`（`LIST_PRICE` 或 `WAS_PRICE`）和 `buyBoxSavingPercentage`，比直接套用 Product `LISTPRICE` 更贴近当前 Buy Box 展示。来源：[Statistics Object - Buy Box fields](https://keepa.com/api-docs/statistics-object.html#buybox-fields)。当前 `opscli/keepa/stats_formatter.py` 已转换这些字段，但 MCP 摘要白名单没有暴露它们。
6. **MCP 丢失 Deal 数据有两层原因。** Product formatter 只保留 `dealCount`；随后 `opscli/keepa/summary.py` 的固定白名单又不包含 `dealCount`、Deal 类型及任何价格字段。并且 JSON 导出路径在 formatter 之前就调用摘要，见 `opscli/keepa/services/api_manager.py`，所以只改 Product formatter 不能保证 MCP 的 JSON/XLSX 两条路径一致。

因此，完善方向应是：**先补官方原始事实，再补明确标记的组合推导，最后改造场景化 MCP 摘要；不要把 Buy Box 价改名为无来源的 Deal 价。**

## 2. 官方对象语义边界

### 2.1 Product `deals`：活动徽标，不含价格

官方将 Product `deals` 描述为“与商品 Buy Box 关联的 active deals metadata”。字段只有：

| 字段 | 官方语义 | 可否直接输出 |
| --- | --- | --- |
| `accessType` | 活动可访问人群，如 `ALL`、`PRIME_EARLY_ACCESS`、`PRIME_EXCLUSIVE` | 可以，保留未知新枚举 |
| `dealType` | 活动徽标类型，如 `LIMITED_TIME_DEAL`、`PRIME_DAY`、`SELLING_FAST` 等 | 可以，保留未知新枚举 |
| `badge` | Amazon 页面显示的徽标原文 | 可以 |

来源：[Product Object - Deal badges](https://keepa.com/api-docs/product-object.html#fields-deals)。

必须注意以下边界：

- `deals` 仅在 Product Request 使用 `offers` 参数时更新。字段缺失表示“本次没有可用元数据或未请求/未更新”，不能直接等价为“当前无活动”。
- 非空 `deals` 可以确认存在活动徽标；空数组可以表达“最近一次 offers 更新未发现活动”；字段缺失应表达 `unknown/not_returned`。
- `dealType` 中包含 `SELLING_FAST`、`COUNTDOWN_ENDS_IN` 等不一定代表降价的徽标，因此 `dealCount > 0` 也不能自动推出“有折扣价”。
- `LIMITED_TIME_DEAL` 没有独立价格字段。任何由 Buy Box 价格关联得到的“活动价”都是本地组合推导，而不是 Keepa Product 原始字段。

当前 `opscli/keepa/product_formatter.py` 的 `_add_content_summary()` 只派生 `dealCount`，随后嵌套 `deals` 被移出 Product 主表并落入通用 `product_nested_values`，造成主表和 MCP 无法直接识别 `LIMITED_TIME_DEAL`。

### 2.2 Deal Object：近期变化摘要，不等于促销活动

官方定义 Deal Object 为“recently undergone changes, typically in price or sales rank”的商品摘要，由 Browsing Deals 接口返回。来源：[Deal Object](https://keepa.com/api-docs/deal-object.html)。

| 字段 | 准确语义 | 禁止误读 |
| --- | --- | --- |
| `current[priceType]` | Keepa 最后更新时间点的当前价格/排名；金额为站点最小货币单位，`-1` 表示区间内无 offer | 不能统称为 Deal 价 |
| `currentSince[priceType]` | 当前值开始生效的 Keepa Time minutes | 不是活动开始时间 |
| `deltaLast[priceType]` | 前一个值与当前值之差；`0` 表示未变化或无法计算 | 不是折扣金额 |
| `delta[range][priceType]` | 指定窗口加权均值与当前值之差 | 不是标价减活动价 |
| `deltaPercent[range][priceType]` | 与 `delta` 相同口径的百分比 | 不是 Amazon 页面活动折扣率 |
| `avg[range][priceType]` | 指定窗口加权均值；`avg[0]` 名为 day，但实际是最近 48 小时 | 不是原价或划线价 |
| `creationDate` | 请求 price types 最近一次价格/值变化时间 | 不是商品创建时间，也不是活动创建时间 |
| `lightningEnd` | Lightning Deal 计划结束时间；非 Lightning Deal 为 0 | 不能用于识别 Limited Time Deal |

`LIGHTNING_DEAL`、`PRIME_EXCL`、`WAREHOUSE` 的 `deltaLast`、`delta`、`deltaPercent` 以 Amazon 或 New 价格为参考，不是同 price type 自身历史的变化。来源：[Deal Object - Lightning, Prime Exclusive and Warehouse Deals](https://keepa.com/api-docs/deal-object.html#lightning-prime-exclusive-warehouse-deals)。当前 `opscli/keepa/deal_formatter.py` 已用 `deltaReference=AMAZON_OR_NEW` 标识这三个索引，此做法应保留。

### 2.3 Product `csv` 与 Statistics `current`：真正按 price type 区分价格

Product `csv` 是历史序列，Statistics `current` 使用相同 price type 索引。来源：[Product Object - csv History Array](https://keepa.com/api-docs/product-object.html#csv-array)、[Statistics Object - Price Type Indexing](https://keepa.com/api-docs/statistics-object.html#price-type-indexing)。与活动价格最相关的索引如下：

| 索引 | 类型 | 语义 | 依赖 |
| --- | --- | --- | --- |
| 0 | `AMAZON` | Amazon 价格 | 基础 Product 历史 |
| 1 | `NEW` | Marketplace New 最低价 | 基础 Product 历史 |
| 4 | `LISTPRICE` | List Price / MSRP 历史 | 不保证等于当前页面划线价 |
| 8 | `LIGHTNING_DEAL` | Lightning Deal 价格历史 | 独立活动 price type |
| 18 | `BUY_BOX_SHIPPING` | New Buy Box 价格与运费历史 | 需要 `offers` 参数 |
| 33 | `PRIME_EXCL` | 最低 Prime exclusive New offer 价格历史 | 需要 `offers` 参数 |

可以直接输出：

- `stats.current[8]` 为当前 Lightning Deal price type 值时，命名为 `currentLightningDealPrice`，并标记来源 `STATS_CURRENT_8`。
- `stats.current[33]` 为当前 Prime exclusive New price type 值时，命名为 `currentPrimeExclusivePrice`，并标记来源 `STATS_CURRENT_33`。
- `stats.buyBoxPrice`、`stats.buyBoxShipping`、二者相加的 landed price、`buyBoxSavingBasis`、`buyBoxSavingBasisType`、`buyBoxSavingPercentage`，均可按各自官方名称输出。

不能直接输出：

- `LIMITED_TIME_DEAL` 的独立价格，因为官方没有对应字段或 price type。
- 将 `stats.current[18]`、`stats.buyBoxPrice` 或 `currentNewPrice` 无条件命名为 `currentDealPrice`。
- 将 `LISTPRICE` 当作 Amazon 当前页面划线价。若 Statistics 返回 `buyBoxSavingBasis`，应优先使用后者，并保留其 `LIST_PRICE/WAS_PRICE` 类型。

### 2.4 Lightning Deal 历史需要专门解析

官方说明：Lightning Deal 当前生效时，`csv[8]` 最后一条可能是“未来结束时间 + `-1`”；若当前没有活动而最后一条仍是“未来时间 + `-1`”，则表示未来将开始的已公告活动。官方建议读取当前价时处理这一特殊情况，或直接使用 `stats.current[8]`。来源：[Product Object - Lightning Deals note](https://keepa.com/api-docs/product-object.html#csv-array)。

因此：

- `stats.current[8]` 是当前 Lightning Deal 价格的优先来源。
- 不能让通用“取最后一个 csv 值”的逻辑读取 `csv[8]`；否则会把活动结束哨兵 `-1` 当作当前无价格。
- `stats.lightningDealInfo=[startDate,endDate]` 用于识别过去、未来或当前 Lightning Deal；`null` 表示从未有过 Lightning Deal。来源：[Statistics Object - lightningDealInfo](https://keepa.com/api-docs/statistics-object.html#fields)。
- 仅根据 `csv[8]` 的未来 `-1` 无法在所有情况下稳定区分“当前活动结束时间”和“未来活动开始时间”，应结合 `lightningDealInfo`；证据不足时输出 `unknown`，不要猜测。

当前 `opscli/keepa/product_formatter.py` 的 `_latest_csv_value()` 是通用末值读取，未来若把索引 8 加入 `CURRENT_FIELD_BY_INDEX` 会立即踩中该特殊语义。完善时必须先引入 Lightning 专用读取逻辑。`opscli/keepa/stats_formatter.py` 已解析 `lightningDealInfo`，但当前把字段缺失和显式 `null` 都归为 `none`，建议进一步区分 `not_returned` 与 `never`。

### 2.5 Coupon、Promotion 与 Offer 不是 Deal 价

官方 Product Object 说明：

- `coupon=[oneTimeCoupon,snsCoupon]` 描述 Buy Box offer 的 coupon；正数为固定金额优惠，负数为百分比，0 为无该类 coupon。字段总是可访问，但只有使用 `offers` 参数才更新。来源：[Product Object - coupon](https://keepa.com/api-docs/product-object.html#fields).
- `promotions` 是活跃 promotion 数组，目前常见 `type=SNS`；`amount` 是 discounted price，另有 `discountPercent` 与 `snsBulkDiscountPercent`。并非所有促销都能提供，且需要 `offers` 参数更新。来源：[Product Object - promotions](https://keepa.com/api-docs/product-object.html#fields)。
- `offers` 只有使用 `offers` 参数才返回；`liveOffersOrder` 用来从包含历史 offer 的 `offers` 数组中定位当前在售 offer。`offersSuccessful=false` 时不能把缺失 offer 解释为“没有 offer”。来源：[Product Object - offers](https://keepa.com/api-docs/product-object.html#fields)。

当前 `opscli/keepa/product_formatter.py` 已把 Product coupon 解析为金额或百分比，也能拆 Offer 与 Offer 历史；但 `promotions` 仍只进入通用 `product_nested_values`。完善时应新增 `product_promotions` 明细，而不是将 coupon 或 SNS 优惠后的估算实付价放入 `dealPrice`。

如业务必须计算券后价，只能输出类似 `estimatedPriceAfterOneTimeCoupon`，并同时给出：

- `isDerived=true`；
- `basePriceSource`；
- `couponType`；
- 不包含税费、资格、叠加规则等限制说明。

该估算字段不应与 Limited Time Deal、Lightning Deal 或 Prime exclusive price 混用。

## 3. 当前实现缺口

### 3.1 Product formatter

依据 `opscli/keepa/product_formatter.py`：

1. `_add_content_summary()` 只输出 `dealCount`，未输出 `dealType`、`badge`、`accessType`。
2. `deals` 未有专用明细表；主表清理嵌套值后只能在 `product_nested_values` 中逐 path 查找，使用成本高。
3. `CURRENT_FIELD_BY_INDEX` 未包含索引 8 `LIGHTNING_DEAL` 和 33 `PRIME_EXCL`。
4. `_latest_csv_value()` 不理解 Lightning Deal 的未来 `-1` 哨兵语义。
5. `promotions` 没有专用明细表。
6. Product 主行输出的是格式化值，但缺少统一的 `*Source`、`*Raw`、`*IsDerived` 字段，难以让下游区分 Keepa 原值与组合推导。

### 3.2 Statistics formatter

依据 `opscli/keepa/stats_formatter.py`：

1. `PRICE_TYPES` 没有索引 33 `PRIME_EXCL`，导致 `stats_price_types` 中该索引只能作为未知类型处理。
2. `COMMON_ARRAY_COLUMNS` 没有 `stats.current[8]` 与 `stats.current[33]` 的主表友好列。
3. 已经解析 `buyBoxPrice`、`buyBoxShipping`、`buyBoxSavingBasis`、`buyBoxSavingPercentage` 和 landed price，这是 Limited Time Deal 场景可复用的事实价格链路。
4. `buyBoxSavingBasisType`、`buyBoxIsPrimeExclusive`、`buyBoxIsPrimeEligible` 尚未进入主表友好字段。
5. `statsDataFreshness` 目前只按 Buy Box 字段是否存在返回 `available/unverified`，没有结合 Product `offersSuccessful` 与 `lastOffersUpdate` 表达采集新鲜度。

### 3.3 Deal formatter

依据 `opscli/keepa/deal_formatter.py`：

- 当前已正确保留 `current/currentSince/deltaLast/delta/deltaPercent/avg` 指标明细，并为特殊 price type 增加 `deltaReference=AMAZON_OR_NEW`。
- 主表只展开 Amazon、New、Sales Rank、New FBA、Rating、Review Count、Buy Box，未展开 `current[8]` 与 `current[33]`。
- `isLightningDeal` 仅依据 `lightningEnd>0`，符合 Deal Object 自身语义；不应扩展为 Limited Time Deal 判断。
- 字段名 `dealRaw` 容易让使用者误以为它是 Amazon 活动对象，但其内容确实是 Browsing Deals 的原始 Deal Object；建议文档和 schema 描述明确其含义，不必为兼容性贸然改名。

### 3.4 MCP summary 与执行链路

依据 `opscli/keepa/summary.py`、`opscli/mcp/tools/keepa.py`、`opscli/keepa/services/api_manager.py`：

- 固定 `KEEPA_SUMMARY_FIELDS` 只保留标识字段，既没有 Deal 元数据，也没有价格、coupon、Statistics 字段。
- MCP 最终将 `data` 再次压缩为 `data_preview`，因此 formatter 中新增字段若不加入 summary 仍不可见。
- JSON 导出路径直接对 raw rows 调用 `summarize_rows()`；XLSX 路径先 formatter 再进入 MCP 摘要。只修改 Product formatter 会导致 JSON 与 XLSX 的 MCP preview 行为不一致。
- 当前摘要不接收 `scenario`，无法区分 Product、Browsing Deals、Lightning Deals 各自最重要的字段。

## 4. 推荐输出合同

### 4.1 Product 活动事实字段

建议 Product 主表新增以下标量字段，并新增 `product_deals` 明细表逐条保留 `accessType/dealType/badge`：

| 建议字段 | 类型 | 来源与规则 |
| --- | --- | --- |
| `dealMetadataStatus` | enum | 字段缺失=`not_returned`，空数组=`empty`，非空=`available` |
| `hasActiveDealMetadata` | bool/null | 非空=true，空数组=false，字段缺失=null |
| `dealCount` | int/null | 只在 `deals` 为数组时输出 |
| `dealTypesJoined` | string | 原始 `dealType` 去重后连接，保留未知值 |
| `dealBadgesJoined` | string | 原始 `badge` 去重后连接 |
| `dealAccessTypesJoined` | string | 原始 `accessType` 去重后连接 |
| `hasLimitedTimeDealBadge` | bool/null | `deals` 可用时判断是否含 `LIMITED_TIME_DEAL` |
| `hasPriceDealBadge` | bool/null | 只能基于明确维护的价格活动类型集合；不要对所有 badge 返回 true |

这里建议使用 `hasActiveDealMetadata` 而不是无条件使用 `hasActiveDeal`，名称直接表达这是元数据判断。若对外必须保留 `hasActiveDeal`，也应使用三态并附 `hasActiveDealSource=PRODUCT_DEALS_METADATA`。

### 4.2 原生价格事实字段

| 建议字段 | 来源 | 属性 |
| --- | --- | --- |
| `currentLightningDealPrice` | `stats.current[8]`，必要时专用解析 `csv[8]` | Keepa 原生 Lightning price type |
| `currentLightningDealPriceSource` | 常量 `STATS_CURRENT_8` 或 `CSV_8_SPECIAL` | 来源标识 |
| `lightningDealStatus` | `stats.lightningDealInfo` | Keepa 原始时间事实上的状态派生 |
| `currentPrimeExclusivePrice` | `stats.current[33]` 或 `csv[33]` | Keepa 原生 Prime exclusive price type |
| `currentPrimeExclusivePriceSource` | 常量 `STATS_CURRENT_33` 或 `CSV_33` | 来源标识 |
| `currentBuyBoxPrice` | `stats.buyBoxPrice` 或明确记录的 fallback | Buy Box 商品价，不含运费 |
| `currentBuyBoxShipping` | `stats.buyBoxShipping` | Buy Box 运费 |
| `currentBuyBoxLandedPrice` | 上述两字段相加 | 可验证组合推导 |
| `buyBoxSavingBasis` | `stats.buyBoxSavingBasis` | Buy Box 划线参考价 |
| `buyBoxSavingBasisType` | Statistics 同名字段 | `LIST_PRICE/WAS_PRICE` |
| `buyBoxSavingPercentage` | Statistics 同名字段 | Amazon/Keepa 返回的标示百分比 |

所有金额继续同时输出 raw、amount、currency；`-1/-2` 保持不可用语义，不转换为负金额。

### 4.3 Limited Time Deal 的安全组合字段

若产品存在 `LIMITED_TIME_DEAL` 徽标且有可用 Buy Box 事实，可选输出：

| 建议字段 | 示例 | 说明 |
| --- | --- | --- |
| `dealAssociatedBuyBoxLandedPrice` | `125.99` | 这是“活动元数据存在时观察到的 Buy Box landed price” |
| `dealAssociatedPriceSource` | `STATS_BUY_BOX_LANDED` | 明确来源 |
| `dealAssociatedPriceIsDerived` | `true` | 明确为本地组合 |
| `dealAssociatedPriceIsNativeDealPrice` | `false` | 明确不是 Keepa 独立 Deal price field |
| `dealAssociatedPriceReason` | `LIMITED_TIME_DEAL_BADGE_WITH_ACTIVE_BUY_BOX` | 说明组合依据 |

不建议输出以下字段：

```text
currentDealPrice = currentBuyBoxPrice
dealPriceSource = BUY_BOX_INFERRED
```

虽然 `BUY_BOX_INFERRED` 比无标记更好，但 `currentDealPrice` 的主字段名仍容易被下游丢弃来源字段后当作 Keepa 原生 Deal 价。应把“关联/推导”直接编码进字段名。

### 4.4 可用性与新鲜度字段

活动元数据、Buy Box、coupon、promotion 都依赖 offers 更新，应同时输出：

- `offersRequested`：由本次规范化请求参数得出；
- `offersSuccessful`：Product 原始字段；
- `lastOffersUpdateUtc`：Statistics 可用时输出；
- `dealMetadataStatus`；
- `priceFreshnessStatus`：建议枚举 `fresh/available_but_age_unknown/request_failed/not_requested`，不要只用布尔值。

这样 MCP 用户看到 `deals` 缺失时，能区分“确实没有”“没请求 offers”“offers 抓取失败”。

## 5. MCP 摘要完善方案

### 5.1 改为场景化摘要

`summarize_rows()` 建议接收 `scenario`，按场景选择标量字段：

- `product`：ASIN、标题、活动元数据、Lightning/Prime/Buy Box/划线价、coupon、offers 新鲜度。
- `deals`：ASIN、标题、`currentAmazonPrice`、`currentNewPrice`、`currentBuyBoxPrice`、`isLightningDeal`、`lightningEndUtc`；明确这是 Browsing Deals 变化摘要。
- `lightning-deals`：原生 `dealPriceAmount`、`currentPriceAmount`、状态、开始/结束时间、claimed 百分比。

摘要仍保持纯标量和最多 5 行，不把 `deals`、`offers`、`stats` 原始嵌套对象放入 MCP 上下文。

### 5.2 JSON/XLSX 统一摘要来源

不要继续让 JSON 预览摘要 raw rows、XLSX 预览摘要 formatted rows。建议在 API manager 中建立轻量、场景化的 `preview_rows`：

1. 原始响应继续完整保存和导出。
2. 对 Product raw row 调用共享的 Product preview formatter；该 formatter 与完整 Product formatter 复用 Deal、price type、coupon、Statistics 的标量提取函数。
3. JSON 与 XLSX 都将同一批 `preview_rows` 交给 MCP `_compact_public_data()`。
4. `_compact_public_data()` 只做行数压缩，不再次丢弃已经允许的场景字段。

这一调整比单纯扩展全局 `KEEPA_SUMMARY_FIELDS` 更稳妥，因为全局白名单会把不属于其他场景的字段混在一起，也无法从 raw Product 嵌套对象中生成 `dealTypesJoined` 等标量。

### 5.3 Product 示例预览

对存在 Limited Time Deal 的商品，推荐 MCP 返回类似：

```json
{
  "asin": "B0DP4L8HBB",
  "dealMetadataStatus": "available",
  "hasActiveDealMetadata": true,
  "dealTypesJoined": "LIMITED_TIME_DEAL",
  "dealBadgesJoined": "Limited time deal",
  "currentBuyBoxLandedPrice": 125.99,
  "buyBoxSavingBasis": 139.99,
  "buyBoxSavingBasisType": "WAS_PRICE",
  "buyBoxSavingPercentage": 10,
  "dealAssociatedBuyBoxLandedPrice": 125.99,
  "dealAssociatedPriceSource": "STATS_BUY_BOX_LANDED",
  "dealAssociatedPriceIsNativeDealPrice": false,
  "offersSuccessful": true
}
```

其中数值仅为结构示例，应以实际 Keepa 响应为准。该结构能满足看板展示“Limited Time Deal + 当前 Buy Box 价 + 划线参考价”，又不会声称 Keepa 返回了独立 Limited Time Deal price。

## 6. 实施优先级

### P0：纠正数据合同

1. Product formatter 增加 `product_deals` 明细和三态 Deal 元数据摘要。
2. Statistics/Product formatter 输出 `stats.current[8]`、`stats.current[33]`，补齐索引 33 配置。
3. Lightning `csv[8]` 使用专用当前值解析，禁止复用普通末值读取。
4. 输出 `buyBoxSavingBasisType`、Prime 标记和 offers 新鲜度。
5. 不新增无限定来源的 `currentDealPrice`。

### P1：让 MCP 可见且两种导出一致

1. 建立场景化 preview formatter。
2. JSON/XLSX 共用 preview rows。
3. Product preview 暴露活动类型、徽标、原生活动价、Buy Box、划线价与来源标识。

### P2：补全优惠明细

1. 新增 `product_promotions` 明细表。
2. Coupon、Promotion、Deal badge 分开输出，不合并成单一 Deal。
3. 若业务需要券后估算价，使用 `estimated*` 字段并标注限制。

## 7. 回归测试建议

| 用例 | 关键断言 |
| --- | --- |
| `deals` 字段缺失 | `dealMetadataStatus=not_returned`，`hasActiveDealMetadata=null` |
| `deals=[]` | `dealMetadataStatus=empty`，`hasActiveDealMetadata=false` |
| `LIMITED_TIME_DEAL` + Buy Box | 输出 badge 与 Buy Box 事实；不出现无来源 `currentDealPrice` |
| `SELLING_FAST` badge | 不自动判断为价格活动，不产生活动价推导 |
| `stats.current[8]` 有效 | 输出原生 `currentLightningDealPrice` 与来源 |
| `csv[8]` 最后为未来 `-1` | 不把 `-1` 当活动价；结合 `lightningDealInfo` 判断状态 |
| `stats.current[33]` 有效 | 输出原生 `currentPrimeExclusivePrice` |
| `buyBoxSavingBasis` 存在 | 保留 basis、basis type、percentage，不回退到 `LISTPRICE` 覆盖它 |
| `offersSuccessful=false` | Deal/coupon/offer 缺失标记为请求失败或未知，不判断“无活动” |
| JSON 与 XLSX 请求 | MCP `data_preview` 的活动和价格核心字段一致 |
| Browsing Deals `deltaPercent` | 字段保持“均值对当前值变化”语义，不命名为 Amazon 活动折扣率 |

建议在 `tests/keepa/test_product_formatter.py`、`tests/keepa/test_stats_formatter.py`、`tests/keepa/test_deal_formatter.py`、`tests/keepa/test_api_manager.py` 和 MCP Keepa 工具测试中分别覆盖上述合同。

## 8. 最终建议

本次完善应将“Deal”拆成四个不可混淆的概念：

| 概念 | 官方来源 | 建议展示 |
| --- | --- | --- |
| 活动徽标 | Product `deals` | `dealType/badge/accessType`，无价格 |
| 原生活动价格 | `LIGHTNING_DEAL`、`PRIME_EXCL` price type | 按具体活动类型命名价格 |
| 当前成交入口价格 | Statistics / csv 的 Buy Box | 明确命名 Buy Box price/landed price |
| 近期变化商品 | Browsing Deals 的 Deal Object | current、avg、delta 等变化指标 |

针对 `B0DP4L8HBB`，Keepa 能可靠表达的是“存在 `LIMITED_TIME_DEAL` Buy Box 徽标”；在请求 `offers`/`buybox` 且 Statistics 实际返回对应字段时，还能表达当前 Buy Box 与其划线参考价。Keepa Product Object 没有独立 Limited Time Deal price 字段。因此看板可以展示“Limited Time Deal 活动下观察到的 Buy Box 价”，但数据合同必须标注为活动与 Buy Box 的组合关联，不能宣称它是 Keepa 原始 `dealPrice`。
