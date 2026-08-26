# Keepa Deal Object 字段格式化方案

> 实现状态：已接入默认格式化导出。实现文件：`opscli/keepa/deal_formatter.py`；接入场景：`deals`；默认 XLSX 会派生图片、Keepa 时间、Warehouse 成色、Lightning 标记、常用 current 指标，并追加 `deal_metrics` 指标展开 sheet。

> 参考：Keepa Deal Object 官方文档 `https://keepa.com/#!discuss/t/deal-object/412`。本文用于指导 `opscli keepa` 后续对 Deal Object 的展示、导出与结构化解析；原始响应仍应完整保留。

## 1. 总体原则

- `raw.json` 保持 Keepa 原始返回，不改字段、不改单位、不丢结构。
- Deal Object 表示近期发生价格、排名或促销变化的商品摘要，不等同于完整 Product Object。
- 金额字段使用 Amazon 站点最小货币单位整数，展示层再按站点币种派生十进制金额。
- 所有 Keepa Time Minutes 字段保留原值，并派生 Unix 秒、毫秒与 UTC。
- `current`、`currentSince`、`deltaLast` 等一维数组按 Product Object 的 `csv` price type 索引解释。
- `delta`、`deltaPercent`、`avg` 等二维数组第一维是时间窗口，第二维是 price type。
- 所有未知字段、未知 price type、未知枚举值保留原值，不因 Keepa 新增字段导致解析失败。

## 2. 字段结构

| 字段 | 原始类型 | 语义 | 格式化策略 |
| --- | --- | --- | --- |
| `asin` | `String` | 商品 ASIN | 保留原值，按文本导出。 |
| `parentAsin` | `String` | 父 ASIN | 保留原值，缺失或空值不自动回填。 |
| `title` | `String` | 商品标题，少量场景可能含未转义 HTML | 原文保留；展示层可追加去 HTML 的 `titleText`。 |
| `rootCat` | `Long` | 商品根类目节点 ID，`0` 或 `9223372036854775807` 表示未知 | 保留原值；导出时按文本处理，避免 Excel 科学计数法。 |
| `categories` | `Long[]` | 商品所在 Amazon 类目节点 ID 列表 | 保留 JSON；常用导出可追加 `categoryIds` join 字段。 |
| `image` | `Integer[]` | 主图文件名的 US-ASCII 字符码数组 | 保留原数组，派生 `imageName`、`imageUrl`。 |
| `current` | `Integer[]` | 最近更新时间点的当前价格/排名 | 按 price type 索引展开，价格按金额单位转换，排名/计数字段保持整数。 |
| `currentSince` | `Integer[]` | 当前值开始生效时间 | 按 price type 索引展开，每个值按 Keepa Time 转 UTC；无效值保留。 |
| `deltaLast` | `Integer[]` | 上一次值与当前值差值 | 按 price type 索引展开；价格差值派生金额差，排名差值保留整数。 |
| `delta` | `Integer[][]` | 各时间窗口均值与当前值差值 | 第一维按 date range，第二维按 price type 展开。 |
| `deltaPercent` | `Integer[][]` | `delta` 对应百分比变化 | 第一维按 date range，第二维按 price type 展开，保留百分比整数。 |
| `avg` | `Integer[][]` | 各时间窗口加权均值 | 第一维按 date range，第二维按 price type 展开；day 窗口实际为最近 48 小时均值。 |
| `lastUpdate` | `Integer` | Deal 信息最近更新时间 | 保留原值，追加 `lastUpdateUnixSeconds`、`lastUpdateUnixMilliseconds`、`lastUpdateUtc`。 |
| `creationDate` | `Integer` | 请求 price types 最近一次价格/值变化时间，`-1` 表示从未采集 | 保留原值；非 `-1` 时派生 UTC。 |
| `lightningEnd` | `Integer` | Lightning Deal 计划结束时间，仅秒杀适用，其他为 `0` | 保留原值；大于 `0` 时派生 UTC，并追加 `isLightningDeal`。 |
| `warehouseCondition` | `Integer` | 最低 Warehouse Deal 的成色枚举 | 保留原码，派生 `warehouseConditionText`。 |
| `warehouseConditionComment` | `String` | 最低 Warehouse Deal 的 offer 备注 | 原文保留；无 Warehouse Deal 时可为 `null`。 |

## 3. 索引映射

### 3.1 Price Type 索引

Deal Object 的 `current`、`currentSince`、`deltaLast`、`delta`、`deltaPercent`、`avg` 均复用 Product Object `csv` 字段的 price type 索引。

| 索引 | 名称 | 值类型 | 格式化策略 |
| --- | --- | --- | --- |
| `0` | `AMAZON` | 价格 | 最小货币单位整数转十进制金额；`-1` 表示不可用。 |
| `1` | `NEW` | 价格 | Marketplace New 价格；不含运费。 |
| `2` | `USED` | 价格 | Used 价格；不含运费。 |
| `3` | `SALES` | 销售排名 | 保持整数；数值下降通常表示排名变好。 |
| `4` | `LISTPRICE` | 价格 | 标价/MSRP。 |
| `5` | `COLLECTIBLE` | 价格 | Collectible 价格。 |
| `6` | `REFURBISHED` | 价格 | Refurbished 价格。 |
| `7` | `NEW_FBM_SHIPPING` | 到手价/运费相关 | Deal Object 中按文档仍是 price type 槽位，保留原值并按 Product csv 规则解释。 |
| `8` | `LIGHTNING_DEAL` | 价格 | Lightning Deal 价格。 |
| `9` | `WAREHOUSE` | 价格 | Warehouse 价格。 |
| `10` | `NEW_FBA` | 价格 | New FBA 价格。 |
| `11` | `COUNT_NEW` | offer 数 | 保持整数。 |
| `12` | `COUNT_USED` | offer 数 | 保持整数。 |
| `13` | `COUNT_REFURBISHED` | offer 数 | 保持整数。 |
| `14` | `COUNT_COLLECTIBLE` | offer 数 | 保持整数。 |
| `15` | `EXTRA_INFO_UPDATES` | offer 抓取信息 | 正负号语义沿用 Product Object。 |
| `16` | `RATING` | 评分 x10 | 派生真实评分 `rating = value / 10`。 |
| `17` | `COUNT_REVIEWS` | 评论/评分数量 | 保持整数。 |
| `18` | `BUY_BOX_SHIPPING` | Buy Box 到手价/运费相关 | 保留原值，按 Product csv 规则解释。 |
| `19+` | 其他 Product csv 索引 | 价格/计数/事件 | 用 `CSV_<index>` 保留，已知索引按 Product Object 映射补名称。 |

实现时不要把数组长度写死；Keepa 可能新增 price type。

### 3.2 Date Range 索引

| 索引 | 名称 | 含义 | 格式化策略 |
| --- | --- | --- | --- |
| `0` | `day` | 最近 24 小时；`avg` 实际为最近 48 小时均值 | 输出字段后缀建议用 `Day`，说明中标注 `avg` 特例。 |
| `1` | `week` | 最近 7 天 | 输出字段后缀建议用 `Week`。 |
| `2` | `month` | 最近 31 天 | 输出字段后缀建议用 `Month`。 |
| `3` | `days90` | 最近 90 天 | 输出字段后缀建议用 `90Days`。 |

二维数组展开时建议字段命名为 `{metric}_{dateRange}_{priceType}`，例如 `deltaPercent_week_NEW`。

## 4. 通用值格式化

| 数据类型 | 典型字段 | 原始格式 | 展示/导出格式 |
| --- | --- | --- | --- |
| Keepa Time | `lastUpdate`、`creationDate`、`lightningEnd`、`currentSince[]` | 分钟整数 | 保留原值，追加 Unix 秒、毫秒与 UTC；`-1`、`0` 按字段语义处理。 |
| 金额 | `current[]`、`deltaLast[]`、`delta[][]`、`avg[][]` 中的价格索引 | 站点最小货币单位整数 | 保留原值，派生十进制金额；`-1` 输出为空或不可用。 |
| 百分比 | `deltaPercent[][]` | 整数百分比 | 保留整数，可追加 `%` 展示字段。 |
| 排名 | `SALES` 索引 | 整数 | 保持整数；分析层可派生排名改善/恶化方向。 |
| 评分 | `RATING` 索引 | 评分 x10 | 派生 `rating = value / 10`。 |
| 图片 | `image` | ASCII code 数组 | 转为 `imageName`，再派生 `https://images-na.ssl-images-amazon.com/images/I/<imageName>`。 |
| 类目 ID | `rootCat`、`categories` | long / long array | 按文本导出；可派生 Amazon 类目链接。 |
| 特殊值 | `-1`、`0`、`null`、字段缺失 | 依字段而定 | 保留原语义，不统一转空。 |

## 5. Warehouse 与 Lightning Deal

### 5.1 Warehouse 成色枚举

| 值 | 含义 | 格式化策略 |
| --- | --- | --- |
| `0` | 未找到 Warehouse Deal 或成色未知 | `warehouseConditionText = unknown_or_none`。 |
| `2` | Used - Like New | `warehouseConditionText = used_like_new`。 |
| `3` | Used - Very Good | `warehouseConditionText = used_very_good`。 |
| `4` | Used - Good | `warehouseConditionText = used_good`。 |
| `5` | Used - Acceptable | `warehouseConditionText = used_acceptable`。 |

`warehouseConditionComment` 为最低 Warehouse Deal 的 offer comment；没有 Warehouse Deal 时为 `null`，不要自动填空字符串。

### 5.2 Lightning / Prime exclusive / Warehouse 差值规则

- `LIGHTNING_DEAL`、`PRIME_EXCL`、`WAREHOUSE` 对应 price type 的 `deltaLast`、`delta`、`deltaPercent` 不以同 price type 的历史值为参考。
- Keepa 文档说明这些类型会以 Amazon 或 New 价格作为参考价。
- 展示和分析时应追加 `deltaReference = AMAZON_OR_NEW`，避免误读为“自身历史变化”。
- `lightningEnd > 0` 时可派生 `isLightningDeal = true`、`lightningEndUtc`。

## 6. 建议输出结构

Deal Object 建议同时支持“Deal 主表”和“指标展开表”。XLSX 单 sheet 简化导出时优先使用 Deal 主表，一行一个 Deal Object。

### 6.1 Deal 主表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `asin` | `asin` | 商品 ASIN。 |
| `parentAsin` | `parentAsin` | 父 ASIN。 |
| `title` | `title` | 商品标题原文。 |
| `titleText` | 派生 | 可选，去 HTML 后标题。 |
| `rootCat` | `rootCat` | 根类目 ID，按文本导出。 |
| `categories` | `categories` | 原始类目数组 JSON。 |
| `imageName` | `image` | ASCII code 转文件名。 |
| `imageUrl` | 派生 | Amazon 图片 URL。 |
| `lastUpdate` | `lastUpdate` | Keepa Time Minutes 原值。 |
| `lastUpdateUtc` | 派生 | Deal 最近更新时间 UTC。 |
| `creationDate` | `creationDate` | 最近价格/值变化时间原值。 |
| `creationDateUtc` | 派生 | `creationDate != -1` 时输出。 |
| `lightningEndUtc` | 派生 | `lightningEnd > 0` 时输出。 |
| `warehouseCondition` | `warehouseCondition` | 原始成色枚举。 |
| `warehouseConditionText` | 派生 | 可读成色。 |
| `warehouseConditionComment` | `warehouseConditionComment` | Warehouse offer 备注。 |
| `currentAmazonPrice` | `current[0]` | Amazon 当前价，按金额转换。 |
| `currentNewPrice` | `current[1]` | New 当前价，按金额转换。 |
| `currentSalesRank` | `current[3]` | 当前 sales rank。 |
| `currentRating` | `current[16]` | 当前评分，除以 10。 |
| `currentReviewCount` | `current[17]` | 当前评论/评分数量。 |
| `dealRaw` | 原始对象 | 完整 Deal Object JSON，便于追溯。 |

### 6.2 指标展开表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `asin` | `asin` | 商品 ASIN。 |
| `metric` | `current` / `currentSince` / `deltaLast` / `delta` / `deltaPercent` / `avg` | 指标名称。 |
| `dateRangeIndex` | 二维数组第一维 | 仅 `delta`、`deltaPercent`、`avg` 有值。 |
| `dateRangeName` | 派生 | `day`、`week`、`month`、`days90`。 |
| `priceTypeIndex` | 数组下标 | Product csv price type 索引。 |
| `priceTypeName` | 派生 | 如 `AMAZON`、`NEW`、`SALES`。 |
| `rawValue` | 数组值 | Keepa 原始值。 |
| `formattedValue` | 派生 | 金额、评分、UTC 或原整数。 |
| `valueKind` | 派生 | `money`、`rank`、`count`、`rating`、`time`、`percent`。 |
| `currency` | 派生 | price type 为金额时输出站点币种。 |
| `deltaReference` | 派生 | Lightning / Prime exclusive / Warehouse 差值参考说明。 |

## 7. 与 Product Object 的差异

- Deal Object 是商品摘要和近期变化指标；Product Object 是完整商品详情。
- Deal Object 不包含完整 `csv` 历史序列、`stats`、`offers`、`variations`、`categoryTree` 等复杂结构。
- Deal Object 的价格/排名数组复用 Product Object `csv` price type 索引，但不是历史序列。
- Deal Object 的 `avg` 是按日期窗口聚合后的加权均值；`avg[0]` 的 day 窗口实际是最近 48 小时均值。
- `creationDate` 在 Deal Object 中表示请求 price types 最近一次价格/值变化时间，不等同于 Product Object 的商品创建时间。
- 如需完整商品信息，应从 Deal Object 取 `asin` 后调用 Product Object 查询。

## 8. 与当前 `opscli` 实现的对应关系

- `opscli/keepa/api/scenarios.py` 已有 `deals` 场景，对应 Keepa `deal` endpoint；`selection.priceTypes` 必填且只能包含一个 price type 索引。
- `opscli/keepa/services/api_manager.py` 当前会优先识别响应中的 `deals.dr` 或 `deals.deals`，导出时一行一个 Deal Object。
- `raw_response_to_export_rows` 会保留除 `deals` 以外的顶层响应字段，并设置 `rowSource = deals`。
- `opscli/keepa/time.py` 当前只会自动处理常见标量时间字段；`currentSince[]`、二维指标数组需要后续 Deal formatter 按字段白名单解析。
- `opscli/keepa/export/xlsx.py` 当前对 dict/list 做 JSON 字符串化；Deal Object 友好导出应先在 formatter 层展开常用字段。

## 9. 后续实现建议

1. 新增 `deal_formatter.py`，输入 Deal Object，输出 `main_row` 与 `metric_rows`。
2. 复用 Product Object 的 price type 映射常量，避免 Deal 和 Product 索引解释不一致。
3. 新增 date range 映射常量：`day`、`week`、`month`、`days90`。
4. 新增 `image` ASCII code 数组到 `imageName` / `imageUrl` 的转换函数。
5. 对 `currentSince` 做按 price type 的 Keepa Time 转换，不要用通用二元历史序列逻辑误判。
6. 主表优先输出 Amazon/New/Buy Box/Sales Rank/Rating/Review Count 等常用字段，完整数组继续保留 JSON。
7. Lightning / Prime exclusive / Warehouse 的差值字段需标记参考价来源，避免业务分析误读。
8. 文档与实现都必须保留未知字段，避免 Keepa 新增字段造成解析失败。
