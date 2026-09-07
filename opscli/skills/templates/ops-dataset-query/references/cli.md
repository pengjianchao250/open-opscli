---
name: ops-dataset-query-cli
description: 当前账号元数据的 CLI-only 规划、权限枚举与查询路由
---

# CLI-only 运行契约

## 主线：一体化入口 `opscli query flow`

`opscli query flow` 是内核化后的 CLI 主线入口，一次调用内完成规划与执行（`status=planned` 的数据集查询）。SKILL.md 的「查询规划主线」是权威流程说明，本节只补全参数与示例，供需要精确控制调用参数时查阅。

```bash
opscli query flow <request> [--query-file <文件>] [--field <字段> ...] \
  [--limit <行数>] [--order-by <字段>[:asc|desc] ...] [--offset <偏移>] \
  [--result-dir <目录>] [--pretty]
```

| 参数 | 说明 |
| --- | --- |
| `request`（位置参数） | 自然语言查询原文，保留原始表述，不要自行改写成关键词 |
| `--query-file <文件>` | 从 UTF-8 文件读取查询原文，用户请求含引号等特殊字符时改用本参数 |
| `--field <字段>` | 补充点名字段，可重复传入 |
| `--limit <行数>` | 返回行数上限；不传则自动补齐服务端默认页（最多 5000 行） |
| `--order-by <字段>[:asc\|desc]` | 排序，形态为「结果字段名[:asc\|desc]」，可重复传入实现多级排序；只认 `asc`/`desc`，省略方向默认升序 |
| `--offset <偏移>` | 分页偏移；不传则后端默认 0 |
| `--result-dir <目录>` | **必须每次都传**：传入后全量结果落盘到该目录（文件名 `query_result_<秒级时间戳>.json`），返回体中的结果收窄为预览行；不传则不做截断，大结果集会原样进入返回体、撑爆上下文 |
| `--pretty` | 格式化输出 JSON，便于人工阅读；Agent 消费时通常不需要 |

返回体固定为 `{"success", "command", "data", "error"}`；`data` 内含规划合同全部字段（`status`/`model_view`/`answer_contract`/`execution_ref` 等）+ `result`（`status=planned` 时的查询结果）+ `result_disclosures`（行数/总数/截断/自动补齐/limit/币种披露，另按场景带 `order_disclosure_zh`、`order_fallback`、`freshness_disclosure_zh`，`--result-dir` 时另有 `full_result_file`；**未传 `--result-dir` 且行数超过 20 行时会出现 `large_result_warning_zh`**，提示全量行已原样进入返回体，此时**必须补传 `--result-dir` 并原样重跑**，不能忽略）+ `evidence_contract` 或 `evidence_contract_error`（构建证据合同失败时）。多币种（`multi_currency=true`）时 `data` 顶层只有 `requested_global_currencies`、`currency_results[]` 与 `comparison_contract`，**没有** `result`/`result_disclosures`/`evidence_contract`；每个 `currency_results[i]` 含 `requested_currency`/`returned_currency`/`currency_matches_request`/`result`，其中 `result` 是一份完整的单币种子合同（它的 `result_disclosures` 与 `evidence_contract` 和 `result` 同级），**行数据在 `currency_results[i].result.result.data`**，比单币种多一层嵌套；对比规则见 `comparison_contract.rules_zh`；`clarify_required`/`blocked` 合同不含 `result`、`result_disclosures` 与证据合同键。`success=false` 时看 `error.code`/`error.message`，原样重跑一次仍失败即转 SKILL.md「规划器不可用时的降级路径」。

示例（含 TopN 的常规查询，排序行数交给规划器）：

```bash
opscli query flow "近7天各渠道订单量前3" \
  --result-dir /tmp/opscli-query-results --pretty
```

**TopN/排序通常不需要手动追加**：规划器已能解析「按ACOS降序排列，只要前5行」「订单量前3名的渠道」，以及「前3」「前十」「top5」这类**不带「名/行/条」单位**的写法（唯一例外是数字后紧跟时间单位的时间表述，如「前7天」「前3个月」，那是时间范围不是行数），解析结果直接写入模板的 `orderBy`/`limit`。本次只选了一个指标时按该指标降序；含时间粒度维度（日期/月份等）且用户未点名排序时按该时间维度升序。

只有两种情况才手动追加 `--limit <N>` / `--order-by <结果字段>[:asc|desc]`：用户确有 TopN/排序意图但合同里 `orderBy`/`limit` 仍为 `null`（多指标且用户未点名排序字段时规划器故意不下发，改为在 `answer_contract.required_disclosures_zh` 强制披露），或需要精确控制分页。显式参数会覆盖模板同名值；未识别到该类明确意图时不得凭空追加这两个参数。

```bash
# 两个指标、且「按X取前N」不构成规划器识别的排序表述 → 合同的 orderBy 与 limit 均未下发
# （此时 required_disclosures_zh 会强制披露「未应用排序与行数限制」），按用户口径显式补齐
opscli query flow "近7天各渠道的销售额和订单量，按销售额取前5" \
  --limit 5 --order-by price:desc \
  --result-dir /tmp/opscli-query-results --pretty
```

## 手动构造路线（维护 / 精确控制，非常规路径）

```text
opscli query plan -> 当前账号组件枚举（内核自动完成） -> opscli query simple
```

该路由**不是**常规取数路径（SKILL.md 已明确一体化入口才是主线），仅用于维护者复现审计、需要精确控制查询 payload，或规划器已返回 `clarify_required`/`blocked` 且已按合同处置后需要手工继续的场景。除上述例外，一律走 `opscli query flow`。

若确需手动构造，先只规划不执行（`opscli query plan` 与 `opscli query flow` 共用同一内核规划器，同样按平台 30 秒命令窗口设计：常态数秒到 30 秒内返回，首次调用会同步刷新一次用户级元数据缓存、整条命令可能耗时到 60 秒，超过 30 秒不要中断，等命令自然返回；元数据未就绪时内核同步刷新一次用户级缓存，仍不就绪返回 `status=blocked, recovery_state=refresh_failed`，执行其 `recovery_command`（`opscli skills upgrade ops-dataset-query`）后重跑；偶发窗口超时原样重跑一次，规划器幂等）：

```bash
opscli query plan "$USER_REQUEST" [--query-file <文件>] [--field <字段> ...] [--top-n <候选上限>] --pretty > "$PLAN_FILE"
```

输出固定为 `{"success", "command", "data", "error"}`，`data` 即规划合同 `query_plan_model_contract_v2`（`model_view` / `answer_contract` / `execution_ref`），Agent 只消费这三部分。不要重复读取版本、列目录、检查源码或扫描元数据：规划器只消费当前账号的后端授权元数据（经用户级缓存），Skill 目录里的 `data/` 不参与规划；元数据未就绪时规划器会先自动刷新一次，仍返回 `status=blocked` 时按 `model_view.recovery_command` 处置后重新规划。登录/账号发生变化时同样先重新规划。

## 1. 选表与字段

- `status=planned` 且 `execution_ref.query_template` 存在：数据集、字段、时间和权限动作均已就绪，可进入执行。
- `status=clarify_required`：只按 `model_view.clarification_messages_zh` 提问，用户确认前停止。
- 字段与聚合口径只采用 `model_view` 的中文字段和 `execution_ref` 中对应的授权执行字段；`execution_ref` 字段带 `aggregation_policy`（公式或快照口径）时按其执行，不再传普通 `aggregation`。

## 2. 明确筛选与权限枚举

未指定筛选值时使用 `current_authenticated_account` 默认可见范围，不添加平台、国家、部门、人员或产品默认值。

平台请求读取 `model_view` 与 `execution_ref`：

1. `model_view.platform_semantic_members` 表示请求语义（中文标签）；亚马逊为 SC+VC，明确 SC 或 VC 时不得扩展。内部枚举名在 `execution_ref.platform_semantic_keys`。
2. **规划器默认自动枚举**：待枚举时会自动执行组件查询并回灌重规划，规划器带 `execution_ref.platform_enum_source=auto_enum_service` 即已收敛为终版，直接进入构造。
3. 仅当自动枚举未完成（规划器仍为 `requires_permission_enum`，即实时枚举与本地枚举缓存都不可用）时，按 `model_view` 的阻断/澄清说明处置：先恢复登录态或等待组件服务可用后原样重跑规划，不得手工把平台值塞进查询。

4. 本地规则只做语义匹配，最终值始终原样取自本次服务端返回；内部 alias 不向用户展示。部门/国家等非平台筛选用 `execution_ref.filter_components` 中对应组件的 `component_table_id` 做同样的枚举校验。

- `platform_filter_state=resolved`：正式 filter 只使用 `execution_ref.resolved_platform_values`。
- `status=blocked` 时按 `model_view.next_action` 区分：`block_platform_scope_not_authorized` 当前账号没有请求范围，停止查询；`block_platform_enum_ambiguous` 服务端值无法唯一映射，停止并记录元数据问题；`block_platform_scope_unsupported` 请求的平台不在本 Skill 支持的语义范围，向用户如实说明；`report_component_enum_defect` 组件枚举调用失败（网络/代理抖动或组件元数据异常），原样重跑一次，仍失败提交反馈并停止，不得放大范围。
- 权限收窄只影响请求范围本身，不得据此扩大范围。
- `status=clarify_required` 且 `clarification_reason_codes` 含组件筛选类澄清码时，部门/渠道/国家等筛选值无法唯一锁定，模板已被撤下（fail-closed，绝不放行成全范围查询）；用 `AskUserQuestion` 让用户选定后写回原文重跑。两类澄清码的候选来源不同：
  - `component_filter_value_unmatched`（没有唯一完整等值成员）与 `component_filter_unauthorized`（点名值全部不在授权范围）**会**下发 `model_view.component_candidates_zh`（`field_zh`/`values_zh`/`total`），直接把这些候选展示给用户。
  - `component_filter_field_ambiguous`（同一取值同时属于多个筛选字段）**不下发** `component_candidates_zh`；候选字段名写在 `model_view.clarification_messages_zh` 的文案内（形如「“X”同时是“A”“B”的授权值，无法确定你要按哪个字段筛选」），从该文案取候选，不要去找一个不存在的键。
- 其他澄清码：`metric_not_in_dataset` / `dimension_not_in_dataset`（当前数据集没有点名的指标 / 分组维度，近似字段在 `model_view.field_suggestions_zh`，形态 `[{requested, candidates_zh[]}]`；点名却找不到的字段同时列在 `model_view.unknown_requested_fields`）；`unsupported_currency`（白名单外币种，`model_view.unsupported_currencies` 列出识别到的代码）；`snapshot_metric_window_conflict`（快照指标与流量指标混查且未按日分组，见「3.1 快照指标窗口与默认排序」）。

其他明确筛选必须先经对应组件枚举校验；规划器未返回足够组件来源时，不把文本值静默塞入业务查询。维护者排错可用 `opscli query plan "$USER_REQUEST" --pretty` 查看规划合同中的组件证据（`execution_ref.filter_components`，仅排错用，不进入正常流程）。

## 3. 正式查询

正式执行由 `opscli query flow` 在内核内完成：以规划合同 `execution_ref.query_template` 原样执行，并做完整性摘要校验、执行前字段校验、排序生效校验与兜底、分页补齐、截断披露和证据合同。

**降级态与手动构造路线的正式执行入口统一为 `opscli query simple`**（与 SKILL.md「规划器不可用时的降级路径」一致）：

```bash
opscli query simple --table-id "$TABLE_ID" --payload payload.json --run --pretty
```

字段必须逐字来自规划合同或 `opscli query metadata --dataset <alias>` 返回，并在回答中说明本次未经内核完整性校验；常规路径不得为绕过一体化入口而手工执行。

`opscli query build --output payload.json` + `opscli query run --payload payload.json` 是**手工精细构造**的两步法，只在需要逐项检查或改写 payload 时使用（`query build` 不需要认证，可先离线生成再审阅）；不要在同一次降级里和 `query simple` 混用。

- 公式字段不传额外 `aggregation`；快照类指标默认取最新快照，不跨期累加。
- 环比、同比或上期对比同时传主周期日期 `filters` 和 `dataComparison`。
- 不发明默认筛选，不将局部或截断结果表述为全量。

## 3.1 快照指标窗口与默认排序

- **快照指标窗口收敛**：指标带 `is_snapshot=true`（元数据 `snapshot_metric=1`，如总库存、平台库存）且本次未按时间粒度维度分组时，多日窗口自动收敛为**最新完整快照日**（今天之前的最后一天）。合同给出 `execution_ref.snapshot_policy = {policy: "latest_complete_snapshot_day", snapshot_day, requested_window: {start, end}, metrics[]}`，`model_view.time_scope_zh` 以「快照口径：最新完整快照日 …」开头，`answer_contract.required_disclosures_zh` 含「快照指标已按最新完整快照日 X 取值…未跨日累加」。结论必须说明这是该快照日的切面，不得表述为整个请求窗口的累计或平均。
- **不收敛的两种情形**：按日期维度分组（每天/趋势）时保留完整窗口，按日展示快照序列不求和；环比/同比时主周期与对比周期各取该周期末日的快照，两期口径一致。
- **快照与流量指标混查**：未按日分组时规划器返回 `status=clarify_required` + `snapshot_metric_window_conflict`，提示按日期维度分组或拆成两次查询，不得自行放行。
- **趋势/按日默认排序**：模板含时间粒度维度（日期/月份等）且用户未点名排序时，规划器自动写入 `orderBy: [{"field": <日期字段>, "desc": false}]`（升序）。执行器若发现服务端未按此排序会本地重排，并在 `result_disclosures.order_fallback` / `order_disclosure_zh` 披露；Agent 不需要、也不得自行对趋势结果重新排序。
- `opscli query run` 与 `opscli query simple --run` 均支持三个相同的可选意图归因参数，用于向服务端透传本次选表来源：`--intent-code <编码>`（取自 `query intent` 候选的 `intent_code`）、`--selection-source <来源>`（`planner`/`intent_route`/`local_fallback`/`user_specified` 四选一）、`--match-record-id <ID>`（取自 `query intent` 返回值的 `match_record_id`）。三者均可选，不传不影响查询执行；走 `query intent` 命中候选后应一并透传，便于闭环统计。

## 4. 结果与失败

常规结果按 `SKILL.md` 的最小分析合同输出，不再读取长参考。复杂审计或用户明确要求完整披露时才读取 `references/result-analysis.md`。

0 行、澄清、预期的认证未就绪和用户取消不是工具故障。仅意外 opscli 失败读取 `references/feedback-guide.md` 并提交一次反馈；成功查询不自动提交反馈。

「未登录」错误的处置边界：沙箱/托管环境凭证由平台注入，禁止交互式 `opscli auth login`（Device Flow 在无人环境无法完成）。等待约 1 分钟原样重试一次；仍未登录即停止取数、向用户说明凭证异常并提交一次反馈。

命令失败时输出 `success=false` 与 `error.code`/`error.message`（退出码 1）：未登录、令牌无效等登录类错误按上面「未登录」边界处置；`status=blocked` 且 `recovery_state=refresh_failed` 时执行 `recovery_command` 后重跑；`next_action=report_component_enum_defect`（组件枚举调用失败）原样重跑一次，仍失败按反馈流程处置；其他错误原样重跑一次，仍报同一错误即转 `SKILL.md`「规划器不可用时的降级路径」；无论哪条路径都禁止盲目重试或翻脚本源码。

## 4.1 字段偏好（`opscli query preferences`）

`opscli query preferences [--pretty]` 返回当前用户已保存的图表字段偏好（各数据集的维度/指标）。手动构造路线选字段时优先采用偏好中的字段；规划器主线无需调用。

## 5. 数据集意图目录（`opscli query catalog` / `opscli query intent`）

`opscli query intent` 是 `SKILL.md`「规划器不可用时的降级路径」L2a 层的正式选表入口，`opscli query catalog` 是其辅助读取入口：目录为空或选表失败时，优先用远端实时意图目录路由选表，不依赖本地快照；仅当 `query intent` 不可用、报错或返回 `fallback_required=true` 时才降到 L2b（`opscli query metadata` 数据集卡片选表）。规划器（主线一体化入口）仍可用时不调用这两个命令。

### `opscli query catalog`

读取数据集业务语义索引（dataset catalog），返回完整 catalog JSON（`version`、`intent_count`、`intents` 数组、`query_strategy`）。

```bash
opscli query catalog [--source remote|local] [--fallback-local/--no-fallback-local] [--skills-dir <目录>] [--pretty]
```

- `--source`：数据来源，`remote`（默认，远端优先）或 `local`（仅本地缓存）。
- `--fallback-local` / `--no-fallback-local`：`--source remote` 时远端失败是否回退本地缓存，默认 `--fallback-local`（回退）。
- `--skills-dir`：自定义 Skills 目录，用于读取本地缓存 catalog。
- `--pretty`：格式化输出 JSON。

### `opscli query intent`

将自然语言需求匹配到 `catalog` 中的 intents，返回选表候选与业务约束，并向服务端上报一次匹配事件（fire-and-forget，上报失败不影响匹配结果）。

```bash
opscli query intent -q "<用户原文>" [--source remote|local] [--fallback-local/--no-fallback-local] [--skills-dir <目录>] [--pretty]
```

- `--query` / `-q`（必填）：自然语言查询需求原文。
- `--source`、`--fallback-local/--no-fallback-local`、`--skills-dir`、`--pretty`：含义与 `query catalog` 一致。

输出关键键：

- `matched`：是否命中任一 intent；`false` 时无 `selected`，必须转 L2b。
- `candidates[]`：候选数据集列表，每项含 `intent_code`、`table_id`、`dataset_alias`、`score`、`intent_constraints`（内含 `hard_constraints`/`avoid_when`/`clarify_when`/`recommended_dimensions`/`recommended_metrics`/`default_filters`/`comparison_strategy` 等业务约束）、`routing_status`（`direct_intent` 或 `embedded_intent`）、`embedded_from_table_id`（`embedded_intent` 时指向原始意图行，实际查询仍落在 `table_id` 指向的父表）。
- `ask_user_question_required`：`true` 时候选不唯一（多个候选分数接近），必须用 `AskUserQuestion` 让用户从 `candidates` 里选，不得默认取第一个。
- `fallback_required` / `fallback_reason`：`true` 表示 catalog 为空或无匹配意图，此时转 L2b（`opscli query metadata` 数据集卡片选表，见下方第 6 节；卡片列表在 `data.all_datasets`，中文名在 `description`、补充说明在 `remarks`）。
- `selected`：`matched=true` 且 `ask_user_question_required=false` 时的唯一候选，可直接采用。
- `match_record_id`：本次匹配的服务端归因记录 ID（上报失败时为 `null`）；命中候选并执行查询时须透传，见上方「3. 正式查询」的归因参数说明。

### 典型工作流：intent → 核对字段 → 带归因参数执行

```bash
opscli query intent -q "上周亚马逊美国站销售额" --pretty
# matched=true 且 ask_user_question_required=false 时，取 selected.table_id / selected.dataset_alias
opscli query metadata --dataset <selected.dataset_alias> --pretty   # 逐字核对 field_name
# 按 references/simple-query-guide.md 的形态写好 payload.json，再用降级主线入口执行：
opscli query simple --table-id <selected.table_id> --payload payload.json --run --pretty \
  --intent-code <selected.intent_code> \
  --selection-source intent_route \
  --match-record-id <match_record_id>
```

需要逐项检查或改写 payload 时才换成「3. 正式查询」里的 `query build` + `query run` 两步法，三个归因参数同样传给 `query run`。

---

## 6. 数据集元数据（`opscli query metadata`）

降级 L2b 的选表入口，也是手工构造路线核对 `field_name` 的唯一来源。

```bash
opscli query metadata --pretty                       # 当前账号数据集卡片列表
opscli query metadata --dataset <alias> --pretty      # 该数据集完整字段 + select_columns
opscli query metadata --table-id <id> --pretty        # 同上，按 table_id 指定
opscli query metadata --all-fields --pretty           # 全量元数据：所有授权数据集的所有字段
```

- 不传 `--dataset` / `--table-id` 时返回数据集卡片列表：卡片在 `data.all_datasets`（**没有** `data.datasets` 这个键），中文名在 `description`、补充说明在 `remarks`、别名在 `dataset_alias`、表号在 `table_id`；`dataset_name` 是英文技术名，只用于用户给出精确完整标识时的精确匹配，不用于自然语言选表。
- `--dataset <alias>` / `--table-id <id>` 是**默认的取字段方式**，返回该数据集完整字段（`field_name` / `verbose_name` / 公式配置）与 `select_columns`（可显式筛选列 → 组件数据集 alias，用于枚举校验）。查询 payload 里每个 `field` 必须逐字来自这里；报「字段不存在」时回到本清单重新核对，禁止换名盲试。
- `--all-fields` 一次拉取全部授权数据集的全部字段（`include_all_fields`，经用户级缓存），返回 `data.datasets` + `data.fields` + `dataset_count` / `field_count` / `stale` / `from_cache`，并忽略 `--dataset` / `--table-id` / `--skills-dir`。**只在降级 L2b 里不确定目标字段属于哪张表、或需要跨表比对字段时用**：payload 很大会挤占上下文。`field_count=0` 表示后端尚未上线该能力，退回上面的两步法。
- 远端优先，失败自动回退本地缓存；回退时返回体带 `hint` 说明，可按提示执行 `opscli skills upgrade ops-dataset-query` 更新本地数据。
