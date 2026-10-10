# 西柚 OpenAPI 官方合同核对

核对日期：2026-10-10。范围：[官方 llms.txt](https://openapi-doc.xiyouzhaoci.com/llms.txt) 列出的 4 份指引/更新记录及 22 个接口页面；其中 21 个为当前业务接口，另 1 个为仅限 v1 的余额接口。本次仅读取公开文档，没有请求付费业务 API。

结论：除日趋势可用日期指引外，还应修正 5 个操作的必填参数目录，并补齐类型、枚举、排序、批量上限、站点限制和响应口径。部分文档自身存在冲突，不能直接据示例推导强制校验或改写供应商响应。

## 必填参数差异

下表由官方 requestBody.schema.required 与修改前本地目录对照得出；完整参数详情应由当前操作目录及 Skill 参考文档提供。

| 本地操作 | 官方必填字段 | 修改前缺口 | 官方来源 |
| --- | --- | --- | --- |
| `asin_research_period` | asin、country、page、pageSize、period | 错列 startDate/endDate；缺 page/pageSize/period | [最近天反查](https://openapi-doc.xiyouzhaoci.com/331502595e0.md) |
| `asin_research_monthly` | asin、country、page、pageSize、startMonth、endMonth | 缺 page/pageSize | [月度反查](https://openapi-doc.xiyouzhaoci.com/331594504e0.md) |
| `search_terms_info` | country、searchTerms、sort | 缺 sort | [最近周关键词信息](https://openapi-doc.xiyouzhaoci.com/333379279e0.md) |
| `search_terms_analysis_period` | searchTerm、country、page、pageSize、period、sort | 缺 page/pageSize/sort | [最近天关键词分析](https://openapi-doc.xiyouzhaoci.com/451262166e0.md) |
| `search_terms_analysis_monthly` | searchTerm、country、page、pageSize、startMonth、endMonth、sort | 缺 page/pageSize/sort | [月度关键词分析](https://openapi-doc.xiyouzhaoci.com/451506681e0.md) |

ASIN 反查 `sort` 可选，官方描述默认流量降序；关键词信息及关键词分析的 `sort` 必填，不能将相似接口的默认值套用过去。`sort` 对象包含必填 `field`、`order`，`order` 为 `asc` 或 `desc`，合法字段按具体接口枚举读取。[反查来源](https://openapi-doc.xiyouzhaoci.com/331502595e0.md)、[关键词来源](https://openapi-doc.xiyouzhaoci.com/333379279e0.md)。

最近周期 `period` 的官方枚举只有 `last7days`，不能自行支持 `last30days`；月份为 `YYYY-MM`，日参数为 `YYYY-MM-DD`。[反查周期](https://openapi-doc.xiyouzhaoci.com/331502595e0.md)、[分析周期](https://openapi-doc.xiyouzhaoci.com/451262166e0.md)、[月份](https://openapi-doc.xiyouzhaoci.com/331594504e0.md)。

## 明确的站点与批量约束

通用 Country 枚举为 `US/CA/MX/BR/UK/DE/ES/IT/FR/JP/AU/SA/AE`，英国代码为 `UK`。该枚举不代表每个操作及字段均支持全部站点。[通用 Country](https://openapi-doc.xiyouzhaoci.com/312439564e0.md)。

| 能力 | 官方明确约束 | 官方来源 |
| --- | --- | --- |
| ASIN 流量快照 | `entities` 最多 100 个 ASIN | [流量快照](https://openapi-doc.xiyouzhaoci.com/312439564e0.md) |
| ASIN 商品信息 | `entities` 最多 100 个 ASIN | [商品信息](https://openapi-doc.xiyouzhaoci.com/335282030e0.md) |
| ASIN 近 30 天订单 | `asins` 最多 100 个 ASIN | [近 30 天订单](https://openapi-doc.xiyouzhaoci.com/339953324e0.md) |
| 最近一周关键词信息 | `searchTerms` 最多 100 个词 | [关键词信息](https://openapi-doc.xiyouzhaoci.com/333379279e0.md) |
| 关键词 ABA 周趋势 | 最多 100 个词，最长 52 周 | [ABA 周趋势](https://openapi-doc.xiyouzhaoci.com/333362889e0.md) |
| ASIN 反查及关键词分析列表 | 单次最多 10000 条；`pageSize` 用于限制返回条数及费用 | [反查日](https://openapi-doc.xiyouzhaoci.com/331502595e0.md)、[反查月](https://openapi-doc.xiyouzhaoci.com/331594504e0.md)、[分析日](https://openapi-doc.xiyouzhaoci.com/451262166e0.md)、[分析月](https://openapi-doc.xiyouzhaoci.com/451506681e0.md) |
| ASIN 月度反查 | 查询周期最长一年 | [反查月](https://openapi-doc.xiyouzhaoci.com/331594504e0.md) |
| 词排名小时趋势 | 每次只请求一天，仅 US/UK/DE | [小时排名](https://openapi-doc.xiyouzhaoci.com/332071833e0.md) |
| BSR 日趋势 | Keepa 数据；请求 LimitCountry 为 US/CA/MX/BR/UK/DE/FR/ES/IT/JP，暂不支持 AU/SA/AE | [BSR 日趋势](https://openapi-doc.xiyouzhaoci.com/327781736e0.md) |
| 商品信息日趋势 | coupon/promotion/subscription/other 仅 US/UK/CA/AE/AU；其余字段支持所有站点 | [商品趋势](https://openapi-doc.xiyouzhaoci.com/331311535e0.md) |
| 变体 | 一次查询一个 ASIN；2026-08-12 更新记录新增 AE/SA/AU 支持 | [变体](https://openapi-doc.xiyouzhaoci.com/370838212e0.md)、[更新记录](https://openapi-doc.xiyouzhaoci.com/8718788m0.md) |

日级趋势文档中的“75 天”是计费示例，不是最大查询跨度；不能外推成所有操作统一 30/90 天限制。[日流量计费](https://openapi-doc.xiyouzhaoci.com/326002208e0.md)。

## 响应口径、缺失值与类型

| 返回数据 | 官方明确内容 | 使用建议与未确认项 | 官方来源 |
| --- | --- | --- | --- |
| ASIN trafficScore | 近 7 天/前一 7 天自然、广告、总流量得分；占比、增长率为 number 且可 null | 应称“流量得分”；文档未将其定义为真实访客、点击或会话数量 | [流量快照](https://openapi-doc.xiyouzhaoci.com/312439564e0.md)、[日流量得分](https://openapi-doc.xiyouzhaoci.com/326002208e0.md) |
| 关键词 traffic | summaryTraffic、positionTraffic 为整数流量；positionTrafficAcquisitionRate 为 number | 保留供应商“流量/流量获得率”名称；官方 API 页没有保证等同广告后台实际点击 | [词流量](https://openapi-doc.xiyouzhaoci.com/327911125e0.md) |
| 订单量 | `orders` 为 integer，月度及近 30 天接口明确称订单量 | 文档未承诺等同实际销售件数、销售额，未说明估算方法或父子 ASIN 汇总口径 | [月订单](https://openapi-doc.xiyouzhaoci.com/328160994e0.md)、[近 30 天订单](https://openapi-doc.xiyouzhaoci.com/339953324e0.md) |
| 词排名 | pageRank=页内排名、totalRank=总排名；两字段非 required，示例可仅给 page | 缺失排名不要补零；官方未定义 999 哨兵，也未解释 page=10 等同未收录 | [日排名](https://openapi-doc.xiyouzhaoci.com/329420765e0.md)、[小时排名](https://openapi-doc.xiyouzhaoci.com/332071833e0.md) |
| ABA 周新增指标 | 竞争难度越大越激烈；organicRotationRate 为小数；adjustedClickConversionRate 为四位小数；这些指标及 cpc 各值无数据为 null | organicRotationRate、adjustedClickConversionRate、cpc.value/min/max 在 schema 中是 string；展示可转数值，但 null 保持缺失 | [ABA 周趋势](https://openapi-doc.xiyouzhaoci.com/333362889e0.md)、[2026-07-28 更新](https://openapi-doc.xiyouzhaoci.com/8718788m0.md) |
| 最近周关键词信息 | clickConversionRate、competitiveDifficulty、abaReport、costPerClick 可 null；costPerClick 的 value/minSuggestedBid/maxSuggestedBid 为 string | 与 ABA 的 cpc.value/min/max 字段名不同，不可统一假设所有响应同名 | [关键词信息](https://openapi-doc.xiyouzhaoci.com/333379279e0.md) |
| 商品价格 | 关键词分析的 asinInfo.currency 明确价格货币单位 | 保留 currency，不将所有站点默认为美元；CPC 页面未明确给出货币合同 | [关键词分析](https://openapi-doc.xiyouzhaoci.com/451262166e0.md)、[ABA CPC](https://openapi-doc.xiyouzhaoci.com/333362889e0.md) |

## v2 接入、响应头及费用

以下均来自 [OpenAPI v2 接入指引](https://openapi-doc.xiyouzhaoci.com/9065291m0.md)，该页标注版本 v1.0.1、最后更新 2026-06-25：

- v2 仍使用 `https://openapi.xydc.com/v1/...` 路径，必需 `X-Auth-Version: 2.0`、`X-Api-Key`、`Content-Type: application/json`；无需 v1 签名头。单接口旧 schema 的 `security: []` 不代表无需鉴权。
- `X-Trace-Id` 用于追踪，`X-Cost-Credits` 为实际消耗，429 时的 `Retry-After` 为建议等待秒数。默认按 40 次/分钟设计调用节奏。
- 标准错误 `code` 是 HTTP 数字状态，`reason` 是业务错误，`message` 是说明，`metadata` 是扩展信息。与之前真实复现的字符串 `code`/`msg` 返回不一致，因此需要兼容解析，不能只依赖一套格式。
- 官方建议 30 秒超时；400/401/403 先修正参数、鉴权、额度，不自动重试；429 按 Retry-After 等待；5xx/网络错误最多 3 次指数退避重试。是否实现重试属于客户端策略，不能在 Skill 再叠加无限重放。
- 官方仅说错误“通常不会产生业务扣费”，不能写成无条件免费。实际费用应看响应头，不用粗略公式代替结算结果。

| 接口组 | 文档计费规则 | 来源 |
| --- | --- | --- |
| ASIN 流量快照/商品信息 | 每 ASIN 1 Credit | [流量](https://openapi-doc.xiyouzhaoci.com/312439564e0.md)、[商品](https://openapi-doc.xiyouzhaoci.com/335282030e0.md) |
| ASIN 基础/广告/BSR/商品/流量日趋势 | 每 10 天向上取整 1 Credit | [基础](https://openapi-doc.xiyouzhaoci.com/325279983e0.md)、[广告](https://openapi-doc.xiyouzhaoci.com/326115660e0.md)、[BSR](https://openapi-doc.xiyouzhaoci.com/327781736e0.md)、[商品](https://openapi-doc.xiyouzhaoci.com/331311535e0.md)、[流量](https://openapi-doc.xiyouzhaoci.com/326002208e0.md) |
| ASIN 周/月流量趋势 | 每 4 周向上取整 1 Credit / 每月 1 Credit | [周](https://openapi-doc.xiyouzhaoci.com/326241285e0.md)、[月](https://openapi-doc.xiyouzhaoci.com/326253357e0.md) |
| 月订单/近 30 天订单/变体 | 每 6 月向上取整 1 / 每 5 ASIN 向上取整 1 / 每请求 5 Credits | [月订单](https://openapi-doc.xiyouzhaoci.com/328160994e0.md)、[近 30 天](https://openapi-doc.xiyouzhaoci.com/339953324e0.md)、[变体](https://openapi-doc.xiyouzhaoci.com/370838212e0.md) |
| 词流量日/排名日/排名小时 | 每 5 天向上取整 1 / 每 5 天向上取整 1 / 每天固定 3 Credits | [词流量](https://openapi-doc.xiyouzhaoci.com/327911125e0.md)、[排名日](https://openapi-doc.xiyouzhaoci.com/329420765e0.md)、[排名小时](https://openapi-doc.xiyouzhaoci.com/332071833e0.md) |
| 反查/关键词分析列表 | 每返回 20 条向上取整 1 Credit | [反查日](https://openapi-doc.xiyouzhaoci.com/331502595e0.md)、[反查月](https://openapi-doc.xiyouzhaoci.com/331594504e0.md)、[分析日](https://openapi-doc.xiyouzhaoci.com/451262166e0.md)、[分析月](https://openapi-doc.xiyouzhaoci.com/451506681e0.md) |
| ABA 周/关键词最近周 | ⌈词数÷20×周数⌉ / 每 10 词向上取整 1 Credit | [ABA](https://openapi-doc.xiyouzhaoci.com/333362889e0.md)、[关键词](https://openapi-doc.xiyouzhaoci.com/333379279e0.md) |

## 文档冲突与不能据此修改的事项

| 冲突或未明确合同 | 证据与处理 |
| --- | --- |
| 日 Date.pattern 要求带时间及偏移，description/format/example 是 YYYY-MM-DD | [日排名](https://openapi-doc.xiyouzhaoci.com/329420765e0.md)、[小时请求日期](https://openapi-doc.xiyouzhaoci.com/332071833e0.md)；请求按操作说明及实际已验证日期格式，不能复制冲突正则 |
| ABA 周描述误写“周日到周一” | [ABA 示例](https://openapi-doc.xiyouzhaoci.com/333362889e0.md) 实际是周日到周六，与 [最近周 reportFromDate/reportToDate](https://openapi-doc.xiyouzhaoci.com/333379279e0.md) 一致；流量周 [示例](https://openapi-doc.xiyouzhaoci.com/326241285e0.md) 则是周一到周日，但 schema 仅说 7 天，不应将示例边界当成统一硬规则 |
| 周流量响应 schema 是 week，部分示例是 dateRange | [周流量](https://openapi-doc.xiyouzhaoci.com/326241285e0.md)；保留真实字段，分析时先读取实际响应，不按单个示例强行丢字段 |
| PositionTraffic schema 与示例展示位数量不同 | [周](https://openapi-doc.xiyouzhaoci.com/326241285e0.md)、[月](https://openapi-doc.xiyouzhaoci.com/326253357e0.md) schema 列 6 个位置，示例还含 ac/er/hr/trb/cpf；不可据通用组件认为其他位置非法 |
| 商品日趋势文字提到最多 100 ASIN，但请求是单 asin | [商品趋势](https://openapi-doc.xiyouzhaoci.com/331311535e0.md)；不自行添加 asins 数组或批量结构 |
| 流量快照计费示例 120 ASIN，与请求 100 上限冲突 | [流量快照](https://openapi-doc.xiyouzhaoci.com/312439564e0.md)；计费演算不是有效批次示例，上限按参数明确文字 |
| 关键词分析供应商分页基数未确认 | [分析日](https://openapi-doc.xiyouzhaoci.com/451262166e0.md)、[分析月](https://openapi-doc.xiyouzhaoci.com/451506681e0.md) 只有 integer/mock min1，无 minimum/default 或实际请求 example；4 份指引也未定义起点。反查 page=1 示例不能证明另一接口同基数，保留现有兼容转换待独立验证 |
| 月查询的共享 MonthDate 带 format: date | [月份](https://openapi-doc.xiyouzhaoci.com/326253357e0.md) 同时明确 YYYY-MM 和相应正则，应按月份格式，不要求补日 |
| v2 余额与旧能力误导 | [余额接口](https://openapi-doc.xiyouzhaoci.com/457513504e0.md) 明确仅限 v1，空对象 body，最多延迟 10 分钟；[2026-08-06 更新记录](https://openapi-doc.xiyouzhaoci.com/8718788m0.md) 明确市场洞察 API 已下线，不按历史发布清单新增能力 |

当前公开 API 文档没有给出日趋势统一数据就绪时刻、最早可查询日、缺日是否补齐、排名哨兵定义或所有指标的货币/百分比转换合同。应区分“官方明确约束”“本次真实复现证据”“尚未确认”，不以推测扩大参数校验。
