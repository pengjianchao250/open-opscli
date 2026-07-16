# 数据集默认条件（filter_config）接入需求说明

| 项目 | 内容 |
|------|------|
| 文档状态 | 已评审定稿（2026-07-15，7 条待确认问题已全部定案，见「六、评审结论」） |
| 编写日期 | 2026-07-15 |
| 涉及系统 | auto-scheduler 后端（aukey/data-metrics 包）、opscli query 模块、ops-dataset-query Skill |
| 数据库 | `polaris_ops_metrics_qa.dm_table_columns.field_config`（QA 环境） |

---

## 一、需求背景

后台管理（数据集管理页）已支持为数据集的字段配置 **字段级默认条件 `filter_config`**，配置持久化在 `dm_table_columns.field_config` JSON 字段中，例如：

```json
{
  "displayed": { "type": "text", "label": "文本" },
  "jump_link": null,
  "sort_type": { "type": "none", "priority": 1 },
  "filter_config": {
    "type": "required",
    "value": null,
    "enabled": true,
    "operator": "equals",
    "enum_value": ["QUARTER"],
    "filter_agg": "none",
    "filter_type": "enum"
  }
}
```

其中 `filter_config` 即该字段在此数据集下的**默认条件**（如上例：该字段默认必须等于 `QUARTER`）。

**当前问题**：`filter_config` 目前仅停留在后台配置层（配置界面 `datasets.blade.php`、解析函数 `FieldGroupApiController::extractFilterConfigs()`），下游链路完全没有消费：

1. `/api/v1/data-metrics/datasets/query-metadata` 返回数据集元数据时**不包含**默认条件信息；
2. 数据集查询（`cli-query` / `cli-query/simple`）执行时**不会应用**默认条件；
3. ops-dataset-query Skill 的规划器不知道默认条件的存在，构造查询时不会带上，导致查询口径与数据集设计口径不一致。

**需求目标**：打通「后台配置 → 元数据下发（query-metadata 接口 + 数据集 CSV 导出接口）→ 查询强制应用 → Skill 规划器感知与披露」完整链路，保证凡是配置了默认条件的数据集，任何入口的查询都必须带上这些默认条件。

> 术语说明：本需求中的「导出」指**数据集元数据 CSV 文件的导出**（`DatasetSkillApiController` 的 `export` / `exportDatasets` 等接口，见 R3），不是指查询结果的导出。

---

## 二、filter_config 配置结构与枚举说明

### 2.1 存储位置

- 表：`dm_table_columns`（数据集维度字段表）
- 字段：`field_config`（JSON，可空），`filter_config` 为其中一个 key
- 配置入口：后台管理 → 数据集管理（`resources/views/admin/data-metrics/datasets.blade.php`，保存逻辑 `saveFieldFilterConfig()`）

### 2.2 filter_config JSON 结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | bool | 是否启用该字段的默认条件；`false` 时全链路忽略 |
| `type` | string | `required`（强制）/ `optional`（可选），见 2.3 |
| `operator` | string | 比较操作符，按字段类型可选值不同，见 2.3 |
| `filter_type` | string | `enum`（枚举）/ `text`（文本） |
| `enum_value` | string[] | `filter_type=enum` 时的默认值列表 |
| `value` | null / string[] | 文本值或日期值；日期字段选「自定义(exact)」时为 `[startDate, endDate]`。**注意（QA 实测修正）**：日期字段选预设时，预设标识（如 `thisQuarter`）存在 `enum_value` 而非 `value`（`filter_type=enum`、`value=null`），这是后台表单的实际存储约定 |
| `filter_agg` | string | 过滤聚合方式，`none` 表示普通条件；非 `none` 为聚合后过滤（having 语义） |

### 2.3 枚举值说明（来源：datasets.blade.php 后台配置表单）

**type（条件性质）**：

| 值 | 中文 | 语义 |
|----|------|------|
| `required` | 强制 | 查询必须应用，用户条件不可移除该默认条件 |
| `optional` | 可选 | 用户未对该字段提供条件时自动应用；用户显式提供时以用户条件为准 |

**operator（按字段类型分组）**：

| 字段类型 | 可选操作符 |
|----------|-----------|
| 日期字段 | `equals`（等于）、`gt`（大于）、`gte`（大于等于）、`lt`（小于）、`lte`（小于等于）、`isEmpty`（为空）、`isNotEmpty`（不为空） |
| 维度字段 | `equals`（等于）、`notEquals`（不等于）、`isEmpty`（为空）、`isNotEmpty`（不为空） |
| 度量字段 | `equals`、`notEquals`、`gt`、`gte`、`lt`、`lte`、`isEmpty`、`isNotEmpty` |

**filter_type**：`enum`（从预定义枚举值中选择）、`text`（自由输入文本）。

**filter_agg**：`none`（无聚合）、`sum`（求和）、`avg`（平均）、`max`（最大值）、`min`（最小值）、`count`（计数）、`countDistinct`（去重计数）。

**日期预设**（日期字段 value 可取预设标识）：`today`、`yesterday`、`beforeYesterday`、`thisWeek`、`lastWeek`、`thisMonth`、`lastMonth`、`thisQuarter`、`lastQuarter`、`thisYear`、`lastYear`、`monthToDate`、`yearToDate`、`past7Days`、`past30Days`、`past90Days`、`past12Months`、`exact`（自定义区间）。

---

## 三、需求范围总览

本需求涉及三个改动面，数据流如下：

```
后台配置 filter_config（已有）
        │
        ▼
【R1】query-metadata 返回数据集时新增 filter_configs 字段
【R3】DatasetSkillApiController 导出接口（export / exportDatasets 等 CSV）同步携带 filter_config
        │
        ▼
【R2】服务端查询（cli-query / cli-query/simple）执行时强制应用默认条件
        │
        ▼
【R4】opscli query 模块透传 filter_configs（远端 + 本地回退缓存）
        │
        ▼
【R5】ops-dataset-query 规划器：规划结果携带默认条件 + 执行前校验注入 + 向用户披露
```

**本期范围**（评审结论 3、7）：

- **维度字段**（含日期维度）与**度量字段**的 `filter_config` 均纳入本期；度量字段 `filter_agg != none` 时按聚合后过滤（having 语义）应用；
- 默认条件的强制应用仅针对**查询入口**（cli-query / cli-query/simple）；查询结果类导出（图表导出等）不属于本需求范围，暂不处理。

---

## 四、详细需求

### 4.1 【R1·服务端】query-metadata 返回数据集时新增 filter_configs 字段

**接口**：`GET /api/v1/data-metrics/datasets/query-metadata`
**改动位置**：`DatasetSkillService::buildQueryMetadataForUser()`（vendor/aukey/data-metrics/src/Services/DatasetSkillService.php:108-170）

**规则**：

1. `datasets` 数组中每个数据集对象新增 `filter_configs` 数组字段；
2. 汇总范围 = 该数据集**关联的所有字段**（维度字段含日期维度，以及度量字段，评审结论 3）中配置了 `filter_config` 且 `enabled=true` 的字段，包括：
   - 数据集自身的字段；
   - 通过 `select_columns` 关联的组件数据集字段（带 `component_dataset_alias` 标识来源）；
3. 条目携带 `field_type`（`dimension` / `metric`）标识，便于客户端区分 where / having 应用语义；
4. 未配置任何默认条件的数据集返回空数组 `"filter_configs": []`，保证字段结构稳定；
5. `enabled=false` 的配置不下发；
6. **组件引用排除**（实现阶段确认的语义细化）：被任一数据集通过 `select_columns` 引用为组件的字段，只出现在**引用方**数据集的 `filter_configs` 中，不再重复出现在其所属组件数据集（`query_component` 类别，仅作权限枚举源）自身的 `filter_configs`——避免同一条件在下游被重复应用的歧义。

**返回结构示例**：

```json
{
  "table_id": 1,
  "dataset_alias": "ds_d35ac6f3910c",
  "dataset_name": "order_sale_trend_adv_traffic_inv_set",
  "dataset_category": "normal",
  "inner_where_enabled": false,
  "description": "即时综合数据集",
  "remarks": "",
  "filter_configs": [
    {
      "column_name": "date_type",
      "verbose_name": "日期类型",
      "field_type": "dimension",
      "component_dataset_alias": "ds_d35ac6f3910c",
      "filter_config": {
        "type": "required",
        "value": null,
        "enabled": true,
        "operator": "equals",
        "enum_value": ["QUARTER"],
        "filter_agg": "none",
        "filter_type": "enum"
      }
    }
  ],
  "select_columns": [ ... ]
}
```

> 每个条目保留 `column_name` / `verbose_name` / `component_dataset_alias`，与 `select_columns` 条目结构对齐，便于客户端定位字段归属；`filter_config` 原样透传配置 JSON。

### 4.2 【R2·服务端】查询强制应用默认条件

**入口覆盖**：

| 入口 | 位置 |
|------|------|
| 完整查询 | `POST /api/v1/data-metrics/cli-query`（`CliQueryApiController::query()`） |
| 简化查询 | `POST /api/v1/data-metrics/cli-query/simple`（`CliQueryApiController::simpleQuery()`） |

> 查询结果类导出（图表导出等）不在本需求范围内（评审结论 7）；数据集元数据 CSV 导出接口的改动见 R3。

**建议注入点**：

- `SimpleQueryBuilder::buildFilters()`（Services/SimpleQueryBuilder.php:261-316）：构建 where 条件树时合并默认条件；
- `CliQueryService::executeForUser()` / `executeSimpleForUser()`（Services/CliQueryService.php:31-92）：权限校验后、转发查询引擎前做兜底校验，保证完整查询入口（非 simple）也无法绕过。

**合并规则**：

| 配置 | 用户未提供该字段条件 | 用户提供了该字段条件（任意值/操作符） |
|------|---------------------|---------------------|
| `type=required` | 服务端自动注入默认值（保证该维度必被过滤，防全量） | **以用户条件为准，覆盖默认值，不注入默认** |
| `type=optional` | 服务端自动注入默认值（缺省建议） | **以用户条件为准，覆盖默认值，不注入默认** |
| `enabled=false` | 不注入 | 不注入 |

> **覆盖语义（业务复核后修正，取代原评审结论 1/2 的 AND 合并/去重）**：filter_config 默认条件是「**默认值，可被业务覆盖**」，不是「不可改的强制值」。用户对某字段提供任意条件（任何操作符/值）时，完全以用户条件为准、不注入该字段默认——保证业务能按需要查询非默认值（如默认 `report_period=QUARTER`，业务传 `MONTH` 即查月度，而非 `QUARTER AND MONTH` 恒空）。
>
> **required 与 optional 的区别**：查询逻辑一致（没传注入默认、传了覆盖）；`required` 语义强调「该字段必须被过滤、防全量」，`optional` 为「缺省建议」，区别仅体现在披露/后台标注，不影响查询构造。
>
> **逐字段独立**：覆盖某字段不影响其他字段——用户覆盖了 `report_period` 但没传 `end_date`，则 `end_date` 默认仍注入。
>
> **强制过滤 ≠ 权限强制**：若需「用户不可覆盖」的强制约束（如只能看本部门数据），那属于**权限过滤**（`query.from.permission`，由数据集权限自动生成），不走 filter_config。

**操作符映射**（filter_config → 服务端 where 条件树）：

| filter_config.operator | where operator | 备注 |
|------------------------|---------------|------|
| `equals`（单值） | `eq` | |
| `equals`（enum_value 多值） | `in` | 服务端支持 `in`（评审结论 4） |
| `notEquals` | `neq` | |
| `gt` / `gte` / `lt` / `lte` | 同名 | |
| `isEmpty` / `isNotEmpty` | 需确认现有 where 树支持情况 | 实现阶段确认 |

**度量字段聚合后过滤（评审结论 3，纳入本期）**：`filter_agg != none` 的度量字段条件按 having 语义应用——先按 `filter_agg`（sum/avg/max/min/count/countDistinct）对度量聚合，再用 `operator` 比较；注入点需覆盖聚合查询构建，实现阶段确认 `SimpleQueryBuilder` / 查询引擎的 having 能力。

**日期预设解析（评审结论 5）**：日期字段 `value` 为预设标识（如 `thisQuarter`）时，由**服务端**在查询执行时刻解析为具体日期区间（基于 Asia/Shanghai 时区），保证同一配置随时间自然滚动，避免缓存过期导致口径漂移。

### 4.3 【R3·服务端】DatasetSkillApiController 导出接口同步携带 filter_config

ops-dataset-query 规划器在 CLI 模式下**离线规划**，读取的本地缓存 CSV（`data/datasets.csv` / `data/dataset_fields.csv` / `data/dataset_select_columns.csv`）由 `opscli skills upgrade` 从 `DatasetSkillApiController` 的导出接口拉取。因此**不只是 queryMetadata，以下导出接口必须同步支持 filter_config 下发**，否则规划器离线规划时拿不到默认条件，R5 无法落地：

| 接口 | Controller 方法 | Service 方法 | 导出产物 |
|------|----------------|--------------|---------|
| `GET /api/v1/data-metrics/datasets/skill/export` | `export()`（DatasetSkillApiController.php:45-57） | `createFieldExportResponseForUser()`（DatasetSkillService.php:248-290） | `dataset_fields_{version}.csv`（字段 CSV） |
| `GET /api/v1/data-metrics/datasets/skill/export-datasets` | `exportDatasets()`（59-71） | `createDatasetExportResponseForUser()`（292-330） | `datasets_{version}.csv`（数据集 CSV） |
| `GET /api/v1/data-metrics/datasets/skill/export-select-columns` | `exportSelectColumns()`（117-129） | `createSelectColumnExportResponseForUser()`（332-377） | `dataset_select_columns_{version}.csv`（查询组件 CSV） |
| `GET /api/v1/data-metrics/datasets/skill/manifest` | `manifest()`（21-43） | `buildExportPayloadForUser()`（77-111） | 版本清单与计数摘要 |

**改动规则**：

1. **字段 CSV（export，filter_config 的主要载体）**：
   现有列 `table_id, dataset_alias, dataset_name, field_name, verbose_name, global_alias, field_type, summary_expression, detail_expression, description, remarks, snapshot_metric, has_formula_config` **行尾新增 `filter_config` 列**：
   - 值为该字段 `field_config.filter_config` 的 JSON 字符串（原样透传配置结构）；
   - 未配置或 `enabled=false` 时为空字符串；
   - 字段级逐行下发，与存储模型（`dm_table_columns.field_config`）一一对应；字段 CSV 覆盖当前用户授权范围内所有数据集的字段（含组件数据集字段），因此组件关联字段的默认条件也随之下发。

2. **数据集 CSV（exportDatasets，摘要索引）**：
   现有列 `table_id, dataset_alias, dataset_name, dataset_category, inner_where_enabled, description, remarks, select_column_count, select_column_names` **行尾新增摘要列**：
   - `filter_config_count`：该数据集关联维度字段（自身 + 组件关联）中启用默认条件的字段数量；
   - `filter_config_names`：启用默认条件的字段名列表（逗号分隔）；
   - 复用 `select_column_count` / `select_column_names` 的既有摘要模式，供规划器在**选表阶段**不展开字段明细即可感知数据集是否带默认条件。

3. **查询组件 CSV（exportSelectColumns）**：结构不变。组件关联字段自身的 filter_config 已通过字段 CSV 按字段行下发，此处无需重复。

4. **manifest**：本期**不**新增 `filter_config_count` 计数（评审结论 6：字段 CSV 为必选载体、数据集 CSV 摘要列纳入，manifest 计数未采纳）。

5. **兼容性约束**：所有 CSV 新增列必须追加在**行尾**，且表头名称固定，保证旧版 opscli / 旧 Skill 按列名或按位置解析时向后兼容；`publish` 版本发布机制照常覆盖上述数据，无需单独处理。

### 4.4 【R4·opscli】query 模块透传 filter_configs

**改动位置**：`opscli/query/` 模块。

1. **远端路径**：`QueryClient.fetch_query_metadata()` → `QueryMetadataResult`（opscli/query/domain/models.py:8-28）新字段随响应体自动透传，需确认 `to_dict()` 不丢字段；
2. **本地回退路径**：`query_metadata.json` 为远端同源缓存，服务端上线后自然携带 `filter_configs`，`matched.get("filter_configs")` 统一提取，旧缓存缺字段时回退空列表（不做字段 CSV 兜底重建）；
3. `opscli query build / build_simple` 参数结构**不变**：默认条件由服务端强制应用（R2），opscli 侧不重复注入，仅负责把元数据透传给 Skill 供规划披露使用。

### 4.5 【R5·Skill】ops-dataset-query 规划器与执行器优化

**目标**：规划器感知默认条件 → 构造查询时体现 → 执行前校验 → 回答中向用户披露。

1. **元数据读取**（`scripts/dataset_guidance.py`、`scripts/scoped_dataset_reader.py`）：
   - `scoped_dataset_reader.py` 解析字段 CSV 新增的 `filter_config` 列（JSON 字符串反序列化），并读取数据集 CSV 的 `filter_config_count` / `filter_config_names` 摘要列；
   - `dataset_guidance.py` 将所选数据集的默认条件纳入字段指导输出；
   - `scripts/updater*.py` 拉取 CSV 时原样落盘，无需感知新列（透传）。

2. **规划结果投影**（`scripts/query_plan.py` build_model_contract，约 1031-1191 行）：
   - `execution_ref` 新增 `default_filters` 数组（含 `field_name`、`operator`、`values`、`type`、`filter_type`），供查询构造直接使用；
   - `model_view` 新增中文披露字段（如 `default_filters_zh`：`[{"字段": "日期类型", "默认条件": "等于 QUARTER（强制）"}]`），要求回答中**必须向用户披露**已生效的默认条件；
   - `answer_contract.required_disclosures_zh` 追加默认条件披露项。

3. **执行器披露**（`scripts/run_query.py`，披露-only，不注入 payload——服务端权威注入）：
   - 用户未提供该字段条件 → 披露"服务端将自动应用数据集默认条件 X"；
   - 用户已提供该字段条件 → 披露"你的条件将覆盖数据集默认值 X"（覆盖语义，不再有"AND 同时生效"文案）；
   - 度量 having 默认条件 → 披露"服务端将按聚合后过滤应用 X"。

4. **规则文档衔接**（`references/rules.md`）：
   现有硬约束「禁止发明默认筛选」需补充例外说明——**来自服务端元数据 filter_configs 的默认条件不属于"发明"**，属于数据集口径的一部分，必须应用且必须披露；除此之外仍然禁止凭推断添加任何筛选。

5. **文档更新**：
   - `SKILL.md`：「构造与执行」章节说明默认条件的自动应用与披露要求；
   - `references/simple-query-guide.md`：补充「默认条件（filter_configs）的自动应用与覆盖机制」章节；
   - `QUERY_SPEC.md`：MCP 部署契约同步 filter_configs 处理规范。

6. **版本**：`data/VERSION.json` 升级至 `1.4.0`（新功能，minor 升级）。

---

## 五、验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | query-metadata 按 `dataset_alias`/`table_id` 请求时，数据集对象包含 `filter_configs`，覆盖本数据集及组件关联字段中所有 `enabled=true` 的配置 | 对已配置 filter_config 的数据集调用接口比对返回 |
| 2 | 未配置默认条件的数据集返回 `"filter_configs": []`，接口向后兼容 | 对未配置数据集调用接口验证 |
| 3 | simple 查询未携带默认条件字段时，最终执行的 where 条件树包含默认条件 | 检查查询日志 / dry-run payload |
| 4 | 完整查询入口（cli-query）同样无法绕过 required 默认条件 | 构造绕过用例验证 |
| 5 | `type=optional` 时用户显式条件可覆盖默认条件 | 构造覆盖用例验证 |
| 6 | 规划器输出 `execution_ref.default_filters`，且 `model_view` 含中文披露 | 运行 `query_plan.py` 检查输出 |
| 7 | `run_query.py` precheck 对缺失的 required 条件自动注入并披露 | 构造缺失用例验证 |
| 8 | `skill/export` 导出的字段 CSV 含 `filter_config` 列，已配置字段的列值与后台配置一致（含组件数据集字段）；未配置字段该列为空 | 下载 CSV 与后台配置比对 |
| 9 | `skill/export-datasets` 导出的数据集 CSV 含 `filter_config_count` / `filter_config_names` 摘要列，计数与字段 CSV 明细一致 | 下载 CSV 交叉比对 |
| 10 | `opscli skills upgrade` 后本地缓存包含 filter_config 数据，离线规划可感知 | 升级后运行规划器验证 |
| 11 | 回归：未配置 filter_config 的数据集，查询/CSV 导出/规划行为与现状完全一致；旧版 opscli 解析新版 CSV 不报错 | 全量回归测试 + 旧版本兼容验证 |
| 12 | 覆盖语义：用户传某字段任意值/操作符 → 只保留用户条件（默认不注入）；用户没传 → 注入默认；逐字段独立 | 构造 report_period=MONTH / end_date=特定日 / != 等用例，检查 where 树只含用户条件 |
| 13 | 度量字段 `filter_agg != none` 的默认条件按聚合后过滤（having 语义）生效 | 构造聚合过滤用例，比对聚合前后数据 |
| 14 | `enum_value` 多值默认条件翻译为 `in` 条件生效 | 构造多枚举值用例，检查 where 条件树与结果 |

---

## 六、评审结论（2026-07-15 已确认）

| # | 问题 | 评审结论 |
|---|------|---------|
| 1 | `required` 默认条件与用户显式条件**冲突**时（如默认 `report_period=QUARTER`，用户传 `MONTH`）如何处理？ | ~~静默 AND 合并~~ → **已被业务复核推翻，改为覆盖语义**：用户传了就以用户为准、覆盖默认（否则业务永远查不了非默认值）。详见「四、4.2 覆盖语义」 |
| 2 | `required` 且用户条件与默认条件**不冲突**（同字段同值或子集）时，是否去重合并？ | ~~合并去重~~ → **已并入覆盖语义**：用户传了该字段任意条件即以用户为准，不存在两条共存，无需去重 |
| 3 | 度量字段的 `filter_config`（`filter_agg != none`，having 语义）是否纳入本期？ | **纳入本期**：维度字段与度量字段均处理，度量字段按 having 语义应用 |
| 4 | `enum_value` 多值 + `operator=equals` 的 where 表达 | **支持 `in`**，多值直接翻译为 `in` 条件 |
| 5 | 日期预设（`thisQuarter` 等）的解析归属 | **服务端执行时解析**，避免缓存过期口径漂移 |
| 6 | R3 中数据集 CSV 摘要列与 manifest 计数是否需要？ | **字段 CSV 为必选载体；数据集 CSV 摘要列纳入**（规划器选表阶段低成本感知）；manifest 计数未采纳，本期不做 |
| 7 | 需求中「导出」的含义澄清 | 「导出」指**数据集元数据 CSV 文件导出**（R3 覆盖的 `export` / `exportDatasets` 等接口）；查询结果类导出（图表导出等）**不属于本需求，暂不处理** |

---

## 七、影响范围与兼容性

1. **接口兼容**：`filter_configs` 为新增字段，旧版客户端（旧 opscli / 旧 Skill）忽略该字段不受影响；但注意——**服务端 R2 强制应用后，旧客户端的查询结果口径也会变化**（这是需求预期行为），需在发布说明中向存量用户明示；
2. **查询结果口径变化**：已配置 required 默认条件的数据集，所有历史调用方的查询结果都会收敛到默认口径，上线前需与数据集管理员确认配置正确性；
3. **Skill 升级依赖**：R5 依赖 R1/R3 先行发布；Skill 侧需版本升级（1.3.5 → 1.4.0）并通过 `opscli skills upgrade ops-dataset-query` 分发；
4. **性能**：query-metadata 需额外解析各字段 field_config JSON，量级为字段数 × 数据集数，预计影响可忽略，实现时避免 N+1 查询。

---

## 八、附录：关键代码位置

### 服务端（auto-scheduler / aukey/data-metrics）

| 功能点 | 位置 |
|--------|------|
| query-metadata 接口 | `src/Http/Controllers/DatasetSkillApiController.php:73-99` |
| 字段 CSV 导出接口 | `src/Http/Controllers/DatasetSkillApiController.php:45-57`（export）→ `src/Services/DatasetSkillService.php:248-290`（createFieldExportResponseForUser） |
| 数据集 CSV 导出接口 | `src/Http/Controllers/DatasetSkillApiController.php:59-71`（exportDatasets）→ `src/Services/DatasetSkillService.php:292-330`（createDatasetExportResponseForUser） |
| 查询组件 CSV 导出接口 | `src/Http/Controllers/DatasetSkillApiController.php:117-129`（exportSelectColumns）→ `src/Services/DatasetSkillService.php:332-377`（createSelectColumnExportResponseForUser） |
| manifest 接口 | `src/Http/Controllers/DatasetSkillApiController.php:21-43`（manifest）→ `src/Services/DatasetSkillService.php:77-111`（buildExportPayloadForUser） |
| 元数据组装 | `src/Services/DatasetSkillService.php:108-170`（buildQueryMetadataForUser） |
| 维度字段加载 | `src/Services/DatasetSkillService.php:430-462`（loadColumns） |
| filter_config 既有解析参考 | `src/Http/Controllers/FieldGroupApiController.php:1406-1429`（extractFilterConfigs） |
| where 条件构建 | `src/Services/SimpleQueryBuilder.php:261-316`（buildFilters）、操作符映射 33-42 |
| 查询执行编排 | `src/Services/CliQueryService.php:31-92` |
| 路由定义 | `src/Http/routes.php:81-97` |
| 后台配置表单枚举 | `auto-scheduler_debug/resources/views/admin/data-metrics/datasets.blade.php:4327-4402`（枚举定义）、4983-5067（保存逻辑） |

### opscli / Skill

| 功能点 | 位置 |
|--------|------|
| metadata HTTP 拉取 | `opscli/query/transport/client.py:109-147`（fetch_query_metadata） |
| metadata 编排与本地回退 | `opscli/query/services/manager.py:76-155` |
| 元数据模型 | `opscli/query/domain/models.py:8-28`（QueryMetadataResult） |
| 规划器主入口 | `opscli/skills/templates/ops-dataset-query/scripts/query_plan.py`（build_query_plan 565-655、build_model_contract 1031-1191） |
| 字段指导 | `opscli/skills/templates/ops-dataset-query/scripts/dataset_guidance.py`（_permission_scope 279-387） |
| 执行器 precheck | `opscli/skills/templates/ops-dataset-query/scripts/run_query.py` |
| 硬约束规则 | `opscli/skills/templates/ops-dataset-query/references/rules.md`（禁止发明默认筛选） |
| Skill 版本 | `opscli/skills/templates/ops-dataset-query/data/VERSION.json`（当前 1.3.5） |
