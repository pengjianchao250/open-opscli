# MCP 查询规范

> 【适用范围】本文件仅作为 MCP 部署契约存档；CLI-only 会话不要读取本文件，一律以 SKILL.md 与规划器为准。

本文件是 `ops-dataset-query` 包内的规范 MCP 查询契约，与 `SKILL.md` 保持一致。

## 1. 授权元数据

- 当前已认证账号的 `query_metadata` 响应是数据集、字段、公式、聚合、`select_columns` 和组件枚举关系的唯一运行时来源。
- **认证来源（两种，等价）**：当前已认证账号既可由平台注入的登录态确立，也可由调用方通过工具参数**显式传入**凭证确立——`query_metadata` / `query_simple` 等工具均接受可选的 `session_id` 与 `jwt` 参数；两者留空时使用平台注入的登录态，显式传入时优先使用显式凭证。无论哪种来源，确立的都是同一个"当前已认证账号"，本次请求内所有 `query_metadata` / `query_simple` 必须归属同一账号，不跨账号混用。
- **显式传参形式**：`session_id` / `jwt` 作为工具参数与业务参数并列传入（`jwt` 为 ops 系统 JWT；`jwt` 留空时用 `session_id` 向后端换取）。**仅当调用方/编排方持有显式凭证时才传**；默认 Agent 流程使用平台注入的登录态，**无需也不应手填**这两个参数：

  ```python
  query_metadata(session_id="<SESSION_ID>", jwt="<OPS_JWT>")
  query_simple(table_id="<TABLE_ID>", dimensions=[...], metrics=[...],
               session_id="<SESSION_ID>", jwt="<OPS_JWT>")
  ```

- **身份核验（可选）**：需要确认究竟以谁的账号取数时，调用 `auth_me`（同样接受可选 `session_id` / `jwt`）核验当前有效身份（返回 `username` / `id` 等）。显式凭证必须发往其签发的同一后端环境，否则后端返回 407（凭证无效 / 用户不存在），按认证失败处理。
- 认证或远程元数据失败时阻断选择。不得使用客户端文件、先前结果、个性化设置或其他账号响应补齐。
- 本次请求固定 MCP-only，不切换到其他执行模式。

## 2. 数据集选择

1. 调用无参 `query_metadata()` 取得当前账号授权数据集卡片。
2. 自然语言只按卡片的中文名称和中文说明选择；向用户展示中文名称、说明和业务粒度。
3. 用户明确给出精确完整英文技术标识时，才在当前授权卡片中精确匹配。
4. 候选不唯一、粒度不清或无授权候选时停止并澄清；不自行选择。
5. `query_component` 仅用于枚举权限值，不是业务结果数据集。
6. 问题内嵌完整中文数据集名时，嵌套命中保留包含关系中最长的授权名称；独立命中多个名称或同名冲突时必须澄清。
7. 明确请求枚举/可用值时，查询组件可进入 selected-dataset guidance，并由 guidance 归一为 `permission_enum_only`；其他请求仍阻断业务查询。

## 3. 已选数据集

对用户确认的数据集调用 `query_metadata(dataset="<alias>")`，然后：

- 维度、指标、字段类型、聚合方式和输出名称只来自该响应。
- 公式字段含 `formula_config`、`summary_expression` 或 `detail_expression` 时，不再传普通 `aggregation`。聚合/分组使用汇总表达式，明细使用明细表达式。
- 不发明默认筛选。用户明确筛选命中 `select_columns` 关系时，只读取该关系返回的 `component_dataset_alias`。
- 组件 alias 缺失时只阻断该筛选。alias 存在时，调用 `query_metadata(dataset=component_alias)` 取得当前账号的组件 `table_id` 和字段，再用 `query_simple` 查询合法枚举。
- 用户值不在枚举结果中时，展示可用值并请用户重选，不执行原查询。

## 4. 正式 `query_simple`

执行前向用户展示并确认：数据集、维度、指标、时间、筛选、排序、行数、对比口径。MCP 参数使用 snake_case：

> 示例不得直接复制；必须将全部占位符替换为本次 guidance/metadata 返回值。

```python
query_simple(
    table_id="$TABLE_ID",
    dimensions=[
        {"field": "$AUTHORIZED_DIMENSION", "alias": "$DIMENSION_RESULT_ALIAS"}
    ],
    metrics=[
        {
            "field": "$AUTHORIZED_METRIC",
            "aggregation": "$AUTHORIZED_AGGREGATION",
            "alias": "$METRIC_RESULT_ALIAS",
        }
    ],
    filters=[
        {
            "field": "$AUTHORIZED_FILTER",
            "operator": "$CONFIRMED_OPERATOR",
            "value": "$CONFIRMED_FILTER_VALUE",
        }
    ],
    order_by=[{"field": "$METRIC_RESULT_ALIAS", "desc": "$CONFIRMED_DESC"}],
    limit="$CONFIRMED_LIMIT",
)
```

环比、同比或上期对比必须同时传主周期日期 `filters` 和 `data_comparison`。不将局部或截断结果表述为全量。

`query_metadata` 返回的数据集对象含 `filter_configs` 数组（字段级默认条件，`required` 类型服务端强制应用）；`query_simple` 结果口径已含默认条件。

## 5. 证据导向分析

MCP-only 场景没有本地 shell，按以下内联证据合同组织结论，输出顺序固定为：范围与口径、主要结论、关键贡献/异常、可执行观察、限制。

- 先说明数据集中文名、时间、维度、指标、筛选、币种、聚合、排序和返回行数；每个数值结论必须附字段名或结果列证据，数值保持返回精度不四舍五入。
- 0 行只能说明没有返回记录，不能判断业务为 0；全零不等于无数据；空值不等于 0。
- 周期比较只使用已返回的本期、`last_*`、`diff_*`、`pct_*` 列，缺列时说明无法比较；不同原币不得混加，也不得与 CNY 列混加。
- Top N 或截断必须披露排序、展示数和总行数；未查询范围不得外推；不把相关性表述为因果。
- 披露权限、样本、公式口径和数据新鲜度限制。

## 6. 反馈边界

- 只有 opscli/MCP 调用抛出异常、返回 `success: false`、超时或出现无法解释的服务错误时，才是意外失败。
- 意外失败同一请求内提交一次结构化反馈；30 分钟内同工具、关键参数、错误码和错误文本去重。
- 反馈提交自身失败只报告，不再递归。
- 0 行不是反馈事件。预期的认证未就绪、需要澄清和用户取消也不是反馈事件。
- 成功查询不自动提交反馈。

## 部署注记

本地文件是当前包契约。若独立部署的服务端 `query_spec_must_read()` 仍返回旧 payload，需在服务端另行更新；修改本文件不会自动更新已部署服务。
