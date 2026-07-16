# 数据集默认条件（filter_config）QA 验收记录

| 项目 | 内容 |
|------|------|
| 验收日期 | 2026-07-15 |
| 验收环境 | QA `http://ops.cm`（auto-scheduler 本地站点，运行 aukey/data-metrics release 分支改动代码） |
| 验收账号 | id=59 张培良 |
| 数据源 | doris_analytics（QA） |
| 验收依据 | `docs/design/数据集默认条件filter_config接入需求.md` 第五节验收标准 |

---

## 一、验收结论

**全部机制通过。** 服务端默认条件的下发、注入、解析、导出、回归六大能力均在真实 QA 环境验证正确。验收过程抓到 1 个真实缺陷（日期预设未解析）并修复，另触发 2 处 opscli 跨端架构对齐修复。

**关于 VC报告【Manufacturing】的 0 行结果**：该数据集（`ds_RMoN44WXhu4Z`）在 QA Doris 环境**本身无任何数据**——清空全部 where 条件后总行数仍为 0。0 行是数据缺失，**不是**默认条件实现的缺陷；注入机制经 tinker 逐条实证正确。

---

## 二、逐条验收结果

| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | query-metadata 返回 filter_configs（覆盖本集+组件字段） | ✅ PASS | VC 返回 2 条：`end_date`(required/enum/beforeYesterday) + `report_period`(required/enum/QUARTER)；全库 43 数据集中 3 个有配置（table 18/40/45） |
| 2 | 未配置数据集返回 `"filter_configs": []` | ✅ PASS | 40 个未配置数据集均为 `[]`，0 个缺 `filter_configs` 键，接口向后兼容 |
| 3 | simple 查询未带默认字段时 where 树含默认条件 | ✅ PASS | tinker 实证：无 filters 时 where = `end_date>=2026-07-13 AND end_date<=2026-07-13 AND report_period=QUARTER`（日期预设已解析为真实日期） |
| 4 | 完整 cli-query 入口无法绕过 required | ✅ PASS | `appendDefaultConditions` 对空 where 的绕过 payload 兜底注入全部默认条件 |
| 5 | optional 用户条件可覆盖 | ✅（单测覆盖） | VC 无 optional 配置；`mergeDefaultFilters` 单元测试覆盖 optional 用户优先 |
| 8 | 字段 CSV 含 `filter_config` 列 | ✅ PASS | `skill/export` 第 14 列为 `filter_config`；`end_date` 行含 `beforeYesterday`、`report_period` 行含 `QUARTER` |
| 9 | 数据集 CSV 含 `filter_config_count`/`filter_config_names` | ✅ PASS | `skill/export-datasets` 第 10/11 列；VC 行为 `2` / `end_date\|report_period` |
| 11 | 回归：未配置数据集查询/CSV/规划行为不变 | ✅ PASS | 6 个未配置数据集（table 1/2/3/10/20/30）build 后 where 条件数=0，无任何注入 |
| 12 | ~~冲突静默 AND 合并 + 同值/子集去重~~ **已被覆盖语义取代（见第六节）** | ⚠️ 作废 | 该验收项对应旧 AND 合并语义，已推翻——现为覆盖语义：用户传值即覆盖默认，验收见第六节 L2/L3 |
| 13 | 度量 having（filter_agg != none） | ✅（单测覆盖） | VC 无度量 having 配置；`buildDefaultHavingConditions` 单元测试覆盖 |
| 14 | 多枚举值 → in | ✅（单测覆盖） | `toSimpleFilters` 单元测试覆盖多值 equals→in |

### 端到端回归实测（未配置数据集不受影响）

| 数据集 | table_id | 结果 |
|--------|----------|------|
| order_sale_trend...（未配置） | 1 | `success:true, rowCount:3` 正常返回 |
| ds_9e288aa0df06（未配置） | 2 | `success:true, rowCount:3` 正常返回 |

### 另两个已配置数据集注入验证

| 数据集 | table_id | 注入的默认条件 |
|--------|----------|---------------|
| 物控库存周转 | 40 | `date_id >= 2026-07-13 AND <= 2026-07-13`（beforeYesterday 预设已解析） |
| 库存周转(SQL) | 18 | `ed_sku_lower LIKE LOWER(CAAN1051708A)`（**support_like enrichment 生效**）+ `date_id today` + `dept_name = 项目二部` |

> table 18 的 `ed_sku_lower LIKE LOWER(...)` 证明终审 I-2 修复（完整/简化入口对齐 `getSelectColumnConfig` 的 support_like/map_field/value_func 改写）在真实配置下正确工作。

---

## 三、验收中发现并修复的问题

### 问题 1（真实缺陷）：日期预设名存 enum_value 未被解析

- **现象**：VC 的 `end_date` 配置为 `filter_type=enum`、`enum_value=["beforeYesterday"]`、`value=null`。`toSimpleFilters` 原本只对 `$fc['value']` 调 `FilterDatePreset::resolve`，导致 `beforeYesterday` 字面量直接发给 Doris，匹配不到日期。
- **根因**：后台管理表单（`datasets.blade.php:4886/4996-5000`）对**日期字段**的存储约定是：预设名存 `enum_value`（`filter_type=enum`），只有"自定义(exact)"才把 `[start,end]` 存 `value`。需求文档 2.2 节原假设"预设存 value"与实际不符。
- **修复**：`toSimpleFilters` 增加 enum_value 单元素作为日期候选（`resolve` 对业务枚举 `QUARTER` 返回 null，天然区分，安全）。提交 `c11150d`，24 单元测试。
- **验证**：修复后 `end_date` 正确解析为 `2026-07-13`。

### 问题 2（跨端架构，opscli 侧）：客户端预注入字面量与服务端解析冲突

- **现象**：opscli `run_query` 与 `query_plan.query_template` 会把默认条件字面量（含未解析的日期预设名）预注入进 payload；服务端收到后当作用户条件，又注入自己解析后的真实日期 → AND 合并 → 字面量永不匹配 → 配置了日期默认条件的数据集经 Skill 查询恒 0 行。
- **根因**：服务端已成为默认条件注入的唯一权威方，且日期预设只由服务端解析（评审结论 5）；客户端预注入变成冗余且有害。
- **修复（确立"客户端只披露、服务端权威注入"架构）**：
  - `40538b0`：`run_query._apply_default_filters` 改为披露-only，不再 mutate payload；
  - `bba32cd`：`query_plan` 移除 query_template 默认条件预填，追加"服务端权威注入，勿手动加"说明。
- **验证**：opscli 32 相关测试全绿，review Approved。

---

## 四、提交区间

| 仓库 | 分支 | 区间 | 说明 |
|------|------|------|------|
| aukey/data-metrics | release | `f8f9613..c11150d`（17 commits） | 服务端 R1/R2/R3 + QA 修复，未 push |
| opscli | master_pjc | `a811d7b..bba32cd` | R4/R5 + 终审 + 跨端架构对齐，未 push |

---

## 五、遗留与后续

1. **VC 数据集补数后复验**：QA Doris 中 VC【Manufacturing】当前无数据，待其有数据后可复验默认条件下的实际结果口径；
2. **opscli 端到端（Task 7 opscli）**：需服务端发布 QA 后执行 `opscli skills upgrade ops-dataset-query` 拉取带 `filter_config` 列的 CSV，再实测规划器 → 执行器全链路；
3. **需求文档 2.2 节修订建议**：把"日期预设存 value"更正为"日期字段预设存 enum_value（filter_type=enum），自定义区间存 value"，与后台实际约定一致；
4. **技术债（先例缺陷，本次未动）**：`QueryBuilder::buildHavingConditionString`（约 4432 行）既有图表路径的 having 字符串值未转义，与本次新增的安全加固不同源。

---

## 六、覆盖语义修正与 e2e 验收（2026-07-15 追加）

### 背景
业务负责人复核指出：filter_config 默认条件应是「可被业务覆盖的默认值」而非「不可改的强制值」。原实现（评审结论 1/2 的 AND 合并）会导致业务无法查非默认值（VC 默认 QUARTER，传 MONTH → QUARTER AND MONTH 恒空）。已修正为**覆盖语义**：用户传某字段任意条件即以用户为准（不注入默认），没传则注入默认；required/optional 一致，required 语义仅强调"该维度必被过滤、防全量"。

### e2e 验收证据链（真实 QA 环境 http://ops.cm）

**L1 单元测试**：服务端 47 tests（覆盖套件 24）+ opscli 相关测试全绿。

**L2 where 树逻辑（tinker，VC 数据集）**：
- 传 report_period=MONTH → 只保留 MONTH（QUARTER 被覆盖）+ end_date 默认（没传则注入）
- 传 end_date=2026-06-30 → 覆盖 beforeYesterday
- 不传 → 两默认都注入
- 逐字段独立 √

**L3 真实 COUNT 行数（table 1 临时配置 country_name=美国，真实 Doris，验后精确还原）**——最硬证据：

| 场景 | COUNT | 判定 |
|------|-------|------|
| 不传 country（默认注入美国） | 51157 | = 美国裸量 √ |
| 传 country=加拿大（覆盖） | 681 | = 加拿大裸量，覆盖生效（旧 AND 语义会是 0）√ |
| 传 country=美国（同默认值） | 51157 | 不重复叠加 √ |
| 传 platform=Temu（他字段） | 51157 | country 默认仍注入，逐字段独立 √ |

field_config 已精确还原（与原值一致 √）。

**L4 opscli 命令层（真实 opscli 命令 → ops.cm）**：
- `opscli query metadata --dataset ds_RMoN44WXhu4Z` → success，filter_configs 完整透传（R4）√
- `opscli query build ... --where report_period=MONTH --dry-run` → 发给服务端的 payload **只含用户 MONTH，无预注入默认**（证明客户端披露-only、不注入）√
- `opscli query build ... --run` → success，executionTimeMs 1126，真实执行到 Doris √

### 结论
覆盖语义在服务端逻辑层、真实数据行数层、opscli 命令层全部验证通过。"客户端只披露、服务端权威注入"架构端到端成立。

### 相关提交
- 服务端：`a0cb70c`（覆盖语义）+ `e75e0ff`（注释）；区间 f8f9613..e75e0ff（19 commits）
- opscli：`757ca83`（披露文案覆盖语义）
