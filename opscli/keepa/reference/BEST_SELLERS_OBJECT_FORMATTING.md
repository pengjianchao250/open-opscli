# Keepa Best Sellers Object 字段格式化方案

> 实现状态：已接入默认格式化导出。实现文件：`opscli/keepa/best_sellers_formatter.py`；接入场景：`bestsellers`；默认 XLSX 主表输出带 `bestSellerRank` 的 ASIN 明细，并追加 `best_sellers_list` 榜单汇总 sheet。

> 参考：Keepa Best Sellers Object 官方文档 `https://keepa.com/#!discuss/t/best-sellers-object/1299`。本文用于指导 `opscli keepa` 后续对 Best Sellers Object 的展示、导出与结构化解析；原始响应仍应完整保留。

## 1. 总体原则

- `raw.json` 保持 Keepa 原始返回，不改字段、不改单位、不丢结构。
- Best Sellers Object 是“类目榜单快照”，不是商品详情对象。
- `asinList` 的数组顺序就是榜单顺序，导出明细时用下标加 1 派生 `bestSellerRank`。
- `lastUpdate` 使用 Keepa Time Minutes，需保留原值并派生 Unix 秒、毫秒与 UTC。
- 所有未知字段保留原值，不因 Keepa 新增字段导致解析失败。

## 2. 字段结构

| 字段 | 原始类型 | 语义 | 格式化策略 |
| --- | --- | --- | --- |
| `domainId` | `Integer` | Amazon 站点 ID | 保留原值，按站点映射派生 `domain`、`amazonHost`。 |
| `lastUpdate` | `Integer` | 榜单最近更新时间，Keepa Time Minutes | 保留原字段，追加 `lastUpdateUnixSeconds`、`lastUpdateUnixMilliseconds`、`lastUpdateUtc`。 |
| `categoryId` | `Long` | 请求使用的 Amazon category node ID | 保留为字符串或整数，导出时避免科学计数法；可派生 Amazon 类目链接。 |
| `asinList` | `String[]` | 热销 ASIN 列表，按销量排名从高到低排列 | 保留原数组，导出明细时拆成一行一个 ASIN，并追加 `bestSellerRank`。 |

## 3. 与 Product Object 的差异

- Best Sellers Object 只包含榜单元数据和 ASIN 列表；Product Object 是单个商品详情。
- Best Sellers Object 不包含标题、品牌、价格、评分、销量、`csv`、`stats`、`offers` 等商品详情字段。
- `lastUpdate` 表示榜单更新时间，不是 Product Object 的商品更新时间。
- `categoryId` 是榜单所属类目，不等同于 Product Object 的 `rootCategory` 或 `categories` 全量类目路径。
- 如需商品详情，应先从 `asinList` 取 ASIN，再调用 Product Object 查询。

## 4. 建议输出结构

Best Sellers Object 建议同时支持“榜单主表”和“ASIN 明细表”。

### 4.1 榜单主表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `domainId` | `domainId` | Keepa 站点 ID。 |
| `domain` | 派生 | 站点简称。 |
| `amazonHost` | 派生 | Amazon 域名。 |
| `categoryId` | `categoryId` | 类目节点 ID，按文本导出。 |
| `categoryUrl` | 派生 | Amazon 类目页面链接。 |
| `lastUpdate` | `lastUpdate` | Keepa Time Minutes 原值。 |
| `lastUpdateUtc` | 派生 | 榜单更新时间 UTC。 |
| `asinCount` | `asinList.length` | 榜单 ASIN 数量。 |
| `asinList` | `asinList` | 原始数组，JSON 字符串化保留。 |

### 4.2 ASIN 明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `domainId` | `domainId` | Keepa 站点 ID。 |
| `categoryId` | `categoryId` | 榜单类目 ID，按文本导出。 |
| `lastUpdateUtc` | 派生 | 榜单更新时间 UTC。 |
| `bestSellerRank` | `asinList` 下标 + 1 | 类目热销排名。 |
| `asin` | `asinList[index]` | 商品 ASIN，按文本导出。 |
| `rowSource` | 派生 | 建议固定为 `bestSellersList`。 |

XLSX 单 sheet 简化导出时，优先使用 ASIN 明细表，一行一个 ASIN。

## 5. 与当前 `opscli` 实现的对应关系

- `opscli/keepa/api/scenarios.py` 已有 `bestsellers` 场景，对应 Keepa `bestsellers` endpoint。
- `opscli/keepa/services/api_manager.py` 当前会优先识别 `bestSellersList.asinList`，并在导出行中把每个 ASIN 展开为 `asin`。
- `raw_response_to_export_rows` 会保留除 `bestSellersList` 以外的顶层响应字段，并设置 `rowSource = bestSellersList`。
- 当前导出层不会自动补 `bestSellerRank`；后续实现 Best Sellers formatter 时应按 `asinList` 下标派生。
- `opscli/keepa/export/xlsx.py` 已包含 `bestSellersListRaw`、`asinListRaw`、`asinList`、`categoryId`、`lastUpdateUtc` 等标题映射，可在此基础上补榜单排名和类目链接。

## 6. 后续实现建议

1. 新增 `best_sellers_formatter.py`，输入 Best Sellers Object，输出 `list_row` 与 `asin_rows`。
2. 导出 ASIN 明细时补 `bestSellerRank`、`asinCount`、`categoryUrl`。
3. `categoryId` 和 `asin` 都按文本导出，避免 Excel 自动改格式。
4. 保留 `bestSellersList` 原始 JSON，便于追溯 Keepa 原始响应。
5. 如后续链路需要商品详情，用 ASIN 明细表作为 Product Object 批量查询输入。
