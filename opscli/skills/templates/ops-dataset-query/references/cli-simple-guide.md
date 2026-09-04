---
name: ops-dataset-query-cli-simple
description: CLI 模式 — 查询命令详解（opscli query simple / opscli query chart / 辅助脚本）
---

# CLI 查询指南

本文档涵盖 CLI 模式下所有查询命令的详细说明与示例。

> **阅读前提**：先阅读 `references/simple-query-guide.md` 理解简化接口的通用参数结构。
>
> **文档引用顺序**：优先按本文档和 `simple-query-guide.md` 处理。

---

## 命令说明

- **`opscli query simple`**（推荐）：基于简化参数构造并执行查询。服务端自动处理 `translate`、`MOY` 展开等技术细节。普通聚合、数据对比、MOY 趋势等场景优先使用。
- **`opscli query chart`**：通过图表 ID 获取查询结构并执行，支持多 query 自动合并。涉及小计/总计、字段映射、Excel 导出等复杂场景。
- **`opscli query chart-doc`**：通过图表 UUID 获取图表文档描述。

---

## `opscli query simple`（推荐优先使用）

基于简化参数构造并执行查询。服务端自动处理 `translate`、`MOY` 展开等技术细节。

```
选项：
  --table-id INTEGER   数据集 ID（必填）
  --payload TEXT       简化查询 JSON 文件路径（与 --json 二选一）
  --json TEXT          简化查询 JSON 字符串（与 --payload 二选一）
  --output TEXT        将 payload 写入指定文件
  --global-currency TEXT  全局币种（仅 USD/GBP/CAD/EUR/JPY/CNY），由服务端换算金额指标
  --run                构造后立即执行查询
  --pretty             格式化 JSON 输出
```

> **币种是换算参数，不是字段**：`--global-currency` 写在请求上由服务端换算，元数据里没有 `currency` 字段属正常，不要去字段清单里找、也不要塞进 `filters`。识别到币种意图才传，未识别时不传（服务端回退用户默认配置）。多币种 = 逐币种各执行一次，除该参数外其余完全一致：
>
> ```bash
> opscli query simple --table-id 1 --json '<同一份 payload>' --global-currency USD --run
> opscli query simple --table-id 1 --json '<同一份 payload>' --global-currency EUR --run
> ```

> **【强制】`--payload` 与 `--json` 互斥**：两者只能使用其中一个，不可同时传入。
> - `--payload`：从文件读取 JSON（适合复杂/多行查询）
> - `--json`：直接传入 JSON 字符串（适合简单查询）
> - 同时传入时 CLI 会报错

```bash
# 正确：使用 --json 内联传入
opscli query simple --table-id 1 \
  --json '{"dimensions":[{"field":"dept_name","alias":"f_dept"}],"metrics":[{"field":"fi_first_leg_trailer_fee","aggregation":"SUM","alias":"f_fee_sum"}],"filters":[{"field":"date_id","operator":"between","value":["2026-04-01","2026-04-22"]}],"limit":10}' \
  --run --pretty

# 正确：使用 --payload 从文件读取
opscli query simple --table-id 1 \
  --payload /tmp/simple.json \
  --run --pretty
```

**简化参数结构**详见 `references/simple-query-guide.md`。

---

## 公式字段（Formula Field）处理规则

当 metric 字段的 metadata 中包含 `summary_expression` 或 `detail_expression` 时（如 ACOS、ROAS、平均单价等比率 / 占比指标），在 `metrics` JSON 中需额外传入 `expr` 字段，指定服务端使用的完整公式表达式。

**选择规则**：
- **默认**（聚合 / 分组查询）：使用字段 metadata 中的 `summary_expression` 值
- **明细 / 详情查询**（用户提到"明细"、"详情"、"每一行"、"行级"等关键词时）：使用 `detail_expression` 值

**操作步骤**：
1. 先执行 `opscli query metadata --dataset <alias> --pretty` 获取字段 metadata，读取目标字段的 `summary_expression` 或 `detail_expression` 值
2. 将对应表达式字符串赋给 metric 对象的 `expr` 字段
3. `aggregation`、`alias` 等字段照常传入；服务端识别到 `expr` 后以 `expr` 为准

**示例**（含公式字段 `acos`，默认聚合查询）：

```bash
opscli query simple --table-id 15 \
  --json '{
    "dimensions": [{"field": "dev_team_name", "alias": "f_team"}],
    "metrics": [
      {"field": "sp_total_spend_cny", "aggregation": "SUM", "alias": "f_sp_spend"},
      {
        "field": "acos",
        "aggregation": "SUM",
        "alias": "f_acos",
        "expr": "ROUND(total_spend_cny / sales_cny, 4)"
      }
    ],
    "filters": [
      {"field": "platform_name", "operator": "=", "value": "Amazon"},
      {"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}
    ],
    "orderBy": [{"field": "f_sp_spend", "desc": true}],
    "limit": 200
  }' \
  --run --pretty
```

**明细查询示例**（用户提到"明细"时，改用 `detail_expression`）：

```bash
opscli query simple --table-id 15 \
  --json '{
    "metrics": [
      {
        "field": "days_on_hand",
        "alias": "f_days_on_hand",
        "expr": "ROUND(30 / (total_sell_qty / sell_avg_qty))"
      }
    ],
    "filters": [
      {"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}
    ],
    "limit": 50
  }' \
  --run --pretty
```

> ⚠️ **不传 `expr` 时的行为**：服务端仍会尝试自动识别公式字段并使用正确表达式，但显式传 `expr` 可以确保语义准确、避免版本差异导致的行为不一致。

---

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

**数据展示规范**：

1. **必须遍历所有 queries**，不能只读 `queries[0]`
2. 小计行/总计行的字段数比明细行少（缺少非 groupBy 的维度列），展示时缺失维度列留空即可
3. **禁止自行累加明细行来计算小计/总计**，服务端的聚合逻辑可能与简单累加存在差异（如精度、过滤条件）
4. 展示顺序建议：按部门分组 → 该部门明细行 → 该部门小计 → 下一个部门 → ... → 总计

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

**前置依赖**：`pip install openpyxl`

```bash
cd ~/.claude/skills/ops-dataset-query/scripts

# 从已保存的 chart run 结果导出
python excel_export.py --input /tmp/chart_result.json --output /tmp/output.xlsx

# 通过 UUID 直接获取并导出（自动调用 opscli 执行查询）
python excel_export.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --output /tmp/output.xlsx

# 自定义 Sheet 名称
python excel_export.py --input /tmp/chart_result.json --output /tmp/output.xlsx --sheet-name 销售数据
```

**Excel 格式要求**：

1. **表头**：蓝色背景（`4472C4`）白色粗体字，冻结首行
2. **明细行**：常规格式，数值列使用千分位数字格式（`#,##0.00`），百分比列使用百分比格式（`0.00%`）
3. **小计行**：灰色背景（`D9E2F3`），粗体字
4. **总计行**：深蓝背景（`4472C4`）白色粗体字
5. **负毛利率**：红色字体（`FF0000`）标注亏损
6. **列宽自适应**：根据内容最大宽度自动调整（建议最大 50 字符）
7. **小计/总计数据来源**：必须直接从 `queries[1+].result.data` 读取，维度列缺失时留空

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
  │     └── 映射不完整时手动补充（从 expr 提取 field_name → dataset_fields.csv 查 verbose_name）
  │
  ├── 5. 展示或导出
  │     ├── Markdown 表格（合并明细 + 小计 + 总计）
  │     └── excel_export.py 导出 Excel
  │
  └── 6.（可选）chart_analyze.py 异常检测
```

---

## 辅助脚本索引

### `chart_map.py` — chart 字段映射

将 chart 查询结果中的 `global_alias` 映射为可读的 `verbose_name` 或 `field_name`。

```bash
# 通过 chart_uuid 获取并映射
python scripts/chart_map.py --uuid <chart_uuid> --pretty

# 映射到 field_name
python scripts/chart_map.py --uuid <chart_uuid> --map-to field_name --pretty

# 获取并执行图表查询，同时映射结果行数据的列名
python scripts/chart_map.py --uuid <chart_uuid> --run --map-results --pretty

# 对已保存的 chart 结果文件进行映射
python scripts/chart_map.py --input /tmp/chart_result.json --pretty
```

**数据目录自动发现**：脚本会按以下顺序查找 `data/` 目录（不固定写死路径）：`--data-dir` > `--skills-dir` > `OPSCLI_SKILLS_DIR` 环境变量 > `.claude/skills` > `~/.claude/skills` > `~/.openclaw/skills` > `~/.codex/skills` > 脚本自身所在目录的相对路径。

### `chart_analyze.py` — 图表异常检测

自动获取图表数据、映射字段别名、检测业务角色，执行 5 类异常规则并输出结构化 JSON 报告。

```bash
# 通过 chart_uuid 获取并自动分析（推荐）
python scripts/chart_analyze.py --uuid <chart_uuid> --pretty

# 分析已保存的 chart run 结果
python scripts/chart_analyze.py --input /tmp/chart_result.json --pretty

# 附带 dataComparison 环比数据（增强趋势异常检测）
python scripts/chart_analyze.py --input /tmp/chart_result.json --dc-input /tmp/dc_result.json --pretty
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

**输出结构**：包含 `summary`（汇总统计）、`anomalies`（异常列表，按 severity 排序）、`findings`（人类可读关键发现）。

### `excel_export.py` — 图表数据 Excel 导出

从 chart 查询结果中提取明细、小计、总计数据，按透视表格式写入 Excel。

```bash
python scripts/excel_export.py --input /tmp/chart_result.json --output /tmp/output.xlsx --sheet-name 销售数据
```


## 典型工作流

### 探索数据集 → 构造 → 执行（已知数据集时）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 通过本地索引确认字段名
# 2. 查看完整 metadata（获取 table_id 和字段信息）
opscli query metadata --dataset sales_order_d --pretty

# 3. 使用简化接口构造并执行
opscli query simple \
  --table-id 1 \
  --json '{
    "dimensions": [{"field": "date_id", "alias": "f_date"}],
    "metrics": [{"field": "order_cost", "aggregation": "SUM", "alias": "f_total_cost"}],
    "filters": [{"field": "date_id", "operator": "between", "value": ["2024-01-01", "2024-12-31"]}],
    "orderBy": [{"field": "f_total_cost", "desc": true}],
    "limit": 50
  }' \
  --run --pretty
```

### 环比查询（MOY 月环比 — 简化接口）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 使用简化接口执行 MOY 查询（1 行 metrics 声明，服务端自动展开为 3 列）
opscli query simple --table-id 1 \
  --json '{
    "dimensions": [
      {"field": "dept_name", "alias": "f_dept"},
      {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}
    ],
    "metrics": [
      {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"},
      {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_moy", "comparison": "MOY", "moyType": "MOM_MONTH"}
    ],
    "filters": [
      {"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-04-22"]}
    ],
    "orderBy": [{"field": "f_month", "desc": true}],
    "limit": 20
  }' \
  --run --pretty

# 返回列：f_dept, f_month, f_fee_sum, f_fee_moy_prev, f_fee_moy_diff, f_fee_moy_pct
```

### 环比查询（dataComparison — 简化接口）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 使用简化接口执行 dataComparison 查询
opscli query simple --table-id 1 \
  --json '{
    "dimensions": [{"field": "dept_name", "alias": "f_dept"}],
    "metrics": [{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    "filters": [{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    "dataComparison": {"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    "limit": 10
  }' \
  --run --pretty

# 返回列：f_dept, f_fee_sum, last_f_fee_sum, diff_f_fee_sum, pct_f_fee_sum
```

> 完整简化参数说明见 `references/simple-query-guide.md`。

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

