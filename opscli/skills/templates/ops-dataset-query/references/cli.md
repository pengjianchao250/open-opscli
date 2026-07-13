---
name: ops-dataset-query-cli
description: 当前账号元数据的 CLI-only 规划、权限枚举与查询路由
---

# CLI-only 运行契约

## 唯一路由

```text
query_plan.py -> 当前账号组件枚举 -> opscli query simple
```

若当前请求尚未运行组合入口，直接在 Skill 目录执行：

```bash
python3 scripts/query_plan.py "$USER_REQUEST"
```

不要重复读取版本、列目录、检查源码或扫描元数据。组合合同只消费当前账号下发的 `data/`；`data_state` 不为 `ready`，或登录/账号/元数据所有权发生变化时，先执行 `opscli skills upgrade ops-dataset-query`，再重新规划。

组合入口默认输出模型合同（`model_view` / `answer_contract` / `execution_ref`），Agent 只消费这三部分。`--output-mode internal` 输出内部完整合同，仅供维护者排错，不进入正常流程。

## 1. 选表与字段

- `status=planned`：数据集已确定，用 `model_view.dataset_name_zh` 与中文粒度向用户确认业务表。
- `status=clarify_required`：只按 `model_view.clarification_messages_zh` 提问，用户确认前停止。
- 字段与聚合口径只采用 `model_view` 的中文字段和 `execution_ref` 中对应的授权执行字段；`execution_ref` 字段带 `aggregation_policy`（公式或快照口径）时按其执行，不再传普通 `aggregation`。

## 2. 明确筛选与权限枚举

未指定筛选值时使用 `current_authenticated_account` 默认可见范围，不添加平台、国家、部门、人员或产品默认值。

平台请求读取 `model_view` 与 `execution_ref`：

1. `model_view.platform_semantic_members` 表示请求语义；亚马逊为 SC+VC，明确 SC 或 VC 时不得扩展。
2. `platform_filter_state=requires_permission_enum` 表示尚未取得授权值，不能构造业务查询的平台 filter。
3. 使用 `execution_ref.platform_component_table_id` 和字段 `platform_name` 构造最小枚举查询；内部 alias 不向用户展示。
4. 将组件查询实际返回的平台值逐个传回组合入口；本地规则只做语义匹配，最终值始终原样取自本次服务端返回。

枚举查询同样走正式入口：

```bash
opscli query simple --table-id "$COMPONENT_TABLE_ID" --json "$ENUM_QUERY_JSON" --run --pretty
```

将返回值逐项传回，参数可重复：

```bash
python3 scripts/query_plan.py "$USER_REQUEST" \
  --authorized-platform-value "$CURRENT_ACCOUNT_PLATFORM_VALUE"
```

- `platform_filter_state=resolved`：正式 filter 只使用 `execution_ref.resolved_platform_values`。
- `status=blocked` 时按 `model_view.next_action` 区分：`block_platform_scope_not_authorized` 当前账号没有请求范围，停止查询；`block_platform_enum_ambiguous` 服务端值无法唯一映射，停止并记录元数据问题；`block_platform_scope_unsupported` 请求的平台不在本 Skill 支持的语义范围，向用户如实说明。
- 权限收窄只影响请求范围本身，不得据此扩大范围。

其他明确筛选必须先经对应组件枚举校验；合同未返回足够组件来源时，不把文本值静默塞入业务查询。维护者排错可用 `python3 scripts/query_plan.py "$USER_REQUEST" --output-mode internal` 查看完整组件证据（仅排错用，不进入正常流程）。

## 3. 正式查询

按 `references/simple-query-guide.md` 构造参数，执行前展示并确认数据集、字段、时间、筛选、排序、行数和对比口径：

```bash
opscli query simple --table-id "$TABLE_ID" --json "$QUERY_JSON" --run --pretty
```

- 公式字段不传额外 `aggregation`；快照类指标默认取最新快照，不跨期累加。
- 环比、同比或上期对比同时传主周期日期 `filters` 和 `dataComparison`。
- 不发明默认筛选，不将局部或截断结果表述为全量。

## 4. 结果与失败

常规结果按 `SKILL.md` 的最小分析合同输出，不再读取长参考。复杂审计或用户明确要求完整披露时才读取 `references/result-analysis.md`。

0 行、澄清、预期的认证未就绪和用户取消不是工具故障。仅意外 opscli 失败读取 `references/feedback-guide.md` 并提交一次反馈；成功查询不自动提交反馈。
