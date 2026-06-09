---
name: ops-keepa-internal
mcp-version: v1.0.0
description: Keepa MCP 中文自然语言使用规范，用于通过 keepa_* 工具查询商品、关键词、类目、卖家、折扣、热销等数据并导出表格。
visibility: internal
---

# ops-keepa MCP

这是 `keepa_spec_must_read` 读取的内部 MCP 使用规范，放在
`opscli/mcp/references/keepa/` 下，不作为可安装用户 Skill 暴露。

用户大多数会用中文自然语言提需求，Agent 应优先把中文意图转换成
`keepa_run` 的 `scenario + site + params`，再执行工具。

## Agent 快速执行规则

1. 先把用户话术归类为商品、关键词搜索、筛选、类目、卖家、热销、折扣、秒杀之一。
2. 站点缺省用 `US`；不要因为缺站点而追问。
3. 必填参数齐全时直接执行 `keepa_run`；不要把内部参数确认流程暴露给用户。
4. 只缺必填项时最多追问 1 个短问题；一次追问尽量覆盖同一场景的所有必填项。
5. 默认导出用户可读 XLSX；用户明确要原始数据、后端比对、JSON 或结果行数过大时用 JSON。
6. 最终回复只给业务结果：查询对象、站点、返回行数、导出文件或链接。
7. 不主动展示 API Key、账号来源、token 消耗、额度余额、内部参数、`params.json`、`raw.json`。

## 工具列表

- `keepa_spec_must_read`: read this guide before first use.
- `keepa_scenarios`: list supported Keepa scenarios.
- `keepa_run`: run a Keepa scenario and save request/response/export files. Default export is XLSX. `export_format` accepts `xls`/`xlsx`/`json`; `xls` and `xlsx` both generate `.xlsx`. Large results are automatically exported as JSON to avoid XLSX timeout.
- `keepa_job_status`: read a saved task result by `job_id`.
- `keepa_export`: read export path or cloud URL, filename, format, and MIME type.

不要向用户推荐或暴露单独的 token 状态查询。Keepa 额度由系统内部管理。

## 输入识别规则

- ASIN 通常是 10 位，由大写字母和数字组成，常见形态为 `B0XXXXXXXX` 或 `B00XXXXXXX`。
- 多个 ASIN / seller ID / category id 支持用户用逗号、空格、顿号、换行分隔；调用前规范化为数组或逗号字符串均可。
- UPC/EAN/ISBN-13 等条码走 `code`/`codes`；不要和 `asin`/`asins` 同时传给 `product`。
- 用户同时给 ASIN 和关键词时，以明确动作判断：说“查这个 ASIN”走 `product`，说“搜关键词”走 `product-search`；意图冲突时只追问查询对象类型。
- 用户说“查商品详情”“查商品”时，`product` 默认会带 `history=true` 获取历史价格变化；用户明确说不要历史时再传 `history=false`。
- 用户说“最近 30 天”“近 90 天”时，优先映射为 `stats=30/90`。
- 用户说“只要 ASIN”“只导出 ASIN 列表”时，`product-search` 加 `asins_only=true`。
- 用户说“店铺商品”“店铺 ASIN”时，`seller` 加 `storefront=true`。

## 认证与额度

- Keepa API Key 由后端读取：优先 OPS integration account `platform=keepa`，本地兜底为 `OPSCLI_KEEPA_API_KEY`。
- Keepa 额度由系统内部管理；Agent 不向普通用户展示 API Key、账号来源、token 消耗或剩余额度。
- `keepa_run` 会做额度预检；额度不足或等待卡住时，只回复用户稍后重试或联系运营人员。
- 内部文件可能保留 `tokensLeft`、`tokensConsumed` 等 quota 字段，仅用于排障。

## 导出、任务与文件边界

Every run writes files under the task directory:

- `params.json`: original request, scenario metadata, API account summary, normalized Keepa params, quota precheck.
- `raw.json`: endpoint, normalized request params, before/after token status, raw Keepa response.
- `result.json`: normalized task result and export metadata.
- `<job_id>.xlsx`: default user-facing export with Chinese headers.
- `<job_id>.json`: optional debug export when `export_format=json`, containing rows, raw response, request params, and quota fields.
- 当结果行数过大时，即使请求 XLSX 也会自动改为 JSON，并通过 `warnings` 返回文字提示。

- `export.url` 存在时只回复云端链接；否则回复 `export.path`。
- 上传失败但本地导出存在时，不判定任务失败，回复本地文件路径。
- 用户提供 `job_id` 查询结果时用 `keepa_job_status`；只问文件位置时用 `keepa_export`。
- `job_id` 查不到时回复“未找到该 Keepa 任务”，不要暴露内部目录。
- 不向普通用户展示 task directory、`params.json`、`raw.json`、`result.json`，除非明确要求后端比对或排障。

XLSX 中文表头不是 Keepa 官方提供的，是本地导出层按场景映射生成：

- 商品类：ASIN、父ASIN、标题、品牌、产品组、最近更新(UTC)、评分、评论数、价格、链接等。
- 卖家类：Seller ID、店铺名称、最近更新(UTC)、评分、评分数、店铺ASIN数、店铺链接等。
- 类目类：类目ID、类目名称、父类目ID、产品数量、最高排名、子类目等。

`raw.json` 保留 Keepa 原始字段，后端对比以 `raw.json` 为准；XLSX 用于用户查看。

## 字段口径与时间处理

Keepa uses minute-based timestamps in many API payloads. The timezone is UTC.

- Unix seconds: `(keepa_time + 21564000) * 60`
- Unix milliseconds: `(keepa_time + 21564000) * 60000`

- 不在 MCP 使用规范中推断 Keepa 原始价格、评分、排名、评论、Offer 等字段的单位、倍率或空值语义；除非 Keepa 官方文档、接口说明或当前响应字段已明确说明。
- `raw_response` 不修改；normalized `rows` 只额外补充常见时间字段，如 `lastUpdateUtc`。
- `csv` 时间/数值数组保持 Keepa 原始结构；面向普通用户不要解释原始数组，优先让用户查看 XLSX 可读字段。
- `raw.json` 是后端对比和排障基准；XLSX 是本地导出层生成的用户查看文件。
- 用户追问字段单位、倍率、计算方式或准确性时，不要自行类比卖家精灵或其他数据源；应说明以 Keepa 原始响应、官方文档和后端确认口径为准。

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

## 参数映射与默认值

| 中文表达 | 调用参数 |
| --- | --- |
| `跑 keepa product-search，关键词 flashlight，导出结果` | `scenario="product-search"`, `site="US"`, `params={"keyword":"flashlight"}` |
| `查美区 ASIN B0088PUEPK 的商品详情` | `scenario="product"`, `site="US"`, `params={"asin":"B0088PUEPK","stats":30}` |
| `查这个 ASIN 的价格历史` | `scenario="product"`, `params={"asin":"...","history":true,"stats":30}` |
| `只要 ASIN 列表` | 对 `product-search` 加 `params={"asins_only":true}` |
| `查 seller A2L77EE7U53NWQ 店铺商品` | `scenario="seller"`, `params={"seller":"A2L77EE7U53NWQ","storefront":true}` |
| `查 172282 类目的 best sellers` | `scenario="bestsellers"`, `params={"category":"172282"}` |
| `查 flashlight 的类目` | `scenario="category-search"`, `params={"keyword":"flashlight"}` |
| `查这个 ASIN 最近 90 天价格走势` | `scenario="product"`, `params={"asin":"...","stats":90,"history":true}` |
| `导出 flashlight 搜索结果，只要 ASIN` | `scenario="product-search"`, `params={"keyword":"flashlight","asins_only":true}` |
| `查某店铺的 ASIN 列表` | `scenario="seller"`, `params={"seller":"...","storefront":true}` |
| `查美国当前秒杀` | `scenario="lightning-deals"`, `site="US"`, `params={}` |
| `查折扣商品，按 selection 筛选` | `scenario="deals"`, `params={"selection":{...}}` |
| `要原始 JSON 给后端对比` | 保持原场景和参数，额外传 `export_format="json"` |

- 用户未指定站点：`site="US"`。
- 用户只说“导出”：使用默认 `export_format="xls"`，实际生成 `.xlsx`；也可显式传 `export_format="xlsx"`。
- 用户只说“查商品详情”：建议 `stats=30`；`product` 场景默认会带 `history=true`。
- 用户说“不需要历史/不要价格历史”：额外传 `history=false`。
- 用户说“只要 ASIN”：使用 `asins_only=true`。
- 用户要求后端比对、原始数据、JSON：使用 `export_format="json"`。
- 用户未指定页码：`product-search` 可以不传 `page`，需要显式第一页时传 `page=0`。
- 用户要求店铺商品或店铺 ASIN：`seller` 使用 `storefront=true`。

## 用户回答规范

回答要站在业务用户视角，不解释 API token、账号、内部请求参数、原始 JSON 结构。

成功时固定包含：查询已完成、站点、查询对象、返回行数、导出文件。导出文件优先 `export.url`，没有再用 `export.path`。

成功时不要包含：token 消耗、剩余 tokens、API Key、账号来源、`params.json`、`raw.json` 等内部调试文件。

当用户问“导出的数据准确吗/字段怎么来的”：

```text
表格字段来自 Keepa 原始响应，本地导出层只做中文表头和部分可读化处理；字段单位、倍率和准确性以 Keepa 原始响应、官方文档和后端确认口径为准。原始响应保存在 raw.json，可用于后端对比。
```

成功模板：

```text
已完成 Keepa <场景> 查询并导出表格。

站点：US
查询对象：<关键词 / ASIN / seller ID / category id / selection>
返回行数：<row_count>
导出文件：<export.url 或 export.path>
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

Use Keepa site codes: `US`, `GB`/`UK`, `DE`, `FR`, `JP`, `CA`, `IT`, `ES`, `IN`, `MX`, `BR`.

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
