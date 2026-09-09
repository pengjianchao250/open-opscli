---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵 MCP 使用规范。用于通过 seller_sprite_* 工具执行场景查询、轮询异步任务、读取导出文件并给出用户可读结果。Listing Analysis 仅在用户明确要求使用“卖家精灵 Listing Analysis”“卖家精灵 AI 全景分析”或“卖家精灵全景分析”时提交。
---

# ops-seller-sprite MCP

先读 [SCENARIO_PARAMS_ZH.md](SCENARIO_PARAMS_ZH.md) 获取场景映射、缺参规则和参数口径；本文件只保留 MCP 工具链和任务跟踪规则。

## MCP 工具

- `seller_sprite_scenarios`：查看支持的场景。
- `seller_sprite_quota_status`：查看当前用户今日剩余额度。
- `seller_sprite_run`：执行普通场景，立即持久化入队并返回任务快照。
- `seller_sprite_job_status`：按 `job_id` 查看一个普通任务，可用 `wait_seconds` 有界等待 0–30 秒。
- `seller_sprite_jobs_status`：按 `job_ids` 批量查看 1–50 个普通任务，可用 `wait_seconds` 有界等待 0–30 秒。
- `seller_sprite_export`：读取普通任务导出文件路径、URL、文件名和 MIME 信息。
- `seller_sprite_listing_analysis_submit`：提交 Listing Analysis 并立即返回本地 `job_id`。
- `seller_sprite_listing_analysis_status`：按 `job_id` 续查 Listing Analysis 提交状态。
- `seller_sprite_listing_analysis_result`：按 `job_id` 读取 Listing Analysis 结果；未完成时返回 `ready=false`。

专属账号绑定不提供 MCP 管理工具。绑定、改绑和解绑只能由部署管理员在 MCP 服务所在主机通过本地 CLI 完成，Agent 不得向用户索取卖家精灵密码。

## 专属账号路由

- 已绑定专属账号的 OPS 邮箱会在统一 quota 切面中自动识别；`seller_sprite_run` 和 `seller_sprite_listing_analysis_submit` 不计入每日额度。
- 专属账号 quota 快照返回 `unlimited=true`，且 `limit`、`remaining`、`reset_at` 为 `null`；不要将空值解释为额度耗尽。
- 未绑定用户继续使用公共账号池和原每日额度策略。
- 专属账号任务固定使用提交时确认的账号引用，不保存密码，也不会在登录失败、解绑或改绑后回退公共账号池。
- 解绑只使尚未领取的 `queued` 专属任务失败；已经 `running` 的任务继续使用领取时账号完成。
- 专属账号异常时应报告原任务失败并联系部署管理员检查绑定，不得重新提交以尝试切换公共账号。

## 工具信封与业务状态

- 顶层 `success=true` 只表示工具请求成功，不表示后台业务已完成。
- 普通 `seller_sprite_run` 成功受理后立即返回 `job_id/state/stage/position`；`state=queued` 或 `state=running` 仍是 pending。
- 单任务返回的 `queued`、`running`、`ready=false`，以及批量返回的 `ready=false`，都不是工具失败或业务失败。
- `wait_seconds=30` 表示一次状态调用最多等待 30 秒。等待窗口到期时返回最新快照，不会取消、标记失败或重新入队已有持久任务。
- 只有明确终态才停止跟踪：普通任务以 `succeeded` / `failed` 为终态；批量响应以 `ready=true` 表示全部任务已进入终态。

## 普通任务编排

1. SellerSprite Tool 会根据远端 MCP `api_key` 自动确保隔离 OPS 登录态；需要提前诊断认证时可显式调用一次 `auth_mcp_login`，但不要向业务 Tool 传 `session_id/jwt`。
2. 根据参数手册确认普通场景和必填参数，只调用一次 `seller_sprite_run`。新增的 `keyword-research`、`aba-research`、`association-traffic`、`traffic-extend`、`keyword-comparison`、`keyword-conversion-rate`、`real-time-bidding` 和 `aba-reverse` 在执行前必须先确认 `seller_sprite_scenarios` 已返回对应场景；Skill 与服务端版本可能不同，未暴露时不得提交或改投其他场景。不得调用内部 start helper，也不要传 `mode`、`browser-route`、`api-direct` 或 `async_mode`。
3. `seller_sprite_run` 会立即持久化入队。保存每个返回的 `job_id`，不要等待 `run` 自身给出最终结果。
4. 只有一个 pending 普通任务时，调用 `seller_sprite_job_status(job_id, wait_seconds=30)`。
5. 有多个 pending 普通任务时，优先每个窗口调用一次 `seller_sprite_jobs_status(job_ids, wait_seconds=30)`，不要逐个轮询。
6. 在同一轮执行 3–4 个有界状态窗口，总预算 90–120 秒；每个窗口结束后移除已终态任务，全部终态时提前停止。
7. 如果预算结束仍有 pending，保留全部未完成 `job_id`，告诉用户可说“继续”或“查结果”。未来用户只说 `继续` / `查结果` / `刚才那些好了没` 时，恢复完整 pending 集合；除非用户明确选择子集，否则不得只查最近一个 ID。
8. pending 任务不得重新提交，不得再次调用 `seller_sprite_run` 查状态，也不得重新消耗额度。`run` 消耗额度；状态和导出不消耗额度。
9. 普通任务终态为 `succeeded` 后，响应已有导出信息时直接展示；只需文件信息时调用 `seller_sprite_export(job_id)`。
10. 用户单任务执行、主要用于人工查看或留档结果时，推荐显式传 `export_format="xls"`；一次运行多个任务、需要继续汇总计算或生成分析报告时，每个任务都显式传 `export_format="json"`，终态后保留 `job_id` 和工作表来源再统一分析。用户明确指定格式时遵从用户选择；未显式传参时继续兼容 Tool 的既有默认值。
11. 需要由 Agent 直接读取、汇总或生成分析报告时，优先显式传 `export_format="json"`。

### 认证与运行环境

- 远端 MCP 直连场景下，SellerSprite Tool 会在缺失或过期时调用一步登录，并把 OPS `session_id` 保存在当前 MCP 用户的隔离凭证里。
- 旧客户端显式传入的 `session_id/jwt` 仅用于版本过渡，远端服务会忽略这些值并继续使用当前 API Key 的隔离凭证。
- 正式 `opscli seller-sprite ...` CLI 代理链路不再透传本机 `session_id/jwt`，本机登录只用于取得当前用户的远端 MCP 配置。
- SellerSprite 登录态由后端缓存；不要手动重复登录。
- 集成账号也由后端缓存；只有 SellerSprite 登录本身失败时，才需要后端刷新账号或登录态。
- 浏览器运行时由部署侧决定；Agent 不负责切换 Patchright / Playwright / Chrome。

### 单任务操作模板

```text
seller_sprite_run(...)
→ 保存 job_id
→ seller_sprite_job_status(job_id, wait_seconds=30)
→ 若仍 pending，在同一轮继续下一次 30 秒窗口，最多共 3–4 个窗口
→ 终态则停止；预算到期则保留该 job_id 供后续继续
```

### 批量操作模板

```text
seller_sprite_run(...) × N
→ 保存所有普通 job_id
→ seller_sprite_jobs_status(job_ids, wait_seconds=30)
→ 从 jobs 中保留所有非终态 ID，在同一轮继续下一次批量 30 秒窗口
→ 最多共 3–4 个窗口；ready=true 时提前停止
→ 预算到期则保留完整 pending 集合供后续继续
```

## Listing Analysis 三段式

Listing Analysis 必须使用 submit/status/result 专用流程，不属于普通任务批量跟踪；`seller_sprite_run` 生产入口会明确拒绝 `listing-analysis`，调用方必须改用 `seller_sprite_listing_analysis_submit`：

显式触发边界：只有用户明确要求使用“卖家精灵 Listing Analysis”“卖家精灵 AI 全景分析”或“卖家精灵全景分析”时才允许调用 submit；普通 Listing 优化、ASIN 分析、竞品分析或通用数据采集请求不得自动触发。已有 `job_id` 的 status/result 续查不受该触发限制，但不得重新 submit。

1. 提交：`seller_sprite_listing_analysis_submit(asin, station="GLOBAL", site="US", export_format="json")`，后端在新版页面显式选择“全景分析”并保存真实 `taskId`；全景分析会消耗卖家精灵 10 次额度，不要重复提交同一 ASIN。
2. 续查：约 3 分钟后调用 `seller_sprite_listing_analysis_status(job_id)`；后端优先通过 `task/original/summary/<taskId>` 聚合主任务和子任务状态，只有本地缺少 `taskId` 时才通过 `usage-log` 按 ASIN 恢复全景报告。
3. 取结果：调用 `seller_sprite_listing_analysis_result(job_id, export_format="json")`；`ready=false` 时继续保留该 Listing Analysis `job_id`，生成后展示 `row_count` 和 `export`。
4. Listing Analysis 的 `job_id` 不得传入 `seller_sprite_jobs_status`；Agent 必须继续使用专用 status/result，不为该工作流推荐通用单任务状态工具。
5. 用户只说“继续/查结果”时，按任务类型恢复：普通任务恢复完整 pending 集合；Listing Analysis 继续调用专用 status/result。

## 认证与运行时边界

- 远端 MCP 直连时，OPS `session_id` 由 `auth_mcp_login` 建立并保存在当前 MCP 用户的隔离凭证里。
- 正式 `opscli seller-sprite ...` CLI 代理链路使用本机 OPS 登录态；未登录时先执行 `opscli auth login`。
- SellerSprite 登录态和集成账号由后端缓存；不要手动重复登录。
- 浏览器运行时由部署侧决定；Agent 不负责切换 Patchright / Playwright / Chrome。
- MCP tools 不可用时，直接说明当前宿主没有可用的 SellerSprite MCP。

## 回复规则

### JSON v2 工作表契约

- SellerSprite 本地 JSON 导出使用 `schema_version="2.0"`，与本地生成的 XLSX 共用格式化工作表，因此中文列名、字段 fallback、值转换、列顺序和辅助 Sheet 含义一致。
- 按 `columns[index]` 解释每个 `rows[*][index]`，不要将行数组转换前误当作对象；使用数组是为了保留 XLSX 中可能重复的表头。
- `number_formats[index]` 是同列 XLSX 使用的 Excel 数字格式（如 `0.00%`）；值保持可计算的数字类型，`null` 表示使用自动格式。
- `sheet_name` 是主表名称；`additional_sheets` 是辅助表列表，每项包含 `name`、`columns`、`number_formats`、`row_count` 和 `rows`，行也按该项的 `columns` 下标对齐。
- `sheet_name/additional_sheets` 表示 XLSX 工作表，不是接口分页；多任务合并时保留 `job_id + 工作表名` 来源，按列名对齐后再聚合，并遍历全部辅助表。
- `traffic-extend` 返回 `Unique Words`、`Asin`，`keyword-miner` 可返回 `Unique Words`，`keyword-comparison` 返回 `ASIN`；其他场景通常为 `additional_sheets=[]`。
- `aba-reverse` 等官方文件导出场景仍只支持 `xls` / `xlsx` 并原样返回官网工作簿，不适用 JSON v2。

- 优先读取 `data.summary`、`data.job_id`、`data.row_count`、`data.export.filename`、`data.export.url`、`data.export.path` 和 `data.export.format`。
- 批量状态优先展示 `data.ready` 与 `data.summary`；从 `data.jobs` 识别并保留每个 pending ID。
- `seller_sprite_run` 顶层存在 `quota` 时，普通用户补充：`今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`；`unlimited=true` 时改为说明“当前用户使用专属账号，不受每日额度限制”，不要拼接空额度字段。
- 未绑定专属账号时，`seller_sprite_run` 和 `seller_sprite_listing_analysis_submit` 消耗次数；专属账号用户不计次。场景、额度、普通单/批状态、导出以及 Listing Analysis status/result 不消耗次数。
- 不要在最终回复中打印完整工具参数、原始 JSON、内部长路径或账号信息。
- 一般场景 `row_count=0` 时，明确提示核对查询条件；`aba-reverse` 例外，其官方 XLSX 不做本地解析，`row_count=0` 不代表工作簿为空，应以导出文件为准。
- `keyword-research` 导出应按卖家精灵官方关键词选品工作簿对齐；实际文件是 `.xlsx`，若请求参数仍使用兼容值 `xls`，回复中以工具返回的真实文件名和格式为准。
- `keyword-research` 默认使用 `page=1/page_size=100`，只获取第一页后完成任务，不自动请求后续分页。
- `association-traffic` 固定查询全部变体，只获取第一页 100 条即完成任务，不自动请求后续分页；导出按官网关联流量 56 列主表格式对齐，只生成业务主表，不生成官网 `Notes` 页。
- `association-traffic` 固定使用 `page_size=100`；browser-route 必须把 ASIN 逐个写入页面输入框并按回车，点击“立即查询”后再点击“用全部变体查询”；不得用静默接口 fallback 冒充已完成页面交互。若接口返回固定 20 条的游客数据，先恢复登录态并重试一次。
- `traffic-extend` 必须提供 1—20 个 ASIN，仅支持 browser-route，固定第一页 100 条；点击“立即查询”并校验 `/prepare` 后，默认点击“用全部变体拓词”，也支持 `variantSelection=sell_well/current`。本地生成 33 列主表、`Unique Words` 和 `Asin`，不生成 `Notes`，不得调用官方全量导出接口。
- `keyword-comparison` 必须分别提供 1 个自己的 ASIN 和 1—10 个竞品 ASIN；仅支持 browser-route 和默认“流量占比”，固定第一页 100 条。必须先校验 prepare 响应；用户未指定时自动点击“用畅销变体拓词”，明确要求当前变体时在 `params` 传 `variantSelection=current` 并点击“用当前变体拓词”。点击变体按钮前才监听主响应，控制参数不进入主请求；prepare 失败或页面交互后未捕获主响应时直接失败，不得使用静默 fallback 或改投 `keyword-reverse`。查询 JSON 在本地生成动态业务主表和 `ASIN` 辅助表，不调用官网额度型导出、不生成 `Notes`。
- `keyword-conversion-rate` 必须提供 1—1000 个关键词词组，仅支持 browser-route，周期只支持按周或近 90 天，固定第一页 100 条。页面录入时每个词组只发送一次 Enter；动作超时后只检查标签计数，禁止盲目补按。标签完整后只点击一次“立即查询”，主响应缺失时不得静默 fallback 或换账号重放。本地生成官方 33 列单业务表，不调用官网导出、不生成 `Notes`。
- `real-time-bidding` 必须且只能提供 1 个 ASIN，仅支持 browser-route。普通历史已完成/失败时自动调用一次“再次查询”，无历史时通过弹窗新建默认“亚马逊推荐关键词”任务，进行中任务只轮询，官网示例只读；完成后分别读取 SP、SB 第一页 100 条并校验关键词集合后合并，本地生成官方 46 列单业务表，不调用官网导出、不生成 `Notes`。提交响应不明时禁止重放，列表摘要或详情当前视图不能冒充列表导出。
- `aba-research` 必须提供父/子 ASIN 或关键词；周/月周期、类目多选、排序和结果筛选按参数手册传递，不支持六种推荐模式。后端固定提交一次 `POST /v3/api/aba-research`，使用 `page=1/size=100`，不请求后续页、不调用官网导出接口；查询 JSON 在本地生成官方 19 列业务主表，不生成官网 `Notes` 页和二维码图片，`row_count` 等于第一页实际行数。
- `aba-reverse` 必须提供 1—20 个 ASIN 或 Amazon 产品链接；周期省略时默认 `reverseType=W` 和最近完整周。只使用 `xls` / `xlsx` 导出，后端直接下载并原样保存官网 `/v2/aba/reverse/export` 返回的完整 XLSX，不截取、解析或重建工作簿。

终态成功模板：

```md
已按 `site` 做好了 `scenario title`，并导出为 `format`。

结果：
- `job_id`: xxx
- 返回行数: 20
- 导出文件: [filename](url-or-path)
```

同轮预算到期模板：

```md
任务仍在后台执行，本次等待窗口到期但任务未失败。我已保留全部未完成任务编号；你可以直接说“继续”或“查结果”，我会续查完整 pending 集合，不会重新提交或再次消耗额度。
```
