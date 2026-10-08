---
name: ops-yingyan
description: 仅当用户明确提到“鹰眼”或“PND”，或明确要求使用鹰眼数据时，沿 opscli CLI 到远端通用 MCP 的代理链路，或在宿主已直连 MCP 时调用 ext_pnd_* 查询鹰眼数据；普通 Amazon、销售、选品或数据分析请求不得自动触发。
metadata:
  mcp-version: v1.0.0
---

# ops-yingyan

鹰眼 PND 是远端通用 MCP 服务挂载的第三方 MCP，服务端向调用方暴露 `ext_pnd_*` MCP Tools。`pnd` 只是技术 ID；面向用户统一称“鹰眼”。

## 调用链路与运行模式

入口按以下优先级选择：如果当前发行版或宿主提供正式的 CLI 到远端 MCP 代理入口，优先使用该入口；否则仅在宿主已经直连 MCP Tools 时使用 MCP 直连。

```text
opscli CLI
→ 本地 OPS 登录态
→ 获取远端 MCP 配置/API Key
→ 连接远端通用 MCP（优先 BI运营系统）
→ 远端服务挂载或代理第三方鹰眼 PND
→ ext_pnd_*
```

- CLI/终端模式使用当前安装提供的 `opscli` 远端 MCP 代理能力。CLI 自动使用本地 OPS 登录态获取远端配置并请求远端工具；不要让用户启动本地 `opscli-mcp`、注册 stdio 服务、填写 PND 地址或提供 API Key。
- `opscli-mcp` 在这里指通用 MCP 服务端组件，不是 CLI 用户为本次查询临时启动的本地进程；`opscli mcp` 只管理服务端、用户和第三方上游，也不是鹰眼查询命令。
- 正式 CLI 入口是 `opscli yingyan`，它把命令映射到远端通用 MCP 的 `ext_pnd_*` Tools。不要改用 `opscli query metadata`，也不要把普通 Query 结果冒充鹰眼。
- 只有当前宿主明确直连并暴露 `ext_pnd_*` MCP Tools 时，才走 MCP 直连路径；该路径不需要再经过 CLI。

### CLI 与服务端代理的边界

- `opscli.mcp.tools.yingyan_proxy` 是 `opscli-mcp` 服务端注册代理的实现，不是 CLI 客户端接口。CLI 模式不得从本地 Python/PowerShell 脚本导入并直接调用它来模拟远端工具。
- 不要为规避入口缺失而临时拼接 `python -c`、here-string、`asyncio.run(...)` 或工作区脚本；这类脚本失败属于本地调用包装错误，不能证明 PND 服务不可用。
- 当前安装若没有 `opscli yingyan --help` 或该命令执行失败，报告 CLI 入口缺失；不要自行编写替代脚本。只有真正通过 CLI 代理或 MCP 直连拿到鹰眼目录后，才进入 SQL 工作流。

CLI 代理和 MCP 直连是两种入口，不能把一条入口的可见性当成另一条入口的能力判断。查询规则和错误处理规则对两条入口相同。

## 入口检查

- CLI/终端模式：确认 `opscli yingyan --help` 可用，并确认本地 OPS 登录态可用；`opscli query metadata` 只能证明普通 Query 能力，不能作为鹰眼入口。
- MCP 直连模式：检查当前 Agent 的已挂载工具列表是否包含 `ext_pnd_list_available_datasets`、`ext_pnd_execute_readonly_sql` 或 `ext_pnd_search_similar_terms`。

- MCP 直连工具已挂载，或 CLI 代理入口可用：按本 Skill 的典型工作流执行。
- 两种入口都不可用：说明当前环境没有鹰眼调用入口，保留原始能力缺口，不要用 `opscli query metadata`、其他内部数据集或普通 SQL 结果替代 PND。

在任一入口真正返回目录前，不要声称已经读取 PND 目录，也不要开始构造 PND SQL。

## 正式 CLI 命令

CLI 自动使用本地 OPS 登录态获取远端 MCP 配置，并请求“BI运营系统”中的鹰眼代理：

```powershell
# 读取目录；执行 SQL 前必须先做这一步
opscli yingyan datasets

# 直接传短 SQL；长 SQL 或含中文时推荐使用 UTF-8 文件
opscli yingyan execute-sql --sql "SELECT category_id FROM <目录返回的表> WHERE site = 'US' LIMIT 1"
opscli yingyan execute-sql --sql-file .\query.sql

# 相似词与已有报告任务
opscli yingyan search-similar-terms "stereo amplifier" --site US --top 20
opscli yingyan report-task-status <task_id>
```

`execute-sql` 必须且只能提供 `--sql` 或 `--sql-file` 一个参数；SQL 文件按 UTF-8 读取。命令输出远端 MCP 的 JSON 响应，失败时保留错误码供反馈和诊断。

## 触发边界

只有满足以下任一条件才使用本 Skill：

- 用户明确说“鹰眼”“鹰眼数据”或“鹰眼 PND”。
- 用户明确要求使用 PND 数据或 `ext_pnd_*` Tool。

普通 Amazon 选品、类目分析、关键词、销量、广告或经营分析请求，即使鹰眼可能有相关数据，也不得自动路由到本 Skill。不要主动建议改用鹰眼；只有用户明确选择后才调用。

## 可用场景

| 用户意图 | MCP Tool | 用途 |
| --- | --- | --- |
| 查看能查什么 | `ext_pnd_list_available_datasets` | 返回当前用户可访问的数据集、物理表、可见字段、字段说明和索引提示 |
| 查询鹰眼数据 | `ext_pnd_execute_readonly_sql` | 执行服务端校验通过的单条只读 SQL |
| 扩展相似搜索词 | `ext_pnd_search_similar_terms` | 按站点和种子词返回语义相似的搜索词 |
| 续查已有报告任务 | `ext_pnd_get_report_task_status` | 使用已有 `task_id` 查询报告任务状态 |

## 查询铁律

1. **先目录、后 SQL**：当前任务第一次执行 SQL 前必须调用 `ext_pnd_list_available_datasets`。数据集目录是表名、字段名、字段口径和索引的唯一事实来源，不凭记忆猜字段。
2. **只用已授权结构**：SQL 只能使用目录返回的 `sql_scope.from` 和 `visible_columns`。只生成单条 `SELECT` 或 `WITH ... SELECT`，不得访问未列出的表或列。
3. **条件必须收窄**：查询必须带能显著缩小扫描范围的条件。优先组合站点与时间范围、精确类目 ID、精确 ASIN、精确搜索词或任务 ID；大型表只按 `site` 过滤仍视为过宽。
4. **索引优先**：优先按目录的 `index_hints` 组织 `WHERE`、`ORDER BY` 和分组。需要最新一条记录时，用已知主键或搜索词过滤后 `ORDER BY <时间字段> DESC LIMIT 1`。
5. **明确列和行数**：禁止 `SELECT *`。预览、明细和排行默认 `LIMIT 20`，一般不超过 `100`；确需更多结果时分批查询，并让每批继续保留窄条件。
6. **先过滤再聚合**：聚合前必须先限定站点、日期和业务对象。禁止对大表执行无业务对象约束的全表 `COUNT(*)`、`MAX(date)`、`MIN(date)`、`DISTINCT` 或全局排序。
7. **避免低选择性模糊匹配**：避免前导通配符 `LIKE '%词%'` 和大范围 `OR`。搜索词扩展优先使用 `ext_pnd_search_similar_terms`；名称模糊匹配必须同时限定站点、层级或其他高选择性字段，并设置小 `LIMIT`。
8. **一次只回答一个取数问题**：不要把多个独立分析塞进一条复杂 SQL。先取得最小必要证据，再决定是否需要下一条依赖查询。
9. **0 行不自动放宽**：0 行是有效结果，不是工具失败。说明当前条件无数据；只有用户同意或能确定某个精确条件写错时才调整，不得自动删除站点、日期或主键条件。
10. **不暴露内部信息**：不要输出上游 URL、Authorization、API Key、用户邮箱 Header、内部配置路径或长篇原始响应。

## 30 秒截止时间与重试

鹰眼 Tool 的总截止时间为 30 秒。Agent 必须遵守：

- 一次超时后，**禁止自动重放相同 Tool 参数或相同 SQL**。
- 不通过连续轮询、换一种等价写法或并发提交来规避截止时间。
- 若能设计出明显更窄的新查询，可在说明降级原因后执行一次，例如增加精确搜索词、类目 ID、短日期范围和更小 `LIMIT`；这属于重写查询，不是重放。
- 无法进一步收窄时立即停止，基于已成功取得的数据交付结论，并明确缺失证据。
- `UPSTREAM_MCP_TIMEOUT`、其他 `success=false` 或异常按项目规则立即进入 `ops-feedback`；反馈完成后继续降级交付，不因反馈再次执行原查询。
- 如果 `ext_pnd_list_available_datasets` 成功，但后续工具返回 `UPSTREAM_MCP_CALL_FAILED`，说明 CLI/MCP 到远端通用 MCP 和鹰眼上游的路由已经打通；问题在上游工具执行、SQL 合同或上游服务状态，不能归因于“没有挂载 Skill”。保留错误码，按查询规则只尝试一次明显更窄的重写。
- 如果错误发生在本地临时脚本的语法、转义或导入阶段，说明请求尚未发出；修正入口或停止，不要把它当成鹰眼 SQL 失败反复重试。

## Tool 参数

### `ext_pnd_list_available_datasets`

无参数。返回当前用户可访问的数据目录。

```text
ext_pnd_list_available_datasets()
```

执行 SQL 前，从响应中确认：

- `name` / `display_name` / `description`
- `visible_columns[].name` 和字段说明
- `sql_scope.from` 与 `sql_scope.notes`
- `index_hints[].columns`

### `ext_pnd_execute_readonly_sql`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `sql` | string | 是 | 经过目录校验、条件收窄的单条只读 SQL |

```text
ext_pnd_execute_readonly_sql(
  sql="SELECT <必要列> FROM <sql_scope.from> WHERE site = 'US' AND category_id = '<精确类目ID>' AND month BETWEEN '<开始月>' AND '<结束月>' ORDER BY month DESC LIMIT 12"
)
```

示例中的表名和字段只是结构示意；执行前必须替换为当次数据目录真实返回的值。

### `ext_pnd_search_similar_terms`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `search_term` | string | 是 | 单个明确的种子搜索词 |
| `site` | string | 否 | Amazon 站点；已知时显式传入，例如 `US` |
| `top` | integer | 否 | 1-1100；默认建议 20，通常不超过 50 |

```text
ext_pnd_search_similar_terms(search_term="stereo amplifier", site="US", top=20)
```

不要用空词、过宽的单字母或无业务含义的词调用。需要多个种子词时串行处理，每次先判断上一组结果是否已经足够。

### `ext_pnd_get_report_task_status`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | 是 | 上游已经创建的报告任务 ID |

```text
ext_pnd_get_report_task_status(task_id="<已有任务ID>")
```

本 Tool 只用于续查已有任务。没有 `task_id` 时不得编造，也不要用它搜索任务。

## 典型工作流

### 精确数据查询

1. 确认用户明确要求鹰眼。
2. 调用 `ext_pnd_list_available_datasets`。
3. 根据用户问题选择一个数据集，核对表、字段、口径和索引。
4. 将业务条件补齐为站点、时间范围和至少一个精确对象；缺少会导致宽扫描的条件时先向用户澄清。
5. 构造只选择必要列、使用索引条件并带小 `LIMIT` 的 SQL。
6. 调用一次 `ext_pnd_execute_readonly_sql`。
7. 只有结果提出新的、依赖上一步证据的问题时，才执行下一条窄查询。

### 相似词扩展

1. 确认站点和单个种子词。
2. 调用 `ext_pnd_search_similar_terms`，默认 `top=20`。
3. 需要验证搜索频率时，先从数据目录确认搜索词表及索引，再用精确词集合、明确月份和小 `LIMIT` 查询。
4. 不先对整站搜索词表求最新日期或总行数。

### 类目初筛

1. 从数据目录选择类目筛选或市场规模数据集。
2. 先用站点、单个明确统计期或最新日期、必要的机会阈值，且只选候选所需的少量列和很小的 `LIMIT`，形成候选集；避免一次取多组中文明细列并做无界全局排序。
3. 再对少量精确类目 ID 查询竞争、新品或月度趋势，不做全站多表大聚合。
4. 输出一个候选时，同时说明市场、竞争、利润/价格和风险证据；指标缺失时不伪造评分。

## 执行前自检

调用 `ext_pnd_execute_readonly_sql` 前逐项确认：

- 用户明确要求鹰眼或 PND。
- 本轮已读取数据集目录。
- 表名和每个字段都在当前目录响应中。
- 查询只选择回答问题需要的列。
- 大表同时包含站点、短时间范围和精确业务对象中的适用条件。
- `WHERE` 优先命中 `index_hints`。
- 明细、预览和排行带合理 `LIMIT`。
- 没有全表统计、前导通配符或无界排序。
- 发生过超时时，本次不是相同参数重放。

## 回复规则

- 说明使用了哪个鹰眼数据集、站点、时间范围和关键筛选条件。
- 区分全市场、Top100 快照、搜索词排名和模型指数等不同口径，不混用概念。
- 结论绑定真实返回行；说明数据最新月份、0 行、空字段或数据延迟。
- 超时降级时说明未取得的证据和已保留的有效证据，不把不完整结果包装成完整分析。
- 工具失败反馈成功后返回 `feedback_uuid`，但不要让反馈过程淹没业务结论。
