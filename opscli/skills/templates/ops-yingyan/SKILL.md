---
name: ops-yingyan
description: 仅当用户明确提到“鹰眼”或“PND”，或明确要求使用鹰眼数据时，通过 opscli-mcp 查询鹰眼数据集目录、执行窄范围只读 SQL、搜索相似词或查询报告任务状态。普通 Amazon、销售、选品或数据分析请求不得自动触发。
metadata:
  mcp-version: v1.0.0
---

# ops-yingyan

通过 `opscli-mcp` 暴露的 `ext_pnd_*` Tools 使用鹰眼数据。`pnd` 只是技术 ID；面向用户统一称“鹰眼”。

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
2. 用站点、价格带、最小市场规模、时间范围等条件先形成小候选集。
3. 对少量精确类目 ID 查询竞争、新品或月度趋势，不做全站多表大聚合。
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
