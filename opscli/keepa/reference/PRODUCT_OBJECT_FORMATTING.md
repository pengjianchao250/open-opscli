# Keepa Product Object 字段格式化方案

> 实现状态：已接入默认格式化导出。实现文件：`opscli/keepa/product_formatter.py`；接入场景：`product`；默认 XLSX 会派生金额、Keepa 时间、图片 URL、类目路径、变体摘要、stats 当前值，并按需追加 `csv_history`、`offers`、`variations` sheet。

> 参考：Keepa Product Object 官方文档 `https://keepa.com/#!discuss/t/product-object/116`。本文用于指导 `opscli keepa` 后续对 Product Object 的展示、导出与结构化解析；原始响应仍应完整保留。

## 1. 总体原则

- `raw.json` 保持 Keepa 原始返回，不改字段、不改单位、不丢结构。
- `result.json` / `xlsx` / 后续分析表只做派生与格式化，必须能追溯到原字段。
- 所有解析先判断 `productType`，再决定字段可用性。
- 所有未知字段、未知 `csv` 索引、未知枚举值保留原值，不做失败中断。
- 字段格式化按“标量字段、对象字段、历史序列、矩阵/索引数组”分层处理。

## 2. `productType` 优先级

| 值 | 含义 | 格式化策略 |
| --- | --- | --- |
| `0` | `STANDARD` | 数据最完整，按全量规则解析。 |
| `1` | `DOWNLOADABLE` | 无价格、评分、offers 数据；相关字段展示为空/不可用。 |
| `2` | `EBOOK` | 同 `DOWNLOADABLE`，价格和 offer 类字段不可强依赖。 |
| `3` | `INACCESSIBLE` | 价格、评分、offers 不可用；sales rank 与 offer count 更新频率低。 |
| `4` | `INVALID` | 无当前数据，仅保留可见基础字段。 |
| `5` | `VARIATION_PARENT` | 重点解析 `variations`，不要按普通子体商品读取价格。 |

## 3. 通用值格式化

| 数据类型 | 典型字段 | 原始格式 | 展示/导出格式 |
| --- | --- | --- | --- |
| Keepa Time | `trackingSince`, `listedSince`, `lastUpdate`, `lastPriceChange`, `lastStockUpdate`, `lastSoldUpdate` | 分钟整数 | 保留原字段，追加 `*UnixSeconds`、`*UnixMilliseconds`、`*Utc`。公式：`(keepaTime + 21564000) * 60`。 |
| 金额 | `competitivePriceThreshold`, `suggestedLowerPrice`, `variableClosingFee`, `fbaFees.pickAndPackFee` | 站点最小货币单位整数 | 保留原值，派生十进制金额；`-1` 视为无报价/不可用。JPY 等无小数币种按站点配置处理。 |
| 日期整数 | `publicationDate`, `releaseDate` | `YYYY` / `YYYYMM` / `YYYYMMDD` / `-1` | 派生 `YYYY`、`YYYY-MM` 或 `YYYY-MM-DD`；`-1` 输出为空。 |
| 尺寸 | `packageHeight`, `packageLength`, `packageWidth`, `itemHeight`, `itemLength`, `itemWidth` | 毫米整数 | 派生 `cm`；`0` / `-1` 输出为空。 |
| 重量 | `packageWeight`, `itemWeight` | 克整数 | 派生 `kg`；`0` / `-1` 输出为空。 |
| 布尔 | `isAdultProduct`, `isSNS`, `offersSuccessful` | `true` / `false` / 缺失 | 导出为布尔或中文“是/否”，缺失和 `null` 区分保留。 |
| 文本 | `title`, `features`, `description`, `shortDescription` | 字符串，少量字段可能含 HTML | 原文保留；展示层可追加去 HTML 的 `*Text` 字段。 |
| ASIN/编码数组 | `eanList`, `upcList`, `gtinList`, `frequentlyBoughtTogether` | 字符串数组 | 列表字段保留 JSON；常用导出可追加 `join` 字段。 |

## 4. 基础对象与数组字段

### 4.1 图片 `images`

- 原始字段包含 `l/m` 文件名与对应高宽，如 `l`, `lH`, `lW`, `m`, `mH`, `mW`。
- 派生完整图片 URL：`https://m.media-amazon.com/images/I/<image name>`。
- XLSX 建议输出：`imagesCount`、`mainImageUrl`、`imageUrls`；原始 `images` 保留 JSON。

### 4.2 类目 `categoryTree` / `categories`

- `categoryTree` 为有序对象数组，元素为 `{catId, name}`。
- `categories` 为类目 ID 数组，`rootCategory` 是根类目 ID。
- XLSX 建议输出：`categoryPathName`、`categoryPathId`、`rootCategory`。

### 4.3 变体 `variations`

- 仅 `productType = 5` 或存在变体时重点解析。
- 每个变体包含 `asin`、可选 `image`、`attributes`。
- `attributes` 建议展平为 `dimension=value`；XLSX 输出一行主商品时保留 `variations` JSON，并追加 `variationCount`、`variationAsins`。
- 如需要变体明细表，应单独生成 `product_variations` 子表，每个变体一行。

### 4.4 A+ / 视频 / 危险品 / Deals

- `aPlus`、`videos`、`hazardousMaterials`、`deals` 均保留 JSON。
- 常用派生字段：`hasAPlus`、`aPlusImageCount`、`videoCount`、`hazardousMaterialCount`、`dealBadges`。
- `aPlus` 需要 `aplus` 参数；`videos`、`deals` 等通常依赖 `offers` 或额外参数更新。

## 5. 历史序列字段

历史数组一般使用扁平数组交替记录：`[keepaTime, value, keepaTime, value, ...]`。

| 字段 | 原始格式 | 解析记录 |
| --- | --- | --- |
| `parentAsinHistory` | `[keepaTime, previousParentAsin, ...]` | `{time, previousParentAsin}`；当前值取 `parentAsin`。 |
| `salesRankReferenceHistory` | `[keepaTime, categoryId, ...]` | `{time, categoryId}`；`-1` 不可用，`-2` launchpad。 |
| `monthlySoldHistory` | `[keepaTime, monthlySold, ...]` | `{time, monthlySold}`。 |
| `couponHistory` | `[keepaTime, oneTimeCoupon, snsCoupon, ...]` | `{time, oneTimeCoupon, snsCoupon}`；正数为金额，负数为百分比。 |
| `buyBoxSellerIdHistory` | `[keepaTime, sellerId, ...]` | `{time, sellerId}`。 |
| `buyBoxUsedHistory` | `[keepaTime, sellerId, condition, isFBA, ...]` | `{time, sellerId, condition, isFBA}`。 |

处理要求：

- 每个 `keepaTime` 均追加 Unix 秒、毫秒与 UTC。
- 非标准步长字段按字段白名单解析，不要用统一二元组误判。
- 空数组、`null`、字段缺失应分别保留语义。

## 6. `csv` 二维历史数组

`csv` 是 Product Object 最复杂字段：第一维是数据类型索引，第二维是该类型的历史序列。

### 6.1 索引映射

| 索引 | 名称 | 值含义 | 序列格式 |
| --- | --- | --- | --- |
| `0` | `AMAZON` | Amazon 自营价格 | `[time, price, ...]` |
| `1` | `NEW` | Marketplace New 价格 | `[time, price, ...]` |
| `2` | `USED` | Used 价格 | `[time, price, ...]` |
| `3` | `SALES` | 销售排名 | `[time, rank, ...]` |
| `4` | `LISTPRICE` | 标价/MSRP | `[time, price, ...]` |
| `5` | `COLLECTIBLE` | Collectible 价格 | `[time, price, ...]` |
| `6` | `REFURBISHED` | Refurbished 价格 | `[time, price, ...]` |
| `7` | `NEW_FBM_SHIPPING` | New FBM 到手价拆分 | `[time, price, shipping, ...]` |
| `8` | `LIGHTNING_DEAL` | Lightning Deal 价格 | `[time, price, ...]` |
| `9` | `WAREHOUSE` | Warehouse 价格 | `[time, price, ...]` |
| `10` | `NEW_FBA` | New FBA 价格 | `[time, price, ...]` |
| `11` | `COUNT_NEW` | New offer 数 | `[time, count, ...]` |
| `12` | `COUNT_USED` | Used offer 数 | `[time, count, ...]` |
| `13` | `COUNT_REFURBISHED` | Refurbished offer 数 | `[time, count, ...]` |
| `14` | `COUNT_COLLECTIBLE` | Collectible offer 数 | `[time, count, ...]` |
| `15` | `EXTRA_INFO_UPDATES` | offers 相关数据更新时间 | `[time, fetchedOfferCount, ...]` |
| `16` | `RATING` | 评分，`45` 表示 `4.5` 星 | `[time, ratingX10, ...]` |
| `17` | `COUNT_REVIEWS` | 评论/评分数量 | `[time, count, ...]` |
| `18` | `BUY_BOX_SHIPPING` | Buy Box 价格与运费 | `[time, price, shipping, ...]` |
| `19` | `USED_NEW_SHIPPING` | Used Like New 价格与运费 | `[time, price, shipping, ...]` |
| `20` | `USED_VERY_GOOD_SHIPPING` | Used Very Good 价格与运费 | `[time, price, shipping, ...]` |
| `21` | `USED_GOOD_SHIPPING` | Used Good 价格与运费 | `[time, price, shipping, ...]` |
| `22` | `USED_ACCEPTABLE_SHIPPING` | Used Acceptable 价格与运费 | `[time, price, shipping, ...]` |
| `23` | `COLLECTIBLE_NEW_SHIPPING` | Collectible Like New 价格与运费 | `[time, price, shipping, ...]` |
| `24` | `COLLECTIBLE_VERY_GOOD_SHIPPING` | Collectible Very Good 价格与运费 | `[time, price, shipping, ...]` |
| `25` | `COLLECTIBLE_GOOD_SHIPPING` | Collectible Good 价格与运费 | `[time, price, shipping, ...]` |
| `26` | `COLLECTIBLE_ACCEPTABLE_SHIPPING` | Collectible Acceptable 价格与运费 | `[time, price, shipping, ...]` |
| `27` | `REFURBISHED_SHIPPING` | Refurbished 价格与运费 | `[time, price, shipping, ...]` |
| `28` | `EBAY_NEW_SHIPPING` | eBay New 价格与运费 | `[time, price, shipping, ...]` |
| `29` | `EBAY_USED_SHIPPING` | eBay Used 价格与运费 | `[time, price, shipping, ...]` |
| `30` | `TRADE_IN` | Trade-in 价格 | `[time, price, ...]` |
| `31` | `RENTAL` | Rental 价格 | `[time, price, ...]` |
| `32` | `BUY_BOX_USED_SHIPPING` | Used Buy Box 价格与运费 | `[time, price, shipping, ...]` |
| `33` | `PRIME_EXCL` | Prime exclusive New 价格 | `[time, price, ...]` |
| `34` | `COUNT_NEW_FBA` | New FBA offer 数 | `[time, count, ...]` |
| `35` | `COUNT_NEW_FBM` | New FBM offer 数 | `[time, count, ...]` |

### 6.2 解析规则

- 第一维长度不可固定，Keepa 可能新增索引；未知索引用 `CSV_<index>` 保留。
- 普通类型按二元组解析：`{keepaTime, value}`。
- `*_SHIPPING` 类型按三元组解析：`{keepaTime, price, shipping}`。
- 价格字段整数为站点最小货币单位；`-1` 表示该区间无 offer / 缺货 / 不可用。
- `RATING` 需派生真实评分：`rating = value / 10`。
- `EXTRA_INFO_UPDATES` 的值正数表示抓取了全部 offers，负数表示还有更多未抓取 offers，绝对值为本次抓取 offer 数。
- Lightning Deal 当前活动时，历史最后一条可能是未来时间且价格 `-1`，表示结束时间；不要误判为普通缺货。
- eBay 价格匹配准确性弱，应在分析字段中标记 `sourceReliability = low`。

### 6.3 建议输出结构

Product 主行不直接展开完整 `csv`，避免 XLSX 爆列/爆行。建议同时支持：

- 主商品表：保留 `csv` JSON，追加常用当前值/最新值，如 `currentAmazonPrice`、`currentNewPrice`、`currentBuyBoxPrice`、`currentRating`、`currentReviewCount`。
- 历史明细表：`asin`、`csvIndex`、`csvName`、`keepaTime`、`utc`、`value`、`price`、`shipping`、`currencyUnit`。
- 宽表快照：只取每个 `csvName` 最新值、最低值、最高值、近 30/90 天均值等派生指标。

## 7. `stats` 对象

`stats` 仅在请求参数使用 `stats` 时返回。它适合拿当前价、均价、最低/最高价等快照，优先用于“当前值”展示。

格式化策略：

- `current`、`avg`、`avg30`、`avg90` 等数组使用与 `csv` 相同的索引映射。
- 价格索引按金额转换，计数/排名索引保持整数，`RATING` 除以 `10`。
- `min` / `max` 类结构通常含时间和值，需同时派生 UTC。
- 主商品表可以优先从 `stats.current` 取当前价，缺失时再回退到 `csv` 最新记录。

## 8. `offers` 与 offer 相关字段

`offers` 仅在 `offers` 参数使用时返回，且包含历史 offer 与当前 offer。

| 字段 | 策略 |
| --- | --- |
| `offers` | 原始 JSON 保留；如导出明细，单独生成 `product_offers` 子表。 |
| `liveOffersOrder` | 当前 Amazon offer 页排序索引，用它从 `offers` 中选当前有效 offers。 |
| `offersSuccessful` | 标记 fresh offer 是否成功获取；失败时不要把缺失 offer 当作无竞争。 |
| `buyBoxEligibleOfferCounts` | 8 位数组固定映射：New FBA、New FBM、Used FBA、Used FBM、Collectible FBA、Collectible FBM、Refurbished FBA、Refurbished FBM。 |
| `availabilityAmazon` | 枚举值保留原始码，并派生可读状态；不要与价格是否为 `-1` 简单等同。 |

## 9. 优惠、费用与单位

### 9.1 Coupon

- `coupon` 为 `[oneTimeCoupon, snsCoupon]`。
- 正数：绝对金额优惠，按金额单位转换。
- 负数：百分比优惠，绝对值为百分比。
- `0`：对应类型无优惠。

### 9.2 Promotion

- `promotions` 为对象数组，常见 `type = SNS`。
- `amount` 按金额转换，`discountPercent` 和 `snsBulkDiscountPercent` 保留百分比整数。

### 9.3 FBA / Referral Fee

- `fbaFees.pickAndPackFee`、`variableClosingFee` 按金额转换。
- `referralFeePercentage` 直接按百分比展示。
- `fbaFees.lastUpdate` 按 Keepa Time 转 UTC。

## 10. 缺失值与特殊值

| 原始值 | 语义 | 导出建议 |
| --- | --- | --- |
| 字段缺失 | 当前请求参数未返回或 Keepa 未提供 | 不补默认值；可派生 `has<Field>=false`。 |
| `null` | 明确无数据 | 保留为空单元格或 JSON `null`。 |
| `-1` | 多数数值字段表示不可用；价格字段常表示无 offer | 展示为空，并保留原始字段。 |
| `0` | 对时间/尺寸字段可能表示不可用，对计数字段可能是有效 0 | 必须按字段语义处理。 |
| 空字符串 | 文档中部分 sellerId 可用空字符串表示无资格者 | 保留空字符串，不自动转 `null`。 |

## 11. 与当前 `opscli` 实现的对应关系

- `opscli/keepa/services/api_manager.py` 当前会保存 `raw.json`，并对 normalized `rows` 调用 `add_keepa_time_conversions`。
- `opscli/keepa/time.py` 已能给二元 `[time, value, ...]` 序列追加 `csvUnixSeconds` 等派生字段。
- 当前逻辑不应直接覆盖 Product Object 原字段；新增 Product formatter 时建议作为独立模块挂在导出/展示层。
- 当前 `_looks_like_pair_series` 不适合覆盖 `*_SHIPPING` 三元组、`couponHistory`、`buyBoxUsedHistory` 等非二元历史字段；后续实现应按字段名/`csv` 索引白名单解析。
- `opscli/keepa/export/xlsx.py` 当前对 dict/list 做 JSON 字符串化；若要更友好导出，建议先实现“主商品表 + 历史/offer/variation 子表”的拆分策略。

## 12. 后续实现建议

1. 新增 `product_formatter.py`，输入单个 Product Object，输出 `main_row` 与可选子表：`csv_history_rows`、`offer_rows`、`variation_rows`。
2. 新增 `csv` 索引映射常量，明确每个索引的数据类型：`price`、`rank`、`count`、`rating`、`shipping_price`、`event`。
3. 新增站点货币配置，至少覆盖 `domainId` 到币种、小数位、Amazon 域名的映射。
4. 将 Keepa Time 派生逻辑扩展为字段白名单解析，避免把非时间整数误转。
5. XLSX 导出支持多 sheet：`products`、`csv_history`、`offers`、`variations`；大数据量继续回退 JSON。
6. 文档与实现都必须保留未知字段，避免 Keepa 新增字段造成解析失败。

## Keepa Time Minutes

Time format used for all timestamps. To convert to an uncompressed Unix epoch time:

- For milliseconds: (keepaTime + 21564000) * 60000
- For seconds: (keepaTime + 21564000) * 60
