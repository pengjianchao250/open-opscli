---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵查询与导出 Skill。用于把中文自然语言需求映射为 seller_sprite_* 场景，处理缺参澄清、类目确认、任务续查和 XLS 导出。
---

# ops-seller-sprite

用于把卖家精灵自然语言需求映射成标准场景，并通过正式 MCP 入口完成查询、导出和任务续查。

当前对用户公开的正式 CLI 入口是 `opscli seller-sprite ...`。
该入口默认通过 CLI auth 获取远端 MCP 配置，再调用远端 `seller_sprite_*` tool 完成查询；本 Skill 也以这条正式链路作为默认执行口径。

## 快速规则

1. 先识别场景，再决定是否执行；场景不明确时先澄清，不要盲跑。
2. 只追问缺失的必填参数，不追问可选参数；未提供的可选参数交给后端默认值。
3. 默认使用：
   - `site=US`
   - `period=30d`
   - `page_size=100`
   - `export_format=xls`
4. 用户给了明确条件，就原样带入 `params`；不要发明隐藏枚举值或额外筛选。
5. `月份` / `数据月份` / `2026-04` 传顶层 `period`；只有“上架时间 / 上架月数 / 上架多久”才映射到 `params.putawayMonth`。
6. 类目文本可以直接传；如果后端返回多个类目候选，必须停下来让用户确认，不能猜。
7. 不向用户暴露账号、Cookie、内部运行参数、长本地路径或调试文件。
8. 当前 Skill 的参数词典、场景映射、别名、默认值统一以 [SCENARIO_PARAMS_ZH.md](SCENARIO_PARAMS_ZH.md) 为准。
9. 面向 CLI 说明时，默认引用 `opscli seller-sprite ...` 这条正式命令路径；不要向用户展开底层远端 URL、`api_key` 或内部调试入口。

## 最小工作流

1. 先按用户意图映射场景；拿不准时再读取参数手册确认。
2. 缺少必填参数时，只问当前场景真正缺的字段。
3. 条件齐全后，构造 `scenario + site + period + params`。
4. 执行后记录 `job_id`，后续查状态、取导出文件都复用它。
5. 用户想先看今天还剩几次额度时，优先走 `seller_sprite_quota_status`，或正式 CLI `opscli seller-sprite quota-status`。
6. 如果当前宿主是 MCP 工具协作环境，继续阅读 [SKILL_MCP.md](SKILL_MCP.md) 的工具链和异步规则。

## 缺参澄清原则

- `查关键词` 这类表达可能对应 `keyword-miner`、`keyword-reverse`、`traffic-source`，先让用户选场景。
- `查产品` 这类表达可能对应 `competitor-lookup` 或 `product-research`，先让用户确认目的。
- `看市场/类目` 这类表达可能对应 `market-research` 或 `product-research`，先让用户确认。
- `competitor-lookup` 不能无条件直接跑，至少要有 `keyword`、`brand`、`sellerName`、`asins` 或 Amazon 商品链接中的一种。
- `competitor-lookup` 如果用户给的是单个 ASIN，也要先归一化成 `params.asins`；不要把单个 ASIN 直接留在 `params.asin` 后就发请求。
- `competitor-lookup` 缺少主筛选条件时，应直接报参数错误或继续澄清，不要等成 30 秒 MCP 超时。
- `keyword-reverse` 必须有 ASIN。
- `traffic-source` 必须有关键词或 ASIN。
- `product-research` 和 `market-research` 虽然没有硬性必填，但用户条件明显不足时，仍应先确认意图，不要把“可空”误当成“随便跑”。

可直接复用的话术：

- `你想做关键词挖掘、关键词反查，还是查流量来源？`
- `查竞品需要 keyword、brand、sellerName、asins 或 Amazon 产品链接中的一种，请补充。`
- `关键词反查需要 ASIN，请提供 ASIN 或 Amazon 产品链接。`
- `查流量来源需要关键词或 ASIN，请补充。`

## 回复规则

- 优先使用工具返回的 `data.summary`，不要改写成原始 JSON。
- 成功时只保留用户关心的信息：场景、关键条件、`job_id`、`row_count`、导出文件。
- 若 `seller_sprite_run` 响应顶层存在 `quota`，补一句：
  - `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
- `seller_sprite_run` 会消耗次数；`seller_sprite_scenarios`、`seller_sprite_quota_status`、`seller_sprite_job_status`、`seller_sprite_export` 不消耗次数。
- `row_count=0` 时，要明确告诉用户没有查到数据，并提醒核对站点、ASIN、关键词、类目或筛选条件是否过窄。
- 用户后来只说 `继续`、`查结果`、`刚才那个好了没` 时，直接复用最近一次 SellerSprite `job_id`，不要要求用户重新描述整单请求。
