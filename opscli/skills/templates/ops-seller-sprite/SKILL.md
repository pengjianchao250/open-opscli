---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵查询与导出 Skill。用于把中文自然语言需求映射为 seller_sprite_* 场景，处理缺参澄清、类目确认、任务续查和 XLS 导出。
---

# ops-seller-sprite

用于把卖家精灵自然语言需求映射成标准场景，并通过正式 MCP 入口完成查询、导出和任务续查。

当前对用户公开的正式 CLI 入口是 `opscli seller-sprite ...`。
该入口默认通过 CLI auth 获取远端 MCP 配置，再调用远端 `seller_sprite_*` tool 完成查询；本 Skill 也以这条正式链路作为默认执行口径。
正式 CLI 依赖本机已完成 OPS 授权；若本机未登录或登录态过期，先完成 `opscli auth login` 再继续。

授权排查先看链路类型：正式 CLI 代理链路优先用本机 `opscli auth login`；远端 MCP 直连链路优先用 MCP 授权工具完成当前 MCP 用户的 OPS 登录。两条链路不要混用判断。

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
10. 若返回授权类错误或提示先完成 OPS 授权，优先检查本机 CLI 登录态；不要先把问题归因为卖家精灵账号、场景参数或采集模式。

## 链路区分

### A. 正式 CLI 代理链路（默认）

适用入口：

```bash
opscli seller-sprite scenarios
opscli seller-sprite quota-status
opscli seller-sprite run ...
opscli seller-sprite listing-analysis-submit --asin B0XXXX --station GLOBAL --site US
opscli seller-sprite listing-analysis-status <job_id>
opscli seller-sprite listing-analysis-result <job_id> --export-format json
opscli seller-sprite job-status <job_id>
opscli seller-sprite export <job_id>
```

判断规则：

- 用户在本机终端执行 `opscli seller-sprite ...`，或 Agent 需要代表用户跑正式 CLI 命令时，默认就是这条链路。
- 这条链路依赖本机 OPS 登录态；未登录、登录态过期、返回授权类错误时，先执行：

```bash
opscli auth login
```

- 登录完成后再重试原命令。
- 不要让用户手动传 `api_key`、远端 MCP URL、Cookie 或内部账号参数。
- 不要把此链路的问题误判为卖家精灵业务账号异常；先确认 CLI 登录态。

### B. 远端 MCP 直连链路

适用入口：

- 宿主环境已经连接远端 MCP，并直接调用 `seller_sprite_*` tools。
- 当前上下文不是本机 CLI 命令，而是 MCP 工具协作环境。

判断规则：

- 远端 MCP `api_key` 只表示“能连接 MCP 服务”，不等于当前 MCP 用户已有 OPS 登录态。
- 如果只有 `api_key`，不要直接执行会消耗额度的 `seller_sprite_run`。
- 先完成 MCP 授权登录，让当前 MCP 用户的远端凭证里存在可复用 OPS `session_id`；再调用 `seller_sprite_run`。
- 如果工具返回需要 `session_id`、未授权、授权过期等错误，优先走 MCP 授权流程，而不是要求用户重新给业务参数。

### 快速判断表

| 当前入口 | 优先动作 | 不要做 |
|---|---|---|
| `opscli seller-sprite ...` 报未授权 | 执行 `opscli auth login` 后重试 | 不要让用户传 api_key |
| MCP 直连 `seller_sprite_run` 报未授权 | 先完成 MCP 授权登录 | 不要直接重跑消耗额度工具 |
| 只是查场景/额度/任务状态 | 可先调用对应只读工具 | 不要误判为业务采集失败 |
| 用户只说“登录一下/授权一下” | 根据当前链路选择 CLI 登录或 MCP 登录 | 不要混用两套登录态 |

## 最小工作流

1. 先按用户意图映射场景；拿不准时再读取参数手册确认。
2. 缺少必填参数时，只问当前场景真正缺的字段。
3. 条件齐全后，构造 `scenario + site + period + params`。
4. 普通场景用 `seller_sprite_run`，默认会先等待结果；只有任务进入 `running` 后超过 8 分钟仍未完成时，才返回 `job_id` 供后续查状态、取导出文件复用。
5. `listing-analysis` 用三段式：先 submit，等待约 3 分钟，再 status/result 续查；不要让 `seller_sprite_run` 同步阻塞等待 `listing-analysis` 完整结果。
6. 用户想先看今天还剩几次额度时，优先走 `seller_sprite_quota_status`，或正式 CLI `opscli seller-sprite quota-status`。
7. 如果当前宿主是 MCP 工具协作环境，继续阅读 [SKILL_MCP.md](SKILL_MCP.md) 的工具链和异步规则。

## Listing Analysis 三段式 CLI

Listing Analysis 结果通常 3 分钟以上才生成，正式 CLI 推荐拆成三步：

```bash
opscli seller-sprite listing-analysis-submit --asin B0XXXX --station GLOBAL --site US
opscli seller-sprite listing-analysis-status <job_id>
opscli seller-sprite listing-analysis-result <job_id> --export-format json
```

- `submit` 返回 `job_id` 后不要重复提交同一 ASIN。
- `status/result` 返回 `ready=false` 时，提示用户稍后继续查。
- `result` 返回 `ready=true` 时，再展示 `row_count` 和导出文件。

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
- 如果 `seller_sprite_run` 因运行超时才返回 `job_id`，补充 `queue_duration` 和 `running_duration`，说明当前是排队久还是执行久。
- 若 `seller_sprite_run` 响应顶层存在 `quota`，补一句：
  - `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
- `seller_sprite_run` 和 `seller_sprite_listing_analysis_submit` 会消耗次数；`seller_sprite_scenarios`、`seller_sprite_quota_status`、`seller_sprite_job_status`、`seller_sprite_export` 以及 Listing Analysis 的 `status/result` 不消耗次数。
- `row_count=0` 时，要明确告诉用户没有查到数据，并提醒核对站点、ASIN、关键词、类目或筛选条件是否过窄。
- 用户后来只说 `继续`、`查结果`、`刚才那个好了没` 时，直接复用最近一次 SellerSprite `job_id`，不要要求用户重新描述整单请求。
