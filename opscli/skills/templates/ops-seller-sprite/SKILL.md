---
name: ops-seller-sprite
description: SellerSprite/卖家精灵查询与导出 Skill。用于把中文自然语言需求映射为 seller_sprite_* 场景，处理关键词选品、关键词转化率、实时查竞价、ABA 数据选品、全球商标库、关联流量、流量词对比、ABA 出单词反查、缺参澄清、类目确认、任务续查和 Excel 导出。Listing Analysis 仅在用户明确要求使用“卖家精灵 Listing Analysis”“卖家精灵 AI 全景分析”或“卖家精灵全景分析”时提交。
metadata:
  mcp-version: v1.0.0
---

# ops-seller-sprite

用于把卖家精灵自然语言需求映射成标准场景，并通过正式 MCP 入口完成查询、导出和任务续查。

当前对用户公开的正式 CLI 入口是 `opscli seller-sprite ...`。
该入口默认通过 CLI auth 获取当前用户的远端 MCP 配置，再由远端根据 MCP API Key 自动建立隔离 OPS 登录态并调用 `seller_sprite_*` tool；本 Skill 也以这条正式链路作为默认执行口径。
正式 CLI 依赖本机已完成 OPS 授权；若本机未登录或登录态过期，先完成 `opscli auth login` 再继续。

授权排查先看链路类型：正式 CLI 代理链路优先用本机 `opscli auth login`；远端 MCP 直连链路优先用 MCP 授权工具完成当前 MCP 用户的 OPS 登录。两条链路不要混用判断。

## 快速规则

1. 先识别场景，再决定是否执行；场景不明确时先澄清，不要盲跑。
2. 只追问缺失的必填参数，不追问可选参数；未提供的可选参数交给后端默认值。
3. 默认使用：
   - `site=US`
   - `period=30d`
   - `page_size=100`
   - 未明确导出用途时保留兼容默认 `export_format=xls`；需要由 AI 直接读取、分析或生成结果时优先显式传 `export_format=json`，用户需要人工查看或留档表格时使用 `xls` / `xlsx`。
   - `keyword-research` 例外：`period` 使用数据月份（`YYYY-MM`），不把 `30d` 当作月份；默认 `page=1/page_size=100`，只获取第一页。
   - `association-traffic` 使用公共默认 `page_size=100`，查询固定使用全部变体，不允许改成当前变体。
   - `traffic-extend` 固定第一页 100 条；用户未指定变体时默认“用全部变体拓词”，也支持 `variantSelection=sell_well/current`；查询 JSON 后在本地生成主表、`Unique Words` 和 `Asin`，不生成 `Notes`。
   - `keyword-comparison` 固定使用默认“流量占比”和第一页 100 条；用户未指定时自动选择“用畅销变体拓词”，明确要求当前变体时传 `variantSelection=current`，查询 JSON 后在本地生成动态 XLSX，不调用官网额度型导出。
   - `keyword-conversion-rate` 固定第一页 100 条；周期只支持按周或近 90 天，最多 1000 个关键词词组。页面录入时每个词组只发送一次 Enter，超时后以标签计数判断结果，禁止盲目补按；本地生成官方 33 列业务主表，不生成 `Notes`。
   - `real-time-bidding` 只接受单个 ASIN；普通历史已完成时自动“再次查询”，无历史时通过弹窗新建“亚马逊推荐关键词”任务，进行中任务只等待，官网示例只读；完成后严格合并 SP 与 SB/SBV 第一页 100 条，本地生成官方 46 列业务主表，不生成 `Notes`。
   - `aba-research` 未提供周期时默认最近完整周；固定 `page=1/size=100` 且只查一次，捕获查询 JSON 后在本地生成官方 19 列 XLSX，不调用官网导出接口。
   - `aba-reverse` 未提供周期时默认选择每周和最近完整周；显式周期仍支持具体周结束日或月份。只支持 `xls` / `xlsx`，由后端原样保存官方 XLSX。
4. 用户给了明确条件，就原样带入 `params`；不要发明隐藏枚举值或额外筛选。
5. `月份` / `数据月份` / `2026-04` 传顶层 `period`；只有“上架时间 / 上架月数 / 上架多久”才映射到 `params.putawayMonth`。
6. 类目文本可以直接传；如果后端返回多个类目候选，必须停下来让用户确认，不能猜。
7. 不向用户暴露账号、Cookie、内部运行参数、长本地路径或调试文件。
8. 当前 Skill 的参数词典、场景映射、别名、默认值统一以 [SCENARIO_PARAMS_ZH.md](SCENARIO_PARAMS_ZH.md) 为准。
9. 面向 CLI 说明时，默认引用 `opscli seller-sprite ...` 这条正式命令路径；不要向用户展开底层远端 URL、`api_key` 或内部调试入口。
10. 若返回授权类错误或提示先完成 OPS 授权，优先检查本机 CLI 登录态；不要先把问题归因为卖家精灵账号、场景参数或采集模式。
11. 已由部署管理员绑定专属账号的 OPS 用户会自动使用该账号，`run` 和 Listing Analysis submit 均不消耗每日额度；未绑定用户继续使用公共账号池和原额度策略。
12. 专属账号的绑定、改绑和解绑只能由部署管理员在服务端本机执行 `opscli seller-sprite account-binding ...`，MCP 不提供管理工具；Agent 不得向用户索取或输出卖家精灵密码。
13. 专属账号登录失效时任务直接失败，不会回退公共账号池；不要通过重新提交任务尝试绕过账号异常。
14. Skill 文档出现新场景不等于当前 MCP 已部署；执行 `keyword-research`、`aba-research`、`association-traffic`、`traffic-extend`、`keyword-comparison`、`keyword-conversion-rate`、`real-time-bidding` 或 `aba-reverse` 前先确认 `seller_sprite_scenarios` 已返回该场景，未暴露时如实说明，不能改投其他场景冒充结果。
15. 只有用户明确要求使用“卖家精灵 Listing Analysis”“卖家精灵 AI 全景分析”或“卖家精灵全景分析”时才允许调用 submit；普通 Listing 优化、ASIN 分析、竞品分析或通用数据采集请求不得自动触发。status/result 只续查已有 `job_id`，不受本条触发限制。
16. `competitor-lookup` 的 `asins` 只用于查询指定商品，结果可能展开父子体或变体，不代表从 ASIN 发现了竞品。用户要求“从 ASIN 找竞品”时，转入 `ops-commerce-playbooks` 的“如何找竞品”案例，使用流量词、关键词搜索、关联关系和 StyleSnap 建立候选。

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
opscli seller-sprite job-status <job_id> --wait-seconds 30
opscli seller-sprite jobs-status <job-a> <job-b> --wait-seconds 30
opscli seller-sprite export <job_id>
```

判断规则：

- 用户在本机终端执行 `opscli seller-sprite ...`，或 Agent 需要代表用户跑正式 CLI 命令时，默认就是这条链路。
- 这条链路依赖本机 OPS 登录态；未登录、登录态过期、返回授权类错误时，先执行：

```bash
opscli auth login
```

- 登录完成后再重试原命令；CLI Adapter 不向业务 Tool 透传本机 `session_id/jwt`。
- 不要让用户手动传 `api_key`、远端 MCP URL、Cookie 或内部账号参数。
- 不要把此链路的问题误判为卖家精灵业务账号异常；先确认 CLI 登录态。

### B. 远端 MCP 直连链路

适用入口：

- 宿主环境已经连接远端 MCP，并直接调用 `seller_sprite_*` tools。
- 当前上下文不是本机 CLI 命令，而是 MCP 工具协作环境。

判断规则：

- 远端 MCP `api_key` 同时作为隔离 OPS 登录态的身份依据；SellerSprite 业务 Tool 会在凭证缺失或过期时自动完成一步绑定。
- 可以先调用 `auth_mcp_login` 做显式认证检查，但不再是执行 `seller_sprite_run` 的强制前置步骤。
- 不要向 `seller_sprite_run` 或 Listing Analysis 提交工具显式传递 `session_id/jwt`；旧客户端参数仅为过渡兼容，服务端会忽略。
- 如果自动绑定仍返回未授权或授权过期，检查 MCP API Key 身份，而不是要求用户重新给业务参数。

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
4. 普通场景调用一次 `seller_sprite_run` 后立即持久化入队，并返回 `job_id/state/stage/position`；不要把顶层 `success=true` 当成任务完成。
5. 单个普通任务用 `seller_sprite_job_status(job_id, wait_seconds=30)`；多个普通任务优先用 `seller_sprite_jobs_status(job_ids, wait_seconds=30)`。在同一轮连续执行 3–4 个有界状态窗口，总预算 90–120 秒，全部进入终态时提前停止。
6. `queued`、`running`、`ready=false` 和等待窗口到期都表示仍在 pending，不是失败。预算用完后保留全部未完成 `job_id`；用户后续只说 `继续` / `查结果` 时恢复完整 pending 集合，除非用户明确只选其中一部分。
7. pending 普通任务不得重新提交，也不得再次调用 `run` 查状态，不得重新消耗额度；`run` 消耗额度；状态和导出不消耗额度。
8. `listing-analysis` 必须使用专用 submit/status/result 三段式，等待约 3 分钟后再续查；`seller_sprite_run` 生产入口会明确拒绝 `listing-analysis`，调用方必须改用 `seller_sprite_listing_analysis_submit`；Listing Analysis `job_id` 不得传入 `seller_sprite_jobs_status`。
9. 用户想先看今天还剩几次额度时，优先走 `seller_sprite_quota_status`，或正式 CLI `opscli seller-sprite quota-status`。
10. 如果当前宿主是 MCP 工具协作环境，继续阅读 [SKILL_MCP.md](SKILL_MCP.md) 的工具链和状态规则。

## Listing Analysis 三段式 CLI

Listing Analysis 结果通常 3 分钟以上才生成，正式 CLI 推荐拆成三步：

只有用户明确要求使用“卖家精灵 Listing Analysis”“卖家精灵 AI 全景分析”或“卖家精灵全景分析”时才提交。用户提供已有 `job_id` 或对已提交任务说“继续/查结果”时，可以直接使用 status/result，不能重新 submit。

```bash
opscli seller-sprite listing-analysis-submit --asin B0XXXX --station GLOBAL --site US
opscli seller-sprite listing-analysis-status <job_id>
opscli seller-sprite listing-analysis-result <job_id> --export-format json
```

- `submit` 返回 `job_id` 后不要重复提交同一 ASIN。
- `submit` 会在新版页面显式选择“全景分析”，单次消耗卖家精灵 10 次额度，并从创建响应保存真实 `taskId`。
- `status` 优先读取 `task/original/summary/<taskId>` 的任务数组；本地缺少 `taskId` 时才用 `usage-log` 按 ASIN 和全景分析类型恢复。
- `result` 使用真实 `taskId` 打开 `ai-history?module=LA&taskId=<taskId>`；页面仍显示“正在分析中”时返回 `ready=false`。
- `result` 返回 `ready=true` 时，再展示 `row_count` 和导出文件。

## 缺参澄清原则

- `查关键词` 这类表达可能对应 `keyword-research`、`keyword-miner`、`keyword-reverse`、`traffic-source`，先让用户选场景。
- `关键词选品`、`关键词研究`、`高需求低竞争词`、`市场周期筛选`通常对应 `keyword-research`；单一种子词扩词仍用 `keyword-miner`。
- `ABA 数据选品`、`ABA 关键词趋势`对应 `aba-research`；必须提供父/子 ASIN 或关键词，支持周/月周期、类目 code 多选和搜索结果筛选。不要实现或映射六种推荐模式。
- `关联流量`、`关联产品`、`查关联 ASIN`通常对应 `association-traffic`；必须提供 1—20 个父体或子体 ASIN，固定使用全部变体查询。
- `拓展流量词`、`多 ASIN 拓词`对应 `traffic-extend`；必须提供 1—20 个父体或子体 ASIN，用户未指定变体时默认使用全部变体。
- `流量词对比`、`竞品关键词对比`、`竞品关键词差距`对应 `keyword-comparison`；必须分别提供 1 个自己的 ASIN 和 1—10 个竞品 ASIN，竞品不得包含自己的 ASIN。用户未指定变体时不追问，默认使用畅销变体；用户明确说“当前变体”时传 `variantSelection=current`。
- `关键词转化率`、`批量关键词转化`对应 `keyword-conversion-rate`；必须提供 1—1000 个关键词词组，周期只支持按周或近 90 天。词组内部空格属于关键词内容，不按空格拆分。
- `实时查竞价`、`ASIN 实时竞价`对应 `real-time-bidding`；必须且只能提供 1 个 ASIN。
- `出单词反查`、`ABA 反查`对应 `aba-reverse`；必须提供 1—20 个父体或子体 ASIN 或 Amazon 产品链接。周期可省略，默认使用每周和最近完整周。
- `查产品` 这类表达可能对应 `competitor-lookup` 或 `product-research`，先让用户确认目的。
- `看市场/类目` 这类表达可能对应 `market-research` 或 `product-research`，先让用户确认。
- `competitor-lookup` 不能无条件直接跑，至少要有 `keyword`、`brand`、`sellerName`、`asins` 或 Amazon 商品链接中的一种。
- `competitor-lookup` 如果用户给的是单个 ASIN，也要先归一化成 `params.asins`；不要把单个 ASIN 直接留在 `params.asin` 后就发请求。
- 上一条只说明指定商品查询的参数格式；`params.asins` 返回的是目标商品及可能的父子体/变体，不得把结果命名为“ASIN 竞品”。从 ASIN 发现竞品应读取 `ops-commerce-playbooks` 的“如何找竞品”案例。
- `competitor-lookup` 缺少主筛选条件时，应直接报参数错误或继续澄清，不要等成 30 秒 MCP 超时。
- `keyword-reverse` 必须有 ASIN。
- `traffic-source` 必须有关键词或 ASIN。
- `association-traffic` 必须有 1—20 个合法 ASIN；支持列表、逗号、换行、制表符或从 TXT/Excel 按列复制的文本。
- `traffic-extend` 必须有 1—20 个合法 ASIN；支持列表、空格、逗号、换行、制表符或从 TXT/Excel 按列复制的文本。
- `keyword-comparison` 必须有 1 个自己的 ASIN 和 1—10 个竞品 ASIN；支持列表、空格、中英文逗号、换行或制表符，必须保留两类 ASIN 的角色，不得混成一个列表。
- `keyword-conversion-rate` 必须有 1—1000 个关键词词组；支持数组，或中英文逗号、换行、制表符分隔文本；页面每个词组只发送一次 Enter，动作超时后先检查标签数量，禁止重复按键。
- `aba-research` 必须有父/子 ASIN 或关键词，可用 `q`、`keywordOrAsin`、`keyword` 或 `asin`；类目必须使用页面类目 code，不按自然语言猜 code。
- `aba-reverse` 必须有 1—20 个 ASIN 或 Amazon 产品链接；周期省略时默认最近完整周，显式周周期使用周结束日，月周期使用 `YYYY-MM`。
- `product-research`、`market-research` 和 `keyword-research` 虽然没有硬性必填，但用户条件明显不足时，仍应先确认意图，不要把“可空”误当成“随便跑”。

可直接复用的话术：

- `你想做关键词选品、从种子词扩词、按 ASIN 反查，还是查流量来源？`
- `如果要筛选商品，请提供 keyword、brand、sellerName 或明确的商品 ASIN；如果要从一个 ASIN 发现竞品，我会先反查流量词，再结合关键词搜索、关联关系和视觉相似商品建立候选。`
- `关键词反查需要 ASIN，请提供 ASIN 或 Amazon 产品链接。`
- `查流量来源需要关键词或 ASIN，请补充。`

## 回复规则

### 导出格式选择

| 任务目的 | 推荐格式 | 执行规则 |
| --- | --- | --- |
| 单个任务，用户要打开、下载或留档 | `xls` | 显式传 `export_format="xls"`，最终以工具返回的真实扩展名为准 |
| 多个任务，Skill/Agent 要汇总、计算或生成报告 | `json` | 每个任务显式传 `export_format="json"`，终态后再统一分析 |
| 用户明确指定格式 | 用户指定格式 | 不用默认推荐覆盖用户选择 |

多任务处理时保留 `job_id + sheet_name/additional_sheets.name` 的来源关系，先按列名对齐再聚合，不要只读取主表。场景只支持官方工作簿时（如 `aba-reverse`），仍使用 `xls` / `xlsx`，不要强制改为 JSON。
需要由 Skill/Agent 直接读取、汇总或生成分析报告时，优先显式传 `export_format="json"`。

### JSON 导出读取规则

- SellerSprite 本地 JSON 导出使用 `schema_version="2.0"`，其中文列名、字段 fallback、值转换、列顺序和辅助 Sheet 与本地生成的 XLSX 共用同一份格式化工作表数据。
- 按 `columns[index]` 解释每个 `rows[*][index]`，不要把行数组当作对象；该结构用于保留 XLSX 中可能重复的表头。
- `number_formats[index]` 是同列 XLSX 使用的 Excel 数字格式（如 `0.00%`）；值保持可计算的数字类型，`null` 表示使用自动格式。
- 主表名称读取 `sheet_name`；多 Sheet 场景继续读取 `additional_sheets` 中每项的 `name/columns/rows`，每个辅助表同样按列下标对齐。没有辅助表时 `additional_sheets=[]`。
- `sheet_name/additional_sheets` 表示工作表，不是接口分页；不要把“第一页 100 条”的场景限制与 JSON 多 Sheet 结构混为一谈。
- `traffic-extend` 的辅助表为 `Unique Words` 和 `Asin`，`keyword-miner` 可包含 `Unique Words`，`keyword-comparison` 包含 `ASIN`。
- `aba-reverse` 等官方文件导出场景仍只支持 `xls` / `xlsx`，返回官网原始工作簿，不适用 JSON v2。

- 优先使用工具返回的 `data.summary`，不要改写成原始 JSON。
- 顶层 `success=true` 只表示工具请求成功；仍需检查业务 `state` / `ready`。`queued`、`running`、`ready=false` 和等待窗口到期都保持 pending，不要报告为成功完成或失败。
- 成功时只保留用户关心的信息：场景、关键条件、`job_id`、`row_count`、导出文件。
- 若 `seller_sprite_run` 响应顶层存在 `quota`，补一句：
  - `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
- 未绑定专属账号时，`seller_sprite_run` 和 `seller_sprite_listing_analysis_submit` 会消耗次数；已绑定专属账号时不计次，quota 快照返回 `unlimited=true` 且 `limit/remaining/reset_at` 为空。`seller_sprite_scenarios`、`seller_sprite_quota_status`、`seller_sprite_job_status`、`seller_sprite_jobs_status`、`seller_sprite_export` 以及 Listing Analysis 的 `status/result` 不消耗次数。
- 普通任务等待到期不会取消、标记失败或重新入队；继续保留全部未完成 `job_id`，不得重新提交，也不得调用 `run` 查状态。
- `aba-research` 固定只取第一页 100 条，`row_count` 是第一页实际返回行数；本地 XLSX 不消耗官网导出次数。
- `keyword-comparison` 仅返回默认“流量占比”第一页最多 100 条；本地 XLSX 包含动态业务主表和 `ASIN` 辅助表，不包含 `Notes`，不得宣称已取得自然排名、广告排名、转化效果或曝光位置视图。
- `keyword-conversion-rate` 只返回第一页最多 100 条；本地 XLSX 包含官方 33 列单业务主表，不包含 `Notes`，不调用官网导出接口。
- `traffic-extend` 只返回第一页最多 100 条；本地 XLSX 包含官方 33 列主表、基于当前 100 条计算的 `Unique Words` 和 `Asin`，不包含 `Notes`，不调用官网全量导出。
- `real-time-bidding` 根据普通查询历史自动刷新或创建：已有完成/失败记录调用一次“再次查询”，无记录通过官网弹窗新建默认“亚马逊推荐关键词”任务，已有进行中任务只轮询，官网示例不创建任务；任务完成后返回第一页最多 100 条，按关键词严格合并 SP 与 SB/SBV 并生成官方 46 列单业务表，不包含 `Notes`，不调用官网导出接口。提交后响应不明时禁止自动重放。
- 一般场景 `row_count=0` 时，要明确告诉用户没有查到数据；`aba-reverse` 例外，其官方 XLSX 不做本地解析，`row_count=0` 不代表工作簿为空，应以导出文件为准。
- 用户后来只说 `继续`、`查结果`、`刚才那个好了没` 时，恢复并查询完整 pending 集合；只有用户明确指定子集时才缩小范围。
