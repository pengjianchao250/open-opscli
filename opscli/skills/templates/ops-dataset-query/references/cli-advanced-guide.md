---
name: ops-dataset-query-cli-advanced
description: CLI 模式 — 完整版查询命令详解（opscli query build / opscli query run / opscli query chart / 降级方案）
---

# CLI 完整版查询指南

本文档涵盖 CLI 模式下所有**完整版/高级查询命令**的详细说明与示例。

> **阅读前提**：确保已阅读 `references/simple-query-guide.md` 和 `references/cli-simple-guide.md`，确认简化接口确实无法满足需求。
>
> **文档引用顺序**：本文档配合 `references/data-query-service-dev-guide.md` 使用（多次失败时参考）。

---

## 命令说明

- **`opscli query build`**：基于简化参数构造**标准完整 query payload**（含 select/where/groupBy 等），可选直接执行。输出的是完整版 payload 结构。
- **`opscli query run`**：透传完整手写 query payload 执行查询。仅当简化接口和 `query build` 均无法满足需求时使用。
- **`opscli query chart`**：通过图表 ID 直接获取查询结构并执行，支持多 query 自动合并。涉及小计/总计、字段映射、Excel 导出等复杂场景。

---

## `opscli query build`

基于简化参数构造标准完整 query payload，可选直接执行。

```
选项：
  --dataset TEXT      dataset_alias（与 --table-id 二选一）
  --table-id INTEGER  table_id
  --dimension TEXT    维度：field_name|global_alias|verbose_name[:alias]，可重复
  --metric TEXT       指标：field_name|global_alias|verbose_name:aggregation[:alias]，可重复
  --where TEXT        筛选：field|operator|value_json，可重复
  --where-json TEXT   where 条件 JSON 字符串（与 --where 互斥）
  --where-file TEXT   where 条件 JSON 文件路径（与 --where 互斥）
  --having TEXT       having 条件：expr|operator|value_json，可重复
  --order-by TEXT     排序：expr[:asc|desc]，可重复
  --limit INTEGER     返回行数，默认 20
  --offset INTEGER    分页偏移，默认 0
  --dry-run           仅生成 SQL，不执行查询
  --output TEXT       将 payload 写入指定文件
  --data-comparison TEXT  数据对比：field,start_date,end_date（例: date_id,2026-03-01,2026-03-22）
  --run               构造后立即执行查询
  --skills-dir TEXT   指定 Skill 目录
  --pretty            格式化 JSON 输出
```

### 参数格式

**dimension**：`field_name|global_alias|verbose_name[:alias]`
- `date_id` → 按 date_id 分组，默认优先使用字段的 `global_alias` 作为输出列名
- `date_id:f_date_id` → 按 date_id 分组，列名改为 `f_date_id`

**metric**：`field_name|global_alias|verbose_name:aggregation[:alias]`
- `order_cost:sum` → 求和
- `order_cost:sum:total_cost` → 求和，列名改为 total_cost
- `order_id:count_distinct:uv` → 去重计数

> `select.alias` 不支持中文；如果不显式传 alias，`opscli query build` 会优先使用字段 metadata 中的 `global_alias`，没有时再回退到 `field_name`。

**公式指标特殊规则**
- 如果字段 metadata 中包含 `formula_config` / `summary_expression` / `detail_expression`，该指标应按公式字段处理。
- 手写 payload 时，聚合 / 分组查询应直接使用完整公式表达式结构，不额外传 `aggregation`：

```json
{
  "expr": "ROUND(SUM(dsp)/SUM(price), 4)",
  "alias": "f_yZZfW7cNu8nYMGCS"
}
```

- 如果使用 `opscli query build`，仍然可以传 `global_alias|verbose_name:aggregation[:alias]`，CLI 会根据 metadata 自动展开为完整表达式 payload。
- 明细查询：使用 `detail_expression`
- 聚合 / 分组查询：使用 `summary_expression`
- 显式传 alias 时，只允许英文、数字和下划线，且不能以数字开头；中文 alias 会被拒绝

**常见易错对照**
- 普通求和指标：`price:sum` 或手写 `{ "expr": "ds_xxx.price", "alias": "f_price", "aggregation": "SUM" }`
- 公式占比指标：手写 `{ "expr": "ROUND(SUM(dsp)/SUM(price), 4)", "alias": "f_yZZfW7cNu8nYMGCS" }`
- 错误写法：`sell_qty_days:sum`、`avg_original_price_cny:sum` 这类公式字段继续套普通聚合

**where**：`field|operator|value_json`（完整操作符列表见 `references/data-query-service-dev-guide.md` 第五章）

```bash
--where "date_id|gte|\"2024-01-01\""
--where "country_id|in|[\"CN\",\"US\"]"
```

**where-json / where-file**：传入结构化 where 对象，支持嵌套逻辑分组：

```bash
--where-json '{"operator":"AND","conditions":[{"field":"country_id","operator":"in","value":["CN","US"]}]}'
--where-file /tmp/where.json
```

**having**：`expr|operator|value_json`

```bash
--having 'total_cost|gt|1000'
```

**order-by**：`expr[:asc|desc]`

```bash
--order-by total_cost:desc
--order-by date_id         # 默认升序
```

### 示例

```bash
# 构造 payload 并写入文件
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --dimension country_id:country \
  --metric order_cost:sum:total_cost \
  --metric order_id:count_distinct:order_count \
  --where "date_id|gte|\"2024-01-01\"" \
  --where "date_id|lte|\"2024-12-31\"" \
  --order-by total_cost:desc \
  --limit 50 \
  --output /tmp/query.json

# 构造后直接执行
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric order_cost:sum \
  --run --pretty

# 使用 where-file 传入复杂条件
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric order_cost:sum \
  --where-file /tmp/where.json \
  --run --pretty

# 带 having 的聚合查询
opscli query build \
  --dataset sales_order_d \
  --dimension country_id:country \
  --metric order_cost:sum:total_cost \
  --having 'total_cost|gt|1000' \
  --order-by total_cost:desc \
  --run --pretty

# 分页查询（第 2 页，每页 20 条）
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric order_cost:sum \
  --limit 20 --offset 20 \
  --run --pretty

# 仅生成 SQL，不执行
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric order_cost:sum:total_cost \
  --dry-run --run --pretty

# 带数据对比（环比上月同期）
opscli query build \
  --table-id 1104 \
  --dimension dept_name \
  --metric price:sum:total_price \
  --metric order_qty:sum:total_qty \
  --where "date_id|gte|\"2026-04-01\"" \
  --where "date_id|lte|\"2026-04-22\"" \
  --data-comparison "date_id,2026-03-01,2026-03-22" \
  --output /tmp/comparison.json
```

---

## `opscli query run`

透传完整 query payload 执行查询。仅当简化接口无法满足需求时使用。

```
选项：
  --payload TEXT   查询 JSON 文件路径（必填）
  --pretty         格式化 JSON 输出
```

```bash
opscli query run --payload /tmp/query.json --pretty
```

> **【强制】手写 payload 的 `query.select` 结构要求**
>
> 服务端校验规则（`CliQueryApiController`）：`query.select.*.expr` 和 `query.select.*.alias` 为**必填字段**。
>
> - `expr`：字段表达式，格式为 `数据集别名.字段名`（如 `ds_d35ac6f3910c.dept_name`），或完整公式
> - `alias`：输出列名，建议使用 `global_alias`（如 `f_520fb9a831ccd52a`）或自定义英文标识
> - `aggregation`：聚合方式（如 `SUM`、`COUNT`），指标字段需提供，维度字段不传
>
> **正确的 select 结构**：
> ```json
> "select": [
>   {"expr": "ds_d35ac6f3910c.dept_name", "alias": "f_520fb9a831ccd52a"},
>   {"expr": "ds_d35ac6f3910c.order_cost", "alias": "f_total_cost", "aggregation": "SUM"}
> ]
> ```
>
> **错误示例（会导致 422 校验失败）**：
> ```json
> // 错误：使用 global_alias 作为 key，缺少 expr
> "select": [
>   {"global_alias": "f_520fb9a831ccd52a"},
>   {"global_alias": "f_total_cost", "aggregation": "SUM"}
> ]
>
> // 错误：缺少 alias
> "select": [
>   {"expr": "ds_d35ac6f3910c.dept_name"}
> ]
> ```
>
> **建议**：优先使用 `opscli query build` 自动构造 payload，避免手写出错。

**输出格式：**

```json
{
  "success": true,
  "command": "query run",
  "data": {
    "success": true,
    "data": [{"date_id": "2024-01-01", "total_cost": "12345.67"}],
    "meta": {"rowCount": 2, "totalCount": 365}
  },
  "error": null
}
```

---

## `opscli query chart`

通过 `chart_uuid` 获取图表的查询结构，可选立即执行所有查询并合并输出。

**推荐心智模型**：
- `datasets`：公共元数据层，沉淀数据集、字段目录、可过滤字段
- `queries`：执行层，沉淀每条 query 的 `query/payload/result`
- 优先使用服务端返回的字段语义信息；本地 `dataset_fields.csv` 仅作兜底

```
选项：
  --uuid TEXT      图表 UUID（必填）
  --run            获取后立即执行所有查询并合并输出
  --dry-run        仅生成 SQL，不执行查询（需配合 --run）
  --pretty         格式化 JSON 输出
```

```bash
# 仅查看图表查询结构
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty

# 获取并执行所有查询（多 query 结果自动合并）
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --pretty

# 仅生成 SQL，不执行
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --dry-run --pretty
```

**说明**：
- 后端返回的 chart bundle 已包含 `datasets[].fields`、`datasets[].filterable_fields`
- 每条 query 会补充字段引用信息，Skill 应优先读取服务端字段语义，避免重复本地推断
- 后端返回的 chart query 已包含 `tableId`，无需本地 metadata 转换
- 一个图表可能包含多个 query（如主查询 + 下钻 + 汇总），`--run` 时依次执行
- 每个 query 独立执行，失败时记录错误但不中断其余 query
- 合并结果中每行数据附加 `_query_index` 字段标识来源 query 序号

**返回结构（仅结构模式）**：见 `references/cli.md` 或实际调用输出。

**返回结构（--run 时）**：见 `references/cli.md` 或实际调用输出。

---

### 【强制】Chart 多查询与小计/总计处理规则

> ⚠️ **核心原则：优先使用服务端返回的小计/总计数据，禁止本地累加计算。**

一个图表可能返回多个 query（通过 `merged.meta.queryCount` 识别），不同 query 的 `groupBy` 维度和 `select` 字段数不同：

| Query 类型 | groupBy 维度 | select 字段数 | 说明 |
|-----------|-------------|-------------|------|
| Query 0（明细） | 全部维度（如部门+渠道+国家） | 最多 | 最细粒度的明细数据 |
| Query 1（小计） | 部分维度（如仅部门） | 较少（缺少非 groupBy 的维度列） | 按更高层级聚合的小计 |
| Query 2+（总计） | 无（空数组） | 最少（只有指标列） | 全局总计 |

**识别方法**：通过 `query.groupBy` 的长度判断：
- `groupBy` 与 Query 0 相同 → 明细行
- `groupBy` 比 Query 0 少 → 小计行（按剩余维度聚合）
- `groupBy` 为空 → 总计行

**实际示例**（3 个查询的图表）：

```
Query 0: groupBy=[dept_name, channel_name, country_name]  → 22 行明细
Query 1: groupBy=[dept_name]                               → 2 行部门小计
Query 2: groupBy=[]                                        → 1 行总计
```

**数据展示规范**：

1. **必须遍历所有 queries**，不能只读 `queries[0]`
2. 小计行/总计行的字段数比明细行少（缺少非 groupBy 的维度列），展示时缺失维度列留空即可
3. **禁止自行累加明细行来计算小计/总计**，服务端的聚合逻辑可能与简单累加存在差异（如精度、过滤条件）
4. 展示顺序建议：按部门分组 → 该部门明细行 → 该部门小计 → 下一个部门 → ... → 总计

**错误示例**：
```python
# 错误：只读 Query 0，本地累加计算小计
detail_rows = queries[0]['result']['data']
for dept in departments:
    subtotal = sum(r['profit'] for r in detail_rows if r['dept'] == dept)
```

**正确示例**：
```python
# 正确：从各 query 的 result 中直接取小计/总计
detail_rows = queries[0]['result']['data']     # 明细
subtotal_rows = queries[1]['result']['data']    # 部门小计
total_rows = queries[2]['result']['data']       # 总计
```

---

### 【强制】Chart 数据展示与 Excel 输出规范

> ⚠️ **核心原则：默认展示全部字段；小计/总计行必须出现在同一张表中，数据取自服务端返回，禁止本地累加。**

#### 一、字段展示规范

1. **默认展示所有字段**：Chart 查询返回的所有维度和指标列必须全部展示，不可省略任何字段
2. **字段别名映射优先级**：
   - 先用 `chart_map.py --map-results` 自动映射
   - 若 `chart_map.py` 映射不完整（部分字段 `mapped_name` 仍为 `global_alias`），则手动补充映射：
     - 从 `payload.query.select[].expr` 提取 `field_name`（如 `ds_xxx.dept_name` → `dept_name`）
     - 用本地 `data/dataset_fields.csv` 按 `field_name` 查找 `verbose_name`
3. **百分比指标格式化**：毛利率、占比等公式指标服务端返回值为小数（如 `-0.2039` 表示 -20.39%），展示时需 ×100 并保留两位小数，无数据时显示 `-`

#### 二、多查询合并展示规范

**必须将明细、小计、总计合并为一张统一的 Markdown 表格**，不可分成多张独立的表：

| 展示区域 | 行来源 | 维度列 | 指标列 |
|---------|--------|-------|--------|
| 明细行（前 N 行） | `queries[0].result.data` | 全部填充 | 全部填充 |
| 小计行 | `queries[1+].result.data`（groupBy 长度 < Q0） | 仅填充 groupBy 包含的维度，其余留空 | 全部填充 |
| 总计行（最后一行） | `queries[last].result.data`（groupBy 为空） | 全部留空 | 全部填充 |

**小计行标注**：在"产品名称"或其他可辨识维度列中标注 `**小计**`，总计行标注 `**总计**`，用加粗区分。

**合并展示示例**：

```markdown
| 日期 | 渠道 | 销售小组 | 产品名称 | 毛利率 | SP广告费占比 |
| --- | --- | --- | --- | --- | --- |
| 2026-04-01 | wayfair-莱沃 | 清货组 | ON ST-105玄关桌黑色 | -10.42% | 1.07% |
| 2026-04-01 | wayfair-莱沃 | 清货组 | ON TVS-104电视柜橡木色 | -23.29% | 0.68% |
| 2026-04-01 | | | **小计** | **-20.39%** | **0.83%** |
| | | | **总计** | **6.29%** | **7.87%** |
```

#### 三、Excel 透视表输出规范

当用户需要导出 Excel 时，遵循以下规范：

**Sheet 结构**：

| Sheet 名称 | 内容 | 行数 |
|------------|------|------|
| 透视表主表 | 明细 + 小计 + 总计合并展示 | 所有 query 合计行数 |
| 可选附加 Sheet | 成本结构占比 / 同环比分析等 | 按需 |

**Excel 格式要求**：

1. **表头**：蓝色背景（`4472C4`）白色粗体字，冻结首行
2. **明细行**：常规格式，数值列使用千分位数字格式（`#,##0.00`），百分比列使用百分比格式（`0.00%`）
3. **小计行**：灰色背景（`D9E2F3`），粗体字
4. **总计行**：深蓝背景（`4472C4`）白色粗体字
5. **负毛利率**：红色字体（`FF0000`）标注亏损
6. **列宽自适应**：根据内容最大宽度自动调整（建议最大 50 字符）
7. **小计/总计数据来源**：必须直接从 `queries[1+].result.data` 读取，维度列缺失时留空

**使用 `excel_export.py` 导出 Excel**：

Skill 目录下提供 `scripts/excel_export.py`，封装了完整的透视表 Excel 导出逻辑（字段别名自动映射、明细/小计/总计合并、负值标红、列宽自适应），直接调用即可。

**前置依赖**：`pip install openpyxl`

```bash
cd ~/.claude/skills/ops-dataset-query/scripts

# 从已保存的 chart run 结果导出
python excel_export.py --input /tmp/chart_result.json --output /tmp/output.xlsx

# 通过 UUID 直接获取并导出（自动调用 opscli 执行查询）
python excel_export.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --output /tmp/output.xlsx

# 自定义 Sheet 名称
python excel_export.py --input /tmp/chart_result.json --output /tmp/output.xlsx --sheet-name 销售数据

# 安装在非标准路径时，指定 Skill 根目录
python excel_export.py --input /tmp/chart_result.json --output /tmp/output.xlsx --skills-dir ~/.openclaw/skills
```

**输出（stdout JSON）**：

```json
{
  "success": true,
  "output": "/tmp/output.xlsx",
  "rows": 25,
  "columns": ["部门名称", "渠道名称", "原价金额", "毛利润", "毛利率"],
  "chart_uuid": "32f660fd-f62a-45c4-a443-e21f2edb0779"
}
```

#### 四、Chart 查询完整工作流

```
用户请求查询图表
  │
  ├── 1. opscli auth token status（前置认证检查）
  │
  ├── 2. opscli query chart --uuid <id> --run --pretty > /tmp/chart_<uuid>.json
  │
  ├── 3. 分析查询结构
  │     ├── datasets（字段目录、可过滤字段、字段语义）
  │     ├── queries 数量（判断是否有小计/总计）
  │     ├── 每个 query 的 groupBy（识别明细/小计/总计）
  │     └── select 字段列表（确定维度和指标）
  │
  ├── 4. 字段别名映射
  │     ├── chart_map.py --input /tmp/chart_<uuid>.json --map-results --pretty
  │     ├── 优先读取服务端 field_mappings / datasets[].fields
  │     └── 仅在映射缺失时查 dataset_fields.csv 补充 verbose_name
  │
  ├── 5. 生成合并 Markdown 表格（明细 + 小计 + 总计）
  │     ├── 小计行：维度列按 groupBy 填充，其余留空，标注"小计"
  │     ├── 总计行：维度列全部留空，标注"总计"
  │     └── 百分比指标 ×100 格式化
  │
  └── 6. 用户要求 Excel 时
        └── python excel_export.py --input /tmp/chart_<uuid>.json --output /tmp/output.xlsx
```

---

#### Chart 查询字段别名映射与转换

Chart 查询返回的数据结构使用**数据集别名**和**字段别名**，现在推荐优先使用服务端返回的字段语义信息，再在缺失时回退到本地 metadata：

| 返回结构位置 | 别名类型 | 示例值 | 含义 |
|-------------|---------|--------|------|
| `datasets[].dataset_alias` / `query.from.alias` | 数据集别名（dataset_alias） | `ds_d35ac6f3910c` | 指向当前 query 所属数据集 |
| `datasets[].fields[].global_alias` | 字段别名（global_alias） | `f_520fb9a831ccd52a` | 服务端维护的统一字段别名 |
| `query.select[].alias` | 查询字段别名（query_alias） | `f_520fb9a831ccd52a` | 当前 query select 输出列名 |
| `query.select[].expr` | 完整字段表达式 | `ds_xxx.dept_name` | 实际 SQL 中使用的字段 |

**别名映射流程**：

```bash
# 1. 优先读取 chart 返回的 datasets[].fields / queries[].field_mappings
#    直接获得 verbose_name / field_name / origin_name / global_alias
#
# 2. 如果 chart 结构里字段语义不完整，再通过本地 metadata 或 dataset_fields.csv 补齐
#
# 3. 将查询结果中的列名（query_alias / global_alias）替换为可读的业务名称（verbose_name）
```

**实际映射示例**：

Chart 返回的 select 结构：
```json
[
  {"expr": "dept_name",  "alias": "f_520fb9a831ccd52a"},
  {"expr": "order_qty",  "alias": "f_9064850a20e4d581", "aggregation": "SUM"}
]
```

通过 `opscli query metadata --dataset ds_d35ac6f3910c` 获取字段映射：

| global_alias | field_name | verbose_name | field_type |
|-------------|-----------|-------------|-----------|
| `f_520fb9a831ccd52a` | `dept_name` | `部门名称` | dimension |
| `f_9064850a20e4d581` | `order_qty` | `订单数量` | metric |

查询结果列名转换：
```json
// 原始结果（列名为 global_alias）
{"f_520fb9a831ccd52a": "项目二部", "f_9064850a20e4d581": "1500"}

// 转换后（列名为 verbose_name 或 field_name）
{"部门名称": "项目二部", "订单数量": "1500"}
```

**重要提示**：
- `query.from.alias` 是数据集别名，不是表名；需要通过它获取 metadata 才能定位字段含义
- `select[].alias` 是全局唯一字段标识（global_alias），不是业务名称；展示时应转换为 `verbose_name`
- 如果同一图表包含多个 query（如下钻），每个 query 的 `from.alias` 可能相同（同一数据集），但 `select` 的字段组合不同
- 聚合查询的结果列名是 global_alias，需要额外步骤映射为可读名称

#### 使用本地脚本自动映射

Skill 目录下提供 `scripts/chart_map.py` 脚本，**直接使用本地 CSV 资源**进行字段别名映射，无需调用远端接口。

**数据目录自动发现机制**：
脚本会按以下优先级自动扫描 `ops-dataset-query/data/` 目录，**不固定写死路径**：

1. `--data-dir` 显式指定（最高优先级）
2. `--skills-dir` 显式指定安装根目录
3. 环境变量 `OPSCLI_SKILLS_DIR`
4. 当前目录下的 `.claude/skills`
5. `~/.claude/skills`
6. `~/.openclaw/skills`
7. `~/.codex/skills`
8. `~/.config/opencode/skills`
9. 脚本自身所在目录的相对路径（回退）

```bash
# 通过 chart_uuid 获取并自动映射（调用 opscli 获取结构，本地 CSV 解析字段）
cd ~/.claude/skills/ops-dataset-query/scripts
python chart_map.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty

# 映射到 field_name（英文字段名）
python chart_map.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --map-to field_name --pretty

# 获取并执行图表查询，同时映射结果行数据的列名
python chart_map.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --map-results --pretty

# 对已保存的 chart 结果文件进行映射
python chart_map.py --input /tmp/chart_result.json --pretty

# 对已保存的 chart run 结果映射结果行列名
python chart_map.py --input /tmp/chart_result.json --map-results --pretty

# 显式指定 Skill 安装目录（当安装在非标准位置时）
python chart_map.py --uuid xxx --skills-dir ~/.openclaw/skills --pretty

# 直接指定数据目录（最高优先级）
python chart_map.py --uuid xxx --data-dir /path/to/ops-dataset-query/data --pretty
```

**脚本说明**：
- 自动读取本地 `data/datasets.csv` 和 `data/dataset_fields.csv`
- 构建数据集索引和字段索引，通过 `(dataset_alias, global_alias)` 复合键快速定位
- 为每个 chart query 添加 `_mapping` 字段，包含数据集信息和字段映射关系
- 支持 `--map-to verbose_name`（默认，中文业务名）或 `--map-to field_name`（英文字段名）
- `--run`：自动通过 opscli 执行图表查询（需配合 `--uuid`）
- `--map-results`：将查询结果行数据中的 `global_alias` 列名也映射为可读名称，输出到 `mapped_results` 字段
- `--no-auto-upgrade`：禁用自动升级兜底（默认启用）

**自动升级兜底机制**：
当本地 CSV 数据无法匹配 chart 中的数据集或字段别名时（通常因为本地数据过期），脚本会自动：
1. 检测所有字段的 `field_info` 是否为空
2. 如果全部为空，自动调用 `opscli skills upgrade ops-dataset-query --force` 拉取最新远端数据
3. 重新加载本地索引并重新执行映射
4. 仅自动升级一次，避免无限循环

#### 使用 chart_analyze.py 自动异常检测

Skill 目录下提供 `scripts/chart_analyze.py` 脚本，自动获取图表数据、映射字段别名、检测业务角色，执行 5 类异常规则并输出结构化 JSON 报告。

```bash
cd ~/.claude/skills/ops-dataset-query/scripts

# 通过 chart_uuid 获取并自动分析（推荐）
python chart_analyze.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty

# 分析已保存的 chart run 结果
python chart_analyze.py --input /tmp/chart_result.json --pretty

# 附带 dataComparison 环比数据（增强趋势异常检测）
python chart_analyze.py --input /tmp/chart_result.json --dc-input /tmp/dc_result.json --pretty
```

**异常检测规则**：

| 规则 | 条件 | 严重度 |
|------|------|--------|
| `negative_margin` | 毛利率 < -20% | critical |
| `negative_margin` | 毛利率 < 0% | warning |
| `profit_drop` | 毛利环比下降 > 30%（需 `--dc-input`） | warning |
| `revenue_cliff` | 原价金额环比下降 > 20%（需 `--dc-input`） | warning |
| `ad_roi_decline` | 广告费上升 + 毛利下降（需 `--dc-input`） | warning |
| `zero_orders` | 当期订单量归零，对比期 > 0（需 `--dc-input`） | info |

**字段业务角色自动检测**：
脚本通过字段的 `verbose_name` / `field_name` 与预定义关键词模式匹配，自动识别以下角色：
- `revenue`（原价/金额）→ 用于毛利率计算、营收异常检测
- `profit`（毛利/利润）→ 用于亏损检测、利润趋势分析
- `ad_cost`（广告/推广）→ 用于广告 ROI 恶化检测
- `quantity`（订单量/数量）→ 用于订单归零检测

**输出结构**：包含 `summary`（汇总统计）、`anomalies`（异常列表，按 severity 排序）、`findings`（人类可读关键发现）。

**典型工作流（图表异常分析）**：

```bash
# 0. 检查认证
opscli auth token status

# 1. 通过 UUID 获取图表数据并分析当期异常
python chart_analyze.py --uuid <chart_uuid> --pretty

# 2. 如需环比趋势分析，先构造 dataComparison 查询
opscli query build --table-id <id> --dimension <dims> --metric <metrics> \
  --data-comparison "date_id,2026-03-01,2026-03-24" \
  --where "date_id|gte|\"2026-04-01\"" --where "date_id|lte|\"2026-04-24\"" \
  --output /tmp/dc.json --run --pretty > /tmp/dc_output.json

# 3. 合并分析当期 + 环比
python chart_analyze.py --uuid <chart_uuid> --dc-input /tmp/dc_output.json --pretty
```

---

## 降级方案：多次查询客户端合并（CLI 示例）

> **仅在 dataComparison 和 MOY 均无法满足需求时使用**（如工具限制、跨数据集对比）。

```bash
# 当期查询
opscli query build --table-id 1104 \
  --dimension dept_name:dept_name \
  --metric price:sum:total_price \
  --where "date_id|gte|\"2026-04-01\"" \
  --where "date_id|lte|\"2026-04-22\"" \
  --run --pretty > /tmp/cur.json

# 对比期查询
opscli query build --table-id 1104 \
  --dimension dept_name:dept_name \
  --metric price:sum:total_price \
  --where "date_id|gte|\"2026-03-01\"" \
  --where "date_id|lte|\"2026-03-22\"" \
  --run --pretty > /tmp/prev.json

# 客户端合并（Python 示例）
python3 -c "
import json
cur  = {r['dept_name']: r for r in json.load(open('/tmp/cur.json'))['data']['result']['data']}
prev = {r['dept_name']: r for r in json.load(open('/tmp/prev.json'))['data']['result']['data']}
for dept, c in cur.items():
    p = prev.get(dept, {})
    cv, pv = float(c['total_price']), float(p.get('total_price', 0))
    pct = (cv - pv) / abs(pv) * 100 if pv else float('inf')
    print(f'{dept}: 本期={cv:,.0f} 上期={pv:,.0f} 环比={pct:+.1f}%')
"
```

---

## 典型工作流（完整版）

### 手写高级 payload → 执行（备用）

> 仅当简化接口无法满足需求时使用（如复杂的 `joins`、`union`、自定义子查询等）。

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 按文档规范手写完整 payload（多次失败时才参考 data-query-service-dev-guide.md）
# 2. 执行
opscli query run --payload /tmp/advanced_query.json --pretty
```

### 通过图表 ID 直接查询

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 通过 chart_uuid 获取图表查询结构并执行
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --pretty

# 2. 仅查看查询结构，不执行
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty
```

> 图表查询会自动处理多 query 场景（主查询 + 下钻 + 汇总），结构模式返回 `datasets + queries`，执行模式会在此基础上补充 `result/merged`。
