---
name: ops-keepa-internal
mcp-version: v1.0.0
description: Keepa MCP 中文自然语言使用规范，用于通过 keepa_* 工具查询商品、关键词、类目、卖家、折扣、热销等数据并导出表格。
visibility: internal
---

# ops-keepa MCP

这是 `keepa_spec_must_read` 读取的内部 MCP 使用规范，放在
`opscli/keepa/reference/` 下，不作为可安装用户 Skill 暴露。

用户大多数会用中文自然语言提需求，Agent 应优先把中文意图转换成
`keepa_run` 的 `scenario + site + params`，再执行工具。

## 工具列表

- `keepa_spec_must_read`: read this guide before first use.
- `keepa_scenarios`: list supported Keepa scenarios.
- `keepa_run`: run a Keepa scenario and save request/response/export files. Default export is XLSX.
- `keepa_job_status`: read a saved task result by `job_id`.
- `keepa_export`: read export path or cloud URL, filename, format, and MIME type.

不要向用户推荐或暴露单独的 token 状态查询。Keepa 额度由系统内部管理。

## 中文自然语言流程

1. 识别用户要查什么：商品、关键词搜索、筛选、类目、卖家、热销、折扣、秒杀。
2. 识别站点：用户未指定时默认 `US`。用户说美国/美区/亚马逊美国都映射为 `US`。
3. 抽取必填参数：ASIN、关键词、类目 ID、seller ID 等。
4. 参数足够时直接调用 `keepa_run`，不要先反复确认。
5. 参数不足时只问缺失的必填项，最多问 1 个短问题。
6. 默认导出 XLSX，除非用户明确要求 JSON 或“后端对比原始数据”。
7. 回答用户时只说查询完成、站点、场景、行数、导出文件/链接。不要展示 token 消耗、剩余额度、API Key、账号来源。

推荐回答格式：

```text
已完成 Keepa 商品关键词搜索并导出表格。

站点：US
关键词：flashlight
返回行数：20
导出文件：<优先使用 export.url，没有则使用 export.path>
```

如果额度不足或等待卡住：

```text
Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。
```

## 认证

Keepa uses an API key. The backend first tries OPS integration account `platform=keepa`.
Store the Keepa API key in the integration account password field. If that is unavailable,
the local fallback is `OPSCLI_KEEPA_API_KEY`.

Agent 不需要让用户感知 API Key 或账号配置。除非是开发/运营排障，不要在用户回答中提账号来源。

## 额度

Keepa API quota is managed internally. Do not expose account source, API key,
or standalone token status to end users. If quota is insufficient or the request
is stuck waiting for quota, tell the user to retry later or contact operations.

Internal saved files may preserve Keepa quota fields when available:

- `tokensLeft`
- `refillIn`
- `refillRate`
- `tokensConsumed`
- `tokenFlowReduction`

`keepa_run` performs an internal precheck with `estimated_tokens + reserve_tokens`.
If balance is below the threshold, it returns a user-facing insufficient-quota
message unless `force=true` or `wait=true`. `estimated_tokens` is only a warning
estimate; Keepa's returned `tokensConsumed` is authoritative.

## 导出和落盘

Every run writes files under the task directory:

- `params.json`: original request, scenario metadata, API account summary, normalized Keepa params, quota precheck.
- `raw.json`: endpoint, normalized request params, before/after token status, raw Keepa response.
- `result.json`: normalized task result and export metadata.
- `<job_id>.xlsx`: default user-facing export with Chinese headers.
- `<job_id>.json`: optional debug export when `export_format=json`, containing rows, raw response, request params, and quota fields.

These files are intentionally retained for backend comparison and debugging.
When OPS file upload is available, the export is uploaded to `keepa/exports` and
`export.url` points to the cloud download URL. If upload fails, keep using the
local `export.path` and do not treat the task as failed.

XLSX 中文表头不是 Keepa 官方提供的，是本地导出层按场景映射生成：

- 商品类：ASIN、父ASIN、标题、品牌、产品组、最近更新(UTC)、评分、评论数、价格、链接等。
- 卖家类：Seller ID、店铺名称、最近更新(UTC)、评分、评分数、店铺ASIN数、店铺链接等。
- 类目类：类目ID、类目名称、父类目ID、产品数量、最高排名、子类目等。

`raw.json` 保留 Keepa 原始字段，后端对比以 `raw.json` 为准；XLSX 用于用户查看。

## Keepa Time Minutes

Keepa uses minute-based timestamps in many API payloads. The timezone is UTC.

- Unix seconds: `(keepa_time + 21564000) * 60`
- Unix milliseconds: `(keepa_time + 21564000) * 60000`

Example:

```text
keepa_time = 7588958
seconds = (7588958 + 21564000) * 60 = 1749177480
milliseconds = 1749177480000
utc = 2025-06-06T02:38:00Z
```

`raw_response` is never modified. Normalized `rows` add derived fields for common
Keepa time keys, for example `lastUpdateUnixSeconds`, `lastUpdateUnixMilliseconds`,
and `lastUpdateUtc`. For Keepa `csv` time/value arrays, normalized rows also add
`csvUnixSeconds` while preserving the original `csv`.

## 场景和必填参数

| 用户说法 | scenario | 必填参数 | 常用可选参数 | 说明 |
| --- | --- | --- | --- | --- |
| 查商品详情、查 ASIN、查价格历史 | `product` | `asin`/`asins` 或 `code`/`codes` | `stats`, `history`, `offers`, `buybox`, `rating`, `days`, `update` | ASIN 或 UPC/EAN/ISBN-13 查询。最多 100 个；带 `offers` 时最多 20 个。 |
| 关键词搜商品、搜索 flashlight | `product-search` | `keyword` 或 `term` | `page`, `stats`, `history`, `update`, `asins_only` | 关键词搜索 Amazon 商品。 |
| 按条件筛商品、Product Finder | `product-finder` | 无固定必填；建议传 `selection` | `selection.perPage`, `selection.sort`, 各类筛选字段 | 复杂筛选走 Keepa Product Finder selection。 |
| 搜类目、查类目关键词 | `category-search` | `keyword` 或 `term` | `parents` | 按类目名称关键词搜索。 |
| 查类目详情、类目 ID | `category-lookup` | `category`/`categories` | `parents` | 按 category id 查询，最多 10 个。 |
| 查卖家、查店铺 | `seller` | `seller`/`sellers` | `storefront`, `update` | 按 seller id 查询，可拉 storefront ASIN。 |
| 查 Top Sellers、头部卖家 | `top-seller` | 无 | 无 | 查询指定站点评分最多的 marketplace sellers。 |
| 查热销、Best Sellers | `bestsellers` | `category` 或 `productGroup` | 无 | 按 category node 或 product group 获取热销 ASIN。 |
| 查折扣、Deals | `deals` | 无固定必填；建议传 `selection` | `selection` | 查询最近变动和折扣商品，单次最多约 150 条。 |
| 查秒杀、Lightning Deals | `lightning-deals` | 无 | `asin` | 当前和即将开始的秒杀，可按 ASIN 过滤。 |

参数不足时的追问口径：

- `product` 缺 ASIN/code：`请提供要查询的 ASIN，或 UPC/EAN/ISBN-13 code。`
- `product-search` 缺关键词：`请提供要搜索的关键词。`
- `category-lookup` 缺类目 ID：`请提供 Keepa/Amazon category id。`
- `seller` 缺 seller ID：`请提供 seller ID。`
- `bestsellers` 缺类目：`请提供 category id 或 productGroup。`

## 自然语言到参数映射

| 中文表达 | 调用参数 |
| --- | --- |
| `跑 keepa product-search，关键词 flashlight，导出结果` | `scenario="product-search"`, `site="US"`, `params={"keyword":"flashlight"}` |
| `查美区 ASIN B0088PUEPK 的商品详情` | `scenario="product"`, `site="US"`, `params={"asin":"B0088PUEPK","stats":30,"history":false}` |
| `查这个 ASIN 的价格历史` | `scenario="product"`, `params={"asin":"...","history":true,"stats":30}` |
| `只要 ASIN 列表` | 对 `product-search` 加 `params={"asins_only":true}` |
| `查 seller A2L77EE7U53NWQ 店铺商品` | `scenario="seller"`, `params={"seller":"A2L77EE7U53NWQ","storefront":true}` |
| `查 172282 类目的 best sellers` | `scenario="bestsellers"`, `params={"category":"172282"}` |
| `查 flashlight 的类目` | `scenario="category-search"`, `params={"keyword":"flashlight"}` |

## 默认参数建议

- 用户未指定站点：`site="US"`。
- 用户只说“导出”：使用默认 `export_format="xls"`。
- 用户只说“查商品详情”：建议 `stats=30`, `history=false`，减少返回体积。
- 用户说“价格历史/历史曲线”：使用 `history=true`。
- 用户说“只要 ASIN”：使用 `asins_only=true`。
- 用户要求后端比对、原始数据、JSON：使用 `export_format="json"`。

## 用户回答规范

回答要站在业务用户视角，不解释 API token、账号、内部请求参数、原始 JSON 结构。

成功时包含：

- 查询已完成。
- 站点。
- 查询对象，例如关键词、ASIN、seller ID、category id。
- 返回行数。
- 导出文件链接，优先展示 `export.url`；没有云端 URL 时展示 `export.path`。

成功时不要包含：

- token 消耗。
- 剩余 tokens。
- API Key 后缀。
- 账号来源。
- `params.json`、`raw.json` 等内部调试文件，除非用户明确问“后端对比文件在哪里”。

当 `export.url` 是云端链接时，优先回答：

```text
导出文件：<export.url>
```

当只有本地文件时，回答：

```text
导出文件：<export.path>
```

当用户问“导出的数据准确吗/字段怎么来的”：

```text
表格字段来自 Keepa 原始响应，本地导出层只做中文表头、时间、价格、评分等便于查看的转换；原始响应保存在 raw.json，可用于后端对比。
```

## 站点

Use Keepa site codes: `US`, `GB`/`UK`, `DE`, `FR`, `JP`, `CA`, `IT`, `ES`, `IN`, `MX`, `BR`.

中文站点映射：

| 中文 | site |
| --- | --- |
| 美国、美区、US | `US` |
| 日本、日区、JP | `JP` |
| 德国、德区、DE | `DE` |
| 英国、英区、UK/GB | `GB` |
| 法国、法区、FR | `FR` |
| 加拿大、CA | `CA` |
| 意大利、IT | `IT` |
| 西班牙、ES | `ES` |
| 印度、IN | `IN` |
| 墨西哥、MX | `MX` |
| 巴西、BR | `BR` |

## 调用示例

Product:

```json
{
  "scenario": "product",
  "site": "US",
  "params": {
    "asins": ["B0088PUEPK"],
    "stats": 30,
    "history": false
  }
}
```

Seller storefront:

```json
{
  "scenario": "seller",
  "site": "US",
  "params": {
    "seller": "A2L77EE7U53NWQ",
    "storefront": true
  },
  "force": true
}
```

Product search with default XLSX export:

```json
{
  "scenario": "product-search",
  "site": "US",
  "params": {
    "keyword": "flashlight",
    "page": 0
  }
}
```

对应中文需求：

```text
跑 keepa product-search，关键词 flashlight，导出结果
```

Use JSON export only for backend comparison:

```json
{
  "scenario": "product-search",
  "site": "US",
  "params": {
    "keyword": "flashlight"
  },
  "export_format": "json"
}
```

Product Finder:

```json
{
  "scenario": "product-finder",
  "site": "US",
  "params": {
    "selection": {
      "current_SALES_gte": 1,
      "current_SALES_lte": 5000,
      "sort": [["current_SALES", "asc"]],
      "perPage": 50
    }
  }
}
```
