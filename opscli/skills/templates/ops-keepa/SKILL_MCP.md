---
name: ops-keepa-internal
mcp-version: v1.1.0
description: Keepa MCP 中文自然语言使用规范，用于通过 keepa_* 工具查询商品、关键词、类目、卖家、折扣、热销等数据并导出表格。
visibility: internal
---

# ops-keepa MCP

这是 `keepa_spec_must_read` 读取的内部 MCP 使用规范，位于
`opscli/skills/templates/ops-keepa/` 下，不再单独维护 `opscli/mcp/references/keepa/` 副本。

用户大多数会用中文自然语言提需求，Agent 应优先把中文意图转换成
`keepa_run` 的 `scenario + site + params`，再执行工具。

## Agent 快速执行规则

1. 先把用户话术归类为商品、关键词搜索、筛选、类目、卖家、热销、折扣、秒杀之一。
2. 站点缺省用 `US`；不要因为缺站点而追问。
3. 必填参数齐全时直接执行 `keepa_run`；不要把内部参数确认流程暴露给用户。
4. 如果返回 `无 session_id：请完成授权登录，或传入有效的 session_id` 等授权类提示，先执行 `auth_mcp_login`，再重试 `keepa_run`；不要先误判为场景参数错误。
5. 只缺必填项时最多追问 1 个短问题；一次追问尽量覆盖同一场景的所有必填项。
6. 默认导出用户可读 XLSX；多任务编排、汇总计算或生成分析报告时推荐显式使用 JSON。
7. 最终回复给出业务结果和 `keepa_run` 顶层返回的 MCP 每日调用额度：查询对象、站点、返回行数、导出文件或链接、今日已用和剩余次数。
8. 不主动展示 API Key、账号来源、Keepa token 消耗或 token 余额、内部参数、`params.json`、`raw.json`。
9. 用户不需要额外说“格式化”；默认 XLSX 导出会自动写入本地可读派生字段和明细 sheet。

## 导出格式选择

| 任务目的 | `export_format` | 处理方式 |
| --- | --- | --- |
| 单任务人工查看/留档 | `xls` | 实际交付 `.xlsx` |
| 多任务编排/汇总/分析报告 | `json` | 每个任务都显式传 JSON，终态后统一读取 |
| 用户明确指定格式 | 用户指定值 | 不覆盖用户选择 |

### JSON v2 原始业务响应契约

- 校验 `schema_version="2.0"`，读取顶层 `scenario`、`site` 和 `response`。
- `response` 保留 Keepa 原始业务字段、数组和嵌套对象；直接遍历对象，不按 XLSX 的 `columns + rows` 模型重建。
- 公开 JSON 会移除 `tokensLeft`、`tokensConsumed`、`refillIn`、`refillRate`、`tokenFlowReduction` 等账号额度字段。
- 多任务合并时保留 `job_id/scenario/site` 来源，再按场景响应主字段对齐。
- `keepa_run` 和 `keepa_job_status` 的 `data_preview` 最多只含少量白名单字段；完整数据必须读取 `export.url` 对应的 JSON/XLSX 文件。
- JSON 是可交付的原始业务响应，不包含请求参数、前后 token 状态等内部包装；后端完整核对仍使用内部 `raw.json`。
- 不得把内部 `raw.json`、`result.json` 或服务端路径当作用户导出文件返回。

## 工具列表

- `keepa_spec_must_read`: read this guide before first use. 官方接口细节见 `opscli/skills/templates/ops-keepa/references/OFFICIAL.md`。
- `keepa_scenarios`: list supported Keepa scenarios.
- `keepa_quota_status`: read the current user's MCP daily call quota without consuming a call.
- `keepa_run`: run a Keepa scenario and save request/response/export files. Default export is XLSX with automatic readable formatting. `export_format` accepts `xls`/`xlsx`/`json`; `xls` and `xlsx` both generate `.xlsx`。
- `keepa_job_status`: read a saved task result by `job_id`。
- `keepa_export`: read export path or cloud URL, filename, format, and MIME type。

不要向用户推荐或暴露 Keepa token 状态查询。用户询问今天还能调用几次时，使用 `keepa_quota_status` 查询 MCP 每日调用额度。

## 输入识别规则

- ASIN 通常是 10 位，由大写字母和数字组成，常见形态为 `B0XXXXXXXX` 或 `B00XXXXXXX`。
- 多个 ASIN / seller ID / category id 支持用户用逗号、空格、顿号、换行分隔；调用前规范化为数组或逗号字符串均可。
- UPC/EAN/ISBN-13 等条码走 `code`/`codes`；不要和 `asin`/`asins` 同时传给 `product`。
- 用户同时给 ASIN 和关键词时，以明确动作判断：说“查这个 ASIN”走 `product`，说“搜关键词”走 `product-search`；意图冲突时只追问查询对象类型。
- 用户说“查商品详情”“查商品”时，`product` 默认会带 `history=true` 获取历史价格变化；用户明确说不要历史时再传 `history=false`。
- 用户说“最近 30 天”“近 90 天”时，优先映射为 `stats=30/90`。
- 用户说“只要 ASIN”“只导出 ASIN 列表”时，`product-search` 加 `asins_only=true`。
- `seller` 场景默认带 `storefront=true`，确保返回店铺 ASIN 相关字段；但官方不允许批量 seller ID 与 `storefront=1` 同时使用，批量查多个 seller 时必须传 `storefront=false`，如需店铺 ASIN 列表则按单个 seller 分开查。

## 认证与额度

- 如果当前宿主是通过远端 MCP `api_key` 直接连接 `keepa_*` tools，首次执行前应先完成 `auth_mcp_login`；不要把“已拿到 MCP `api_key`”误当成“已经具备 `keepa_run` 所需的 OPS 登录态”。
- 出现 `无 session_id：请完成授权登录，或传入有效的 session_id`、`未授权`、`请先登录` 这类提示时，优先补做 `auth_mcp_login` 并重试；不要先归因为 Keepa token、场景参数或导出逻辑问题。
- Keepa API Key 由后端读取：优先 OPS integration account `platform=keepa`，本地兜底为 `OPSCLI_KEEPA_API_KEY`。
- 用户执行前想确认今天还能查几次时，调用 `keepa_quota_status`；该工具不消耗调用次数。
- `keepa_run` 响应顶层的 `quota` 是 MCP 每日调用额度，可以向用户展示；Keepa API token 余额仍由系统内部管理。
- `keepa_run` 会做额度预检；额度不足或等待卡住时，只回复用户稍后重试或联系运营人员。
- 内部文件可能保留 `tokensLeft`、`tokensConsumed` 等 Keepa token 字段，仅用于排障，不向普通用户展示。

## 导出、任务与文件边界

Every run writes files under the task directory:

- `params.json`: original request, scenario metadata, API account summary, normalized Keepa params, quota precheck.
- `raw.json`: endpoint, normalized request params, before/after token status, raw Keepa response.
- `result.json`: normalized task result and export metadata.
- `<job_id>.xlsx`: default user-facing export with Chinese headers.
- `<job_id>.json`: Keepa original business response for agent workflows and reports; nested arrays and objects remain JSON values.

- `export.url` 存在时只回复云端链接；否则回复 `export.path`。
- 上传失败但本地导出存在时，不判定任务失败，回复本地文件路径。
- 用户提供 `job_id` 查询结果时用 `keepa_job_status`；只问文件位置时用 `keepa_export`。
- `job_id` 查不到时回复“未找到该 Keepa 任务”，不要暴露内部目录。
- 不向普通用户展示 task directory、`params.json`、`raw.json`、`result.json`，除非明确要求后端比对或排障。

XLSX 中文表头不是 Keepa 官方提供的，是本地导出层按场景映射生成：

- 商品类：ASIN、父ASIN、标题、品牌、产品组、最近更新(UTC)、评分、评论数、价格、链接等。
- 卖家类：Seller ID、店铺名称、最近更新(UTC)、评分、评分数、店铺ASIN数、店铺链接等。
- 类目类：类目ID、类目名称、父类目ID、产品数量、最高排名、子类目等。
- Product Object 默认自动派生金额、Keepa 时间、图片 URL、类目路径、变体摘要、stats 当前值，并在 XLSX 中按需追加 `csv_history`、`offers`、`variations` 明细 sheet。
- Product Object 返回 `stats` 时，默认自动派生 stats 主表字段，并按需追加 `stats_price_types`、`stats_extremes`、`stats_buy_box_sellers`、`stats_offer_snapshot` sheet。
- Product Finder 请求带 `stats=1` 且 Keepa 返回 `searchInsights` 时，默认自动追加 `search_insights`、`search_insight_brands`、`search_insight_sellers`、`search_insight_categories` sheet。
- Best Sellers 默认主表输出带 `bestSellerRank` 的 ASIN 明细，并追加 `best_sellers_list` 汇总 sheet。
- Deals 默认派生图片、Keepa 时间、Warehouse 成色、Lightning 标记、常用 current 指标，并追加 `deal_metrics` 指标展开 sheet。

`raw.json` 保留请求、状态和 Keepa 原始响应的完整内部包装；XLSX 用于多 Tab 人工查看，JSON v2 保留原始业务响应结构并用于编排和分析。

## 字段口径与时间处理

Keepa uses minute-based timestamps in many API payloads. The timezone is UTC.

- Unix seconds: `(keepa_time + 21564000) * 60`
- Unix milliseconds: `(keepa_time + 21564000) * 60000`

- 不在 MCP 使用规范中推断 Keepa 原始价格、评分、排名、评论、Offer 等字段的单位、倍率或空值语义；除非 Keepa 官方文档、接口说明或当前响应字段已明确说明。
- JSON v2 的 `response` 除账号额度字段外不修改业务结构；normalized `rows` 和 XLSX 默认自动补充可读派生字段，如 `lastUpdateUtc`、金额字段、评分星级等。
- `csv` 原始数组保留；Product Object XLSX 会默认把常用 `csv` 历史拆到 `csv_history` 明细 sheet。面向普通用户不要解释原始数组，优先让用户查看 XLSX 可读字段。
- `raw.json` 是后端对比和排障基准；XLSX 是本地导出层生成的用户查看文件。
- 用户追问字段单位、倍率、计算方式或准确性时，不要自行类比卖家精灵或其他数据源；应说明以 Keepa 原始响应、官方文档和后端确认口径为准。

## 官方口径索引

详细官方口径见 `opscli/skills/templates/ops-keepa/references/OFFICIAL.md`；当用户追问字段、token、分页、响应结构或接口限制时，先读取该文件。

- Product Search：`/search`，必填 `domain`、`type=product`、`term`；默认返回 `products`，`asins-only=1` 返回 `asinList`。
- Best Sellers：`/bestsellers`，必填 `domain`、`category`；响应主字段 `bestSellersList.asinList`，不返回完整商品详情。
- Product Finder：`/query`，必填 `domain`、`selection`；selection 是 query JSON，响应只返回 `asinList`，不返回 product objects。
- Seller Information：`/seller`，必填 `domain`、`seller`；响应主字段 `sellers` map，单次最多 100 个 seller ID。
- 关键限制：`seller` 请求 `storefront=1` 时不允许批量 seller ID；批量查多个 seller 时必须传 `storefront=false`。

## 场景和必填参数

| 用户说法 | scenario | 必填参数 | 常用可选参数 | 说明 |
| --- | --- | --- | --- | --- |
| 查商品详情、查 ASIN、查价格历史 | `product` | `asin`/`asins` 或 `code`/`codes` | `stats`, `history`, `offers`, `buybox`, `rating`, `days`, `update`, `code_limit`, `historical_variations` | ASIN 或 UPC/EAN/ISBN-13 查询，最多 100 个；`offers` 表示每个商品的 Offer 数，官方有效范围为 20-100。活动徽标、Coupon 和新鲜 Offer 数据依赖 `offers` 更新。 |
| 关键词搜商品、搜索 flashlight | `product-search` | `keyword` 或 `term` | `stats`, `history`, `update`, `rating`, `asins_only` | 调用 Keepa `/search` 且 `type=product`；默认返回 `products`，传 `asins_only=true` 时返回 `asinList`；当前接口不支持 `page`。 |
| 按条件筛商品、Product Finder | `product-finder` | `selection` 或至少 1 个筛选字段 | `stats`, `selection.page`, `selection.perPage`, `selection.sort`, 各类筛选字段 | 调用 Keepa `/query`；按 Product Finder selection 筛选商品库，返回 `asinList`；带 `stats=1` 时会自动导出 `searchInsights` 明细 sheet。 |
| 搜类目、查类目关键词 | `category-search` | `keyword` 或 `term` | 无 | 按类目名称关键词搜索。 |
| 查类目详情、类目 ID | `category-lookup` | `category`/`categories` | `parents` | 按 category id 查询，最多 10 个。 |
| 查卖家、查店铺 | `seller` | `seller`/`sellers` | `storefront` | 按 seller id 查询；默认不拉 storefront；`storefront=true` 只允许单 seller。 |
| 按条件筛卖家、Seller Finder | `seller-finder` | `selection` 或至少 1 个筛选字段 | `selection.perPage`, `selection.sort`、各筛选字段 | 调用 `/sellerquery`，返回 `sellerIdList`。 |
| 查 Top Sellers、头部卖家 | `top-seller` | 无 | 无 | 查询指定站点评分最多的 marketplace sellers。 |
| 查热销、Best Sellers | `bestsellers` | `category` 或 `productGroup` | `range`, `month`+`year`, `variations`, `sublist` | `month/year` 必须成对且限过去 36 个完整自然月；不能与 `range`/`sublist` 混用。 |
| 查近期价格/排名变化、Browsing Deals | `deals` | `selection.priceTypes`，且只能有 1 个索引 | `selection` 的筛选、排序和分页字段 | 查询最近约 12 小时发生变化的商品，单次最多约 150 条；不是全部正在进行的 Amazon 活动。 |
| 查秒杀、Lightning Deals | `lightning-deals` | 无 | `asin`, `state` | 当前和即将开始的秒杀；不传 ASIN 的完整列表成本很高。 |

参数不足时的追问口径：

- `product` 缺 ASIN/code：`请提供要查询的 ASIN，或 UPC/EAN/ISBN-13 code。`
- `product-search` 缺关键词：`请提供要搜索的关键词。`
- `category-lookup` 缺类目 ID：`请提供 Keepa/Amazon category id。`
- `seller` 缺 seller ID：`请提供 seller ID。`
- `bestsellers` 缺类目：`请提供 Keepa/Amazon category id，或 productGroup。`

## 参数映射与默认值

| 中文表达 | 调用参数 |
| --- | --- |
| `跑 keepa product-search，关键词 flashlight，导出结果` | `scenario="product-search"`, `site="US"`, `params={"keyword":"flashlight"}` |
| `查美区 ASIN B0088PUEPK 的商品详情` | `scenario="product"`, `site="US"`, `params={"asin":"B0088PUEPK","stats":30}` |
| `查这个 ASIN 的价格历史` | `scenario="product"`, `params={"asin":"...","history":true,"stats":30}` |
| `只要 ASIN 列表` | 对 `product-search` 加 `params={"asins_only":true}` |
| `查 seller A2L77EE7U53NWQ 店铺商品` | `scenario="seller"`, `params={"seller":"A2L77EE7U53NWQ","storefront":true}` |
| `批量查多个 seller 信息，不要店铺商品` | `scenario="seller"`, `params={"sellers":["...","..."],"storefront":false}` |
| `查 172282 类目的 best sellers` | `scenario="bestsellers"`, `params={"category":"172282"}` |
| `查 Home productGroup 的 best sellers` | `scenario="bestsellers"`, `params={"productGroup":"Home"}` |
| `Product Finder 查 sales rank 1 到 5000 的商品` | `scenario="product-finder"`, `params={"selection":{"current_SALES_gte":1,"current_SALES_lte":5000,"perPage":50}}` |
| `Product Finder 查 sales rank 1 到 5000 的市场概况` | `scenario="product-finder"`, `params={"stats":1,"selection":{"current_SALES_gte":1,"current_SALES_lte":5000,"perPage":50}}` |
| `查 flashlight 的类目` | `scenario="category-search"`, `params={"keyword":"flashlight"}` |
| `查这个 ASIN 最近 90 天价格走势` | `scenario="product"`, `params={"asin":"...","stats":90,"history":true}` |
| `导出 flashlight 搜索结果，只要 ASIN` | `scenario="product-search"`, `params={"keyword":"flashlight","asins_only":true}` |
| `查某店铺的 ASIN 列表` | `scenario="seller"`, `params={"seller":"...","storefront":true}` |
| `查美国当前秒杀` | `scenario="lightning-deals"`, `site="US"`, `params={}` |
| `查 Buy Box 价格变化商品` | `scenario="deals"`, `params={"selection":{"priceTypes":[18],"page":0}}` |
| `查 ASIN 的 Limited Time Deal 和活动关联价` | `scenario="product"`, `params={"asin":"...","offers":20,"stats":30}` |
| `要原始 JSON 数据` | 保持原场景和参数，传 `export_format="json"`；需要请求和状态包装时再使用内部 `raw.json` |

- 用户未指定站点：`site="US"`。
- 用户只说“导出”：使用默认 `export_format="xls"`，实际生成自动格式化的 `.xlsx`；也可显式传 `export_format="xlsx"`。
- 用户只说“查商品详情”：建议 `stats=30`；`product` 场景默认会带 `history=true`。
- 用户说“不需要历史/不要价格历史”：额外传 `history=false`。
- 用户说“只要 ASIN”：使用 `asins_only=true`。
- 用户要求结构化 JSON、批量编排或分析报告：使用 `export_format="json"`，直接读取导出文件的 `response`；若要求核对请求参数、前后状态或内部包装，仍以任务内部 `raw.json` 为准。
- `product-search` 当前单次最多返回 20 条，不支持 `page`。
- `seller` 默认使用 `storefront=false`；仅在用户明确需要单个店铺的 ASIN 列表时传 `storefront=true`，批量 seller 禁止开启。

## 用户回答规范

回答要站在业务用户视角，不解释 API token、账号、内部请求参数、原始 JSON 结构。

成功时固定包含：查询已完成、站点、查询对象、返回行数、导出文件和 MCP 每日调用额度。导出文件优先 `export.url`，没有再用 `export.path`。

成功时不要包含：Keepa token 消耗、剩余 tokens、API Key、账号来源、`params.json`、`raw.json` 等内部调试文件。

- 若 `keepa_run` 响应顶层存在 `quota`，在最终自然语言回复末尾补一句：
  - `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
- `keepa_scenarios`、`keepa_quota_status`、`keepa_job_status`、`keepa_export` 不消耗额度；只有 `keepa_run` 消耗次数。
- `job_status` 和 `export` 默认不重复提示额度，避免轮询阶段重复刷屏。

当用户问“导出的数据准确吗/字段怎么来的”：

```text
导出数据来自 Keepa 原始响应；JSON v2 保留原始业务字段和嵌套结构，XLSX 会生成中文表头、可读派生字段和明细 sheet。字段单位、倍率和准确性以 Keepa 官方文档和后端确认口径为准。
如需核对请求参数、前后状态和完整内部响应包装，请使用任务内部 raw.json。
```

成功模板：

```text
已完成 Keepa <场景> 查询并导出表格。

站点：US
查询对象：<关键词 / ASIN / seller ID / category id / selection>
返回行数：<row_count>
导出文件：<export.url 或 export.path>
今日额度：已用 <quota.used> / <quota.limit>，剩余 <quota.remaining>，重置时间 <quota.reset_at>
```

异常和空结果模板：

| 场景 | 用户回复 |
| --- | --- |
| 返回行数为 0 | `已完成查询，但没有返回匹配结果。\n\n站点：<site>\n查询对象：<对象>\n建议：可以换一个更宽泛的关键词，或确认站点和查询对象是否正确。` |
| 查询对象无效或查不到 | `未查询到相关数据，请确认 ASIN、code、category id、seller ID 或站点是否正确。` |
| 多 ASIN 部分无数据 | `查询已完成，部分 ASIN 未返回 Keepa 数据；已将可用结果导出。` |
| Keepa 额度不足或等待卡住 | `Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。` |
| 导出上传失败但本地文件存在 | `查询已完成，云端上传失败，已保留本地导出文件。\n\n导出文件：<export.path>` |
| `job_id` 不存在 | `未找到该 Keepa 任务，请确认 job_id 是否正确，或重新发起查询。` |
| Keepa API 限流/服务异常 | `Keepa 服务暂时不可用，请稍后重试；如果持续失败，请联系运营人员处理。` |

## 站点

Use Keepa site codes: `US`, `GB`/`UK`, `DE`, `FR`, `JP`, `CA`, `IT`, `ES`, `IN`, `MX`, `BR`。

中文站点映射：

- 美国/美区/US -> `US`
- 日本/日区/JP -> `JP`
- 德国/德区/DE -> `DE`
- 英国/英区/UK/GB -> `GB`
- 法国/FR、加拿大/CA、意大利/IT、西班牙/ES、印度/IN、墨西哥/MX、巴西/BR 按对应站点码映射。

## 调用示例

Product:

```json
{
  "scenario": "product",
  "site": "US",
  "params": {
    "asins": ["B0088PUEPK"],
    "stats": 30,
    "history": true
  }
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
