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
| `--result-dir <目录>` | **建议每次都传**：传入后全量结果落盘到该目录（文件名 `query_result_<秒级时间戳>.json`），返回体中的结果收窄为预览行；不传则不做截断，大结果集会原样进入返回体、撑爆上下文 |
| `--pretty` | 格式化输出 JSON，便于人工阅读；Agent 消费时通常不需要 |

返回体固定为 `{"success", "command", "data", "error"}`；`data` 内含规划合同全部字段（`status`/`model_view`/`answer_contract`/`execution_ref` 等）+ `result`（`status=planned` 时的查询结果）+ `result_disclosures`（行数/总数/截断/自动补齐/limit/币种披露，`--result-dir` 时另有 `full_result_file`；**未传 `--result-dir` 且行数超过 20 行时会出现 `large_result_warning_zh`**，提示全量行已原样进入返回体，建议补传 `--result-dir`）+ `evidence_contract` 或 `evidence_contract_error`（构建证据合同失败时）。`success=false` 时看 `error.code`/`error.message`，原样重跑一次仍失败即转 SKILL.md「规划器不可用时的降级路径」。

示例（Top3 排序 + 落盘）：

```bash
opscli query flow "近7天各渠道订单量前3" \
  --limit 3 --order-by order_qty:desc \
  --result-dir /tmp/opscli-query-results --pretty
```

规划器对 TopN/排序语义的 NL 解析**不可依赖**（部分表述能解析、部分不能——如"按ACOS降序排列，只要前5行"能解析出 `orderBy`/`limit=5`，"订单量前3名的渠道"能解析出 `limit=3`，但上面示例这类不带"名/行/条"等单位的"前3"就不能唯一解析，未解析时 `orderBy`/`limit` 会是 `null`）；这两个 CLI 参数是 SKILL.md「构造与执行」规则 1 显式列出的例外，识别到 TopN/排序/限定行数意图时必须像上面这样手动追加，不属于"拼参"违规（详见该规则）；显式参数会覆盖模板同名值。

若 `opscli` 命令本身不可用（命令级环境异常，非规划器业务性降级），改用 Skill 自带的备选执行通道 `python3 scripts/query_flow.py "$USER_REQUEST" --result-dir "$RESULT_DIR"`（详见 SKILL.md），返回结构不同（顶层直接是 `status`/`disclosures`/`preview_rows`/`evidence_contract`，不经 `data` 包裹）。

## 手动构造路线（维护 / 精确控制，非常规路径）

```text
query_plan.py -> 当前账号组件枚举 -> opscli query simple
```

该路由**不是**常规取数路径（SKILL.md 已明确一体化入口才是主线），仅用于维护者复现审计、需要精确控制查询 payload，或规划器已返回 `clarify_required`/`blocked` 且已按合同处置后需要手工继续的场景。除上述例外，一律走 `opscli query flow`。

若确需手动构造，直接在 Skill 目录执行（规划器按平台 30 秒命令窗口设计：
常态 1~3 秒返回；需要刷新元数据时前台最多等 8 秒、未完成即转后台续跑并返回
`recovery_state=refresh_in_progress`，此时直接执行其 `recovery_command`（sleep+重跑
合并的一条命令）即可，禁止自行升级；偶发窗口超时原样重跑一次，规划器幂等）：

```bash
python3 scripts/query_plan.py "$USER_REQUEST" > "$PLAN_FILE"
```

不要重复读取版本、列目录、检查源码或扫描元数据。规划器只消费当前账号下发的 `data/`；元数据未就绪时规划器会先自动执行一次升级兜底，仍返回 `status=blocked` 时按规划器 `model_view.recovery_command`（`opscli skills upgrade ops-dataset-query`）手动刷新后重新规划。登录/账号/元数据所有权发生变化时同样先刷新再规划。

规划器默认输出模型合同（`model_view` / `answer_contract` / `execution_ref`），Agent 只消费这三部分。`--output-mode internal` 输出内部完整合同，仅供维护者排错，不进入正常流程。

## 1. 选表与字段

- `status=planned` 且 `execution_ref.query_template` 存在：数据集、字段、时间和权限动作均已就绪，可进入执行。
- `status=clarify_required`：只按 `model_view.clarification_messages_zh` 提问，用户确认前停止。
- 字段与聚合口径只采用 `model_view` 的中文字段和 `execution_ref` 中对应的授权执行字段；`execution_ref` 字段带 `aggregation_policy`（公式或快照口径）时按其执行，不再传普通 `aggregation`。

## 2. 明确筛选与权限枚举

未指定筛选值时使用 `current_authenticated_account` 默认可见范围，不添加平台、国家、部门、人员或产品默认值。

平台请求读取 `model_view` 与 `execution_ref`：

1. `model_view.platform_semantic_members` 表示请求语义（中文标签）；亚马逊为 SC+VC，明确 SC 或 VC 时不得扩展。内部枚举名在 `execution_ref.platform_semantic_keys`。
2. **规划器默认自动枚举**：待枚举时会自动执行组件查询并回灌重规划，规划器带 `execution_ref.platform_enum_source=auto_enum_service` 即已收敛为终版，直接进入构造。
3. 仅当自动枚举未完成（规划器仍为 `requires_permission_enum`）时走手动路径：直接执行规划结果内嵌的 `execution_ref.platform_enum_command`（现成命令，无需手拼 payload），再将返回的平台值逐项传回：

```bash
python3 scripts/query_plan.py "$USER_REQUEST" \
  --authorized-platform-value "$CURRENT_ACCOUNT_PLATFORM_VALUE"
```

4. 本地规则只做语义匹配，最终值始终原样取自本次服务端返回；内部 alias 不向用户展示。部门/国家等非平台筛选用 `execution_ref.filter_components` 中对应组件的 `component_table_id` 做同样的枚举校验。

- `platform_filter_state=resolved`：正式 filter 只使用 `execution_ref.resolved_platform_values`。
- `status=blocked` 时按 `model_view.next_action` 区分：`block_platform_scope_not_authorized` 当前账号没有请求范围，停止查询；`block_platform_enum_ambiguous` 服务端值无法唯一映射，停止并记录元数据问题；`block_platform_scope_unsupported` 请求的平台不在本 Skill 支持的语义范围，向用户如实说明。
- 权限收窄只影响请求范围本身，不得据此扩大范围。

其他明确筛选必须先经对应组件枚举校验；规划器未返回足够组件来源时，不把文本值静默塞入业务查询。维护者排错可用 `python3 scripts/query_plan.py "$USER_REQUEST" --output-mode internal` 查看完整组件证据（仅排错用，不进入正常流程）。

## 3. 正式查询

以规划器 `execution_ref.query_template` 构造参数，正式执行必须绑定同一份规划器文件：

```bash
python3 scripts/run_query.py --table-id "$TABLE_ID" --json "$QUERY_JSON" --plan-file "$PLAN_FILE"
```

执行器会硬校验 plan 状态、tableId、维度/指标/筛选字段以及模板就绪状态，不得改用 `opscli query simple` 绕过绑定。

- 公式字段不传额外 `aggregation`；快照类指标默认取最新快照，不跨期累加。
- 环比、同比或上期对比同时传主周期日期 `filters` 和 `dataComparison`。
- 不发明默认筛选，不将局部或截断结果表述为全量。
- `opscli query run` 与 `opscli query simple --run` 均支持三个可选意图归因参数，用于向服务端透传本次选表来源：`--intent-code <编码>`（取自 `query intent` 候选的 `intent_code`）、`--selection-source <来源>`（`planner`/`intent_route`/`local_fallback`/`user_specified` 四选一）、`--match-record-id <ID>`（取自 `query intent` 返回值的 `match_record_id`）。三者均可选，不传不影响查询执行；走 `query intent` 命中候选后应一并透传，便于闭环统计。

## 4. 结果与失败

常规结果按 `SKILL.md` 的最小分析合同输出，不再读取长参考。复杂审计或用户明确要求完整披露时才读取 `references/result-analysis.md`。

0 行、澄清、预期的认证未就绪和用户取消不是工具故障。仅意外 opscli 失败读取 `references/feedback-guide.md` 并提交一次反馈；成功查询不自动提交反馈。

「未登录」错误的处置边界：沙箱/托管环境凭证由平台注入，禁止交互式 `opscli auth login`（Device Flow 在无人环境无法完成）。等待约 1 分钟原样重试一次；仍未登录即停止取数、向用户说明凭证异常并提交一次反馈。

规划器异常退出（exit 2）时输出为 stdout 上的错误 JSON：`{"error","retryable","next_action_zh"}`。`retryable=true` 直接原样重跑一次；否则严格按 `next_action_zh` 执行。`retryable=false` 且 `next_action_zh` 无可执行动作，或重跑后仍报同一错误时，转 `SKILL.md`「规划器不可用时的降级路径」；无论哪条路径都禁止盲目重试或翻脚本源码。

## 5. 数据集意图目录（`opscli query catalog` / `opscli query intent`）

这两个命令是 `SKILL.md`「规划器不可用时的降级路径」L2a 层的正式入口：目录为空或选表失败时，优先用远端实时意图目录路由选表，不依赖本地快照；仅当 `query intent` 不可用、报错或返回 `fallback_required=true` 时才降到 L2b 的 `local_fallback.py`。规划器（主线一体化入口）仍可用时不调用这两个命令。

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
- `fallback_required` / `fallback_reason`：`true` 表示 catalog 为空或无匹配意图，此时转 L2b 走 `local_fallback.py`。
- `selected`：`matched=true` 且 `ask_user_question_required=false` 时的唯一候选，可直接采用。
- `match_record_id`：本次匹配的服务端归因记录 ID（上报失败时为 `null`）；命中候选并执行查询时须透传，见上方「3. 正式查询」的归因参数说明。

### 典型工作流：intent → 构造查询 → run 带归因参数

```bash
opscli query intent -q "上周亚马逊美国站销售额" --pretty
# matched=true 且 ask_user_question_required=false 时，取 selected.table_id / selected.dataset_alias 构造查询
opscli query build --table-id <selected.table_id> --dimension ... --metric ... --output payload.json
opscli query run --payload payload.json \
  --intent-code <selected.intent_code> \
  --selection-source intent_route \
  --match-record-id <match_record_id>
```
