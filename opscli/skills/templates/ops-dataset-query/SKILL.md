---
name: ops-dataset-query
description: 使用本地缓存的数据集与字段索引辅助检索和查询
version: v0.0.2
---

# ops-dataset-query

使用本地缓存的数据集与字段索引辅助检索可用数据集、维度和指标，通过 `opscli query` 执行数据查询，通过 `opscli skills upgrade` 拉取远端最新数据。

---

## 调用前置要求

> **【强制】每次调用 `ops-dataset-query` 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现“未登录 / 未授权 / Token 过期 / expired / 401”等状态，必须立即调用 `ops-auth` Skill
- 若是“未登录 / 未授权 / 401”等状态，在 `ops-auth` 中执行 `opscli auth login` 完成授权登录
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh`（例如 `opscli auth token refresh --all` 或 `opscli auth token refresh -s ops`）；刷新失败或仍异常时，再执行 `opscli auth login`
- 登录或刷新后重新执行 `opscli auth token status`
- 只有认证状态确认正常后，才允许继续读取本地索引、执行 `opscli query metadata`、`build`、`run`、`opscli skills upgrade ops-dataset-query`
- 即使当前动作只是本地字段搜索或本地 metadata 辅助，也必须先完成这一轮登录检测

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

> **【强制】使用本 Skill 前，必须先阅读 `references/数据查询服务开发说明文档.md`**

- 若需求涉及 `innerWhere`、子查询数据集、`translate`、`dataComparison`、高级计算（`MOY` / `ACC` / `PPT`）、权限占位符、小计/总计、交叉表/透视表、多次查询等场景，**必须**回到该引用文档逐节核对后再生成 payload
- WHERE 操作符完整列表、聚合函数完整列表、请求体完整结构均在引用文档中，本文件不再赘述
- 若引用文档与仓库原文冲突，以仓库原文 `docs/query/数据查询服务开发说明文档.md` 为准

---

## 使用原则

- 本 Skill 只负责本地字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 `opscli query` 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `opscli skills upgrade ops-dataset-query` 再重试查询
- 字段搜索结果已按相关性排序（精确匹配 > 子串匹配 > 关键词匹配）
- `opscli query build` 适合常见聚合查询（select / groupBy / where / having / orderBy / limit / offset / dryRun）
- `opscli query run` 适合透传完整高级 payload（`innerWhere`、`joins`、`dataComparison`、`translate` 等复杂场景）
- 所有查询工作流都必须以前置的 `ops-auth` 登录检测作为起点

### 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案，禁止跳过高优先级直接多次调用 CLI 后在客户端合并结果**。

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `opscli query run` + 客户端合并 |

> `comparison`（MOY/ACC/PPT）写在 `select` 字段内部可正常透传。

---

## 本地数据文件

| 文件 | 内容 | 说明 |
|------|------|------|
| `data/VERSION.json` | 版本号 | `{"name": "ops-dataset-query", "version": "v1.x.x"}` |
| `data/dataset_fields.csv` | 字段明细 | dataset_alias、field_name、verbose_name、global_alias、field_type、formula_config、detail_expression、summary_expression 等 |
| `data/datasets.csv` | 数据集列表 | table_id、dataset_alias、dataset_name、dataset_type、dataset_category、data_source、main_dttm_col、inner_where_enabled、cache_timeout、description |
| `data/query_metadata.json` | 查询元数据 | 字段类型映射、可用聚合方式等 |

CSV 各列详细说明见 `references/数据查询服务开发说明文档.md` 附录。

---

## 命令参考

### `opscli query metadata`

读取指定数据集的 query metadata（字段定义、可用聚合方式等）。

```
选项：
  --dataset TEXT      dataset_alias（与 --table-id 二选一）
  --table-id INTEGER  table_id（与 --dataset 二选一）
  --skills-dir TEXT   指定 Skill 目录
  --pretty            格式化 JSON 输出
```

```bash
opscli query metadata --dataset sales_order_d --pretty
opscli query metadata --table-id 123 --pretty
```

---

### `opscli query build`

基于简化参数构造标准 query payload，可选直接执行。

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

#### 参数格式

**dimension**：`field_name|global_alias|verbose_name[:alias]`
- `date_id` → 按 date_id 分组，默认优先使用字段的 `global_alias` 作为输出列名
- `date_id:f_date_id` → 按 date_id 分组，列名改为 `f_date_id`

**metric**：`field_name|global_alias|verbose_name:aggregation[:alias]`
- `order_cost:sum` → 求和
- `order_cost:sum:total_cost` → 求和，列名改为 total_cost
- `order_id:count_distinct:uv` → 去重计数

> `select.alias` 不支持中文；如果不显式传 alias，`opscli query build` 会优先使用字段 metadata 中的 `global_alias`，没有时再回退到 `field_name`。

> 完整聚合函数列表见 `references/数据查询服务开发说明文档.md` 第八章。

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
- 如果公式字段继续写成 `field_name + aggregation`，容易出现二次聚合或语义错误
- 显式传 alias 时，只允许英文、数字和下划线，且不能以数字开头；中文 alias 会被拒绝

**常见易错对照**
- 普通求和指标：`price:sum` 或手写 `{ "expr": "ds_xxx.price", "alias": "f_price", "aggregation": "SUM" }`
- 公式占比指标：手写 `{ "expr": "ROUND(SUM(dsp)/SUM(price), 4)", "alias": "f_yZZfW7cNu8nYMGCS" }`
- 公式平均指标：手写 `{ "expr": "ROUND(SUM(original_price) / SUM(order_qty), 4)", "alias": "f_xxx_avg_price" }`
- 错误写法：`sell_qty_days:sum`、`avg_original_price_cny:sum` 这类公式字段继续套普通聚合

**查询前 checklist**
- 先看字段 metadata 里是否有 `has_formula_config = 1`
- 如果有，再检查是否提供了 `summary_expression` 和 / 或 `detail_expression`
- 明细查询优先使用 `detail_expression`
- 聚合 / 分组查询优先使用 `summary_expression`
- 手写 payload 时，公式字段不要再额外传 `aggregation`
- 使用 `opscli query build` 时，可以继续传字段标识，CLI 会按 metadata 自动展开
- 如果字段同时没有 `summary_expression`、`detail_expression`，不要直接猜写法，应回到 metadata 或服务端字段定义确认

**where**：`field|operator|value_json`（完整操作符列表见引用文档第五章）

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

#### 示例

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

### `opscli query run`

执行查询，将 payload 文件转发到服务端。

```
选项：
  --payload TEXT   查询 JSON 文件路径（必填）
  --pretty         格式化 JSON 输出
```

```bash
opscli query run --payload /tmp/query.json --pretty
```

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

### `opscli skills upgrade ops-dataset-query`

从运营系统后端拉取最新字段数据，原子替换本地 `data/` 目录。

```
选项：
  --force        强制重新拉取（忽略版本比较）
  --skills-dir   指定 Skill 目录
  --pretty       格式化 JSON 输出
```

```bash
# 检查版本状态
opscli skills status --pretty

# 升级到最新
opscli skills upgrade ops-dataset-query

# 强制重新拉取
opscli skills upgrade ops-dataset-query --force
```

---

## 字段搜索（本地索引）

本 Skill 内置本地字段索引，可用于辅助确认 `dataset_alias`、`field_name`、`verbose_name`。

**推荐流程**：本地索引确认字段名 → `opscli query metadata` 查看完整 metadata → `opscli query build` 或手写 payload + `opscli query run`

**搜索排序策略（相关性从高到低）：**

| 匹配类型 | 分值 |
|---------|------|
| `field_name` 精确匹配 | 120 |
| `verbose_name` 精确匹配 | 100 |
| `field_name` 子串匹配 | 60 |
| `verbose_name` 子串匹配 | 45 |
| `dataset_alias` 精确匹配 | 40 |
| `description` 子串匹配 | 10 |

---

## 高级查询说明

详细规则见 `references/数据查询服务开发说明文档.md`，核心章节：

| 场景 | 参考章节 |
|------|---------|
| innerWhere、子查询数据集 | 第三章 数据集类型详解 |
| WHERE 操作符、嵌套条件、translate | 第五章 WHERE 条件构建指南 |
| dataComparison 数据对比 | 第六章 |
| 多次查询（交叉表/透视表/堆叠图） | 第七章 |
| SELECT 字段、聚合函数、高级计算(MOY/ACC/PPT) | 第八章 |
| 权限占位符 | 第四章 |
| 分页与排序 | 第九章 |

**使用建议**：
- 普通聚合优先使用 `opscli query build`
- 涉及上述高级场景时，先阅读引用文档，再手写 payload + `opscli query run`

---

## 数据对比与高级计算

### 方案选择决策流程

```
用户需要比较两个时间段的数据？
├── YES → 需要按时间粒度（日/月）分组展示趋势？
│         ├── YES → 使用 MOY 高级计算（comparison 写在 select 字段内）
│         └── NO  → 需要当期 vs 对比期汇总对比？
│                   ├── YES → 使用 dataComparison（服务端一次 SQL，推荐首选）
│                   └── NO  → 普通聚合 opscli query build
└── NO  → 普通聚合 opscli query build
```

---

### dataComparison 数据对比

> 服务端将当期和对比期合并为**一次 SQL**（条件聚合），每个度量字段自动裂变为 4 个字段。

**字段裂变规则**（以别名 `total_price` 为例）：

| 裂变字段 | 含义 |
|---------|------|
| `total_price` | 当期值 |
| `last_total_price` | 对比期值 |
| `diff_total_price` | 绝对差值（当期 - 对比期） |
| `pct_total_price` | 变化率（差值 / ABS(对比期)），上期为 0 时返回 null |

**payload 结构**（`opscli query run --payload`）：

```json
{
  "tableId": 1104,
  "query": {
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "dept_name"},
      {"expr": "ds_xxx.price", "alias": "total_price", "aggregation": "SUM"},
      {"expr": "ds_xxx.order_qty", "alias": "total_qty", "aggregation": "SUM"}
    ],
    "groupBy": ["dept_name"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-04-01"},
        {"field": "ds_xxx.date_id", "operator": "lte", "value": "2026-04-22"}
      ]
    },
    "orderBy": [{"expr": "total_price", "desc": true}],
    "limit": 50,
    "offset": 0
  },
  "dataComparison": {
    "switch": true,
    "field": "ds_xxx.date_id",
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  }
}
```


**适用场景**：当期（如本月 1-22 日） vs 对比期（如上月同期 1-22 日）的汇总数据对比，**同期天数对等**，适合月度/季度环比汇总看板。

---

### MOY 同环比（高级计算）

> 服务端通过窗口函数 `LAG()` 计算，**`comparison` 字段写在 `select` 内部**，opscli 可正常透传。

**前提条件**：`groupBy` 中**必须同时包含日期维度和其他业务维度**。

**type 枚举速查**：

| 类型 | `type` 值 | groupBy 日期格式 |
|------|-----------|----------------|
| 月环比 | `MOM_MONTH` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m')` |
| 日环比 | `MOM_DAY` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m-%d')` |
| 周环比 | `MOM_WEEK` | `DATE_FORMAT(ds_xxx.date_id, '%x-%v')` |
| 月同比 | `YOY_MONTH` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m-%d')` |
| 年同比 | `YOY_YEAR` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m-%d')` |

**`cacl_type` 字段语义**（重要，容易误解）：

| `cacl_type` | 字段值含义 | 说明 |
|-------------|-----------|------|
| `ORIGINAL` | **上期值（LAG）** | 不是当期原始值！是前一期的聚合结果 |
| `COMPARE` | 当期 − 上期 | 正数=增长，负数=下滑 |
| `PERCENT` | (当期 − 上期) / ABS(上期) | 环比变化率，上期为 0 时返回 null |

> 💡 当期实际值 = `ORIGINAL 字段值` + `COMPARE 字段值`

**完整 payload 示例（月环比，按部门）**：

```json
{
  "tableId": 1104,
  "query": {
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "dept_name"},
      {"expr": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')", "alias": "month"},
      {
        "expr": "ds_xxx.price",
        "alias": "price_prev",
        "comparison": "MOY",
        "params": {
          "date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')",
          "dim": ["dept_name"],
          "type": "MOM_MONTH",
          "cacl_type": "ORIGINAL",
          "aggregation": "SUM"
        }
      },
      {
        "expr": "ds_xxx.price",
        "alias": "price_diff",
        "comparison": "MOY",
        "params": {
          "date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')",
          "dim": ["dept_name"],
          "type": "MOM_MONTH",
          "cacl_type": "COMPARE",
          "aggregation": "SUM"
        }
      },
      {
        "expr": "ds_xxx.price",
        "alias": "price_pct",
        "comparison": "MOY",
        "params": {
          "date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')",
          "dim": ["dept_name"],
          "type": "MOM_MONTH",
          "cacl_type": "PERCENT",
          "aggregation": "SUM"
        }
      }
    ],
    "groupBy": ["dept_name", "month"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-03-01"},
        {"field": "ds_xxx.date_id", "operator": "lte", "value": "2026-04-22"}
      ]
    },
    "orderBy": [
      {"expr": "month", "desc": true},
      {"expr": "price_diff", "desc": true}
    ],
    "limit": 100,
    "offset": 0
  }
}
```

**结果读取说明**：
- 当月行（如 `2026-04`）：`price_prev` = 上月值，`price_diff` = 本月增减，`price_pct` = 环比率
- 上月行（如 `2026-03`）：`price_prev` = 上上月值，其他同理
- WHERE 范围需覆盖**当期 + 对比期**（至少两个完整粒度），否则最早一期 `price_prev` 为 NULL

**适用场景**：按月/日/周分组的趋势图、时序对比；注意 MOY 用整个历史周期做 LAG，与 `dataComparison` 的同期对比不同，**月中查询时本月 vs 上月完整月存在天数不等的偏差**。

---

### ACC 累加计算

> 按时间序列滚动累计（Running Total），适合 YTD 累计销售额等场景。

```json
{
  "expr": "ds_xxx.price",
  "alias": "price_acc",
  "comparison": "ACC",
  "params": {
    "dim": [],
    "aggregation": "SUM"
  }
}
```

> `dim` 当前固定传空数组 `[]`，暂不支持分组累加。

---

### PPT 占比计算

> 当前维度指标值 ÷ 全局总量，适合各部门销售额占比等场景。

```json
{
  "expr": "ds_xxx.price",
  "alias": "price_ppt",
  "comparison": "PPT",
  "params": {
    "dim": [],
    "aggregation": "SUM"
  }
}
```

---

### 降级方案：多次查询客户端合并

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

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 检查拼写或 `opscli skills upgrade` 同步最新数据集 |
| 未登录 | 调用 `ops-auth` Skill，并执行 `opscli auth login` |
| Token 过期 | 调用 `ops-auth` Skill，优先执行 `opscli auth token refresh --all`；刷新失败或仍异常时再执行 `opscli auth login` |
| opscli 未找到 | 激活虚拟环境或设置 `OPSCLI_BIN` |
| 远端 manifest 不存在 | 检查网络和 ops 服务地址配置 |
| payload 文件不存在 | 先 `opscli query build --output` 生成 |

---

## AI Agent 使用规范

### 【禁止】用管道截断 opscli 输出后再解析 JSON

> ⚠️ **典型错误**：将 `opscli query ... --run --pretty` 通过 `| head -N` 截断后，尝试解析输出为 JSON，必然报 `JSONDecodeError`。

**错误原因**：`| head -N` 在读取 N 行后关闭管道，opscli 进程输出被强制截断，JSON 结构不完整。Claude Code 的 persisted-output 临时文件同样只是截断预览，**不可作为 JSON 解析源**。

**禁止写法**：
```bash
# ❌ 错误：head 截断了 JSON，无法解析
opscli query build ... --run --pretty 2>&1 | head -80

# ❌ 错误：读取 persisted-output 临时文件（内容截断，JSON 不完整）
with open('/path/to/tool-results/xxxxx.txt') as f:
    data = json.load(f)
```

**正确写法**：始终将完整输出重定向到临时文件，再读取解析：
```bash
# ✅ 正确：完整输出到文件
opscli query build ... --run --pretty > /tmp/result.json

# ✅ 或使用 --output 参数
opscli query build ... --output /tmp/result.json --run

# ✅ Python 解析时从临时文件读取
python3 -c "import json; print(json.load(open('/tmp/result.json'))['data']['result']['meta'])"
```

---

## 典型工作流

### 探索数据集 → 构造 → 执行

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 通过本地索引确认数据集和字段名
# 2. 查看完整 metadata
opscli query metadata --dataset sales_order_d --pretty
# 3. 构造并执行
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric order_cost:sum:total_cost \
  --where "date_id|gte|\"2024-01-01\"" \
  --order-by total_cost:desc \
  --limit 50 \
  --run --pretty
```

### 手写高级 payload → 执行

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 按引用文档规范手写 payload（含 innerWhere / dataComparison 等）
# 2. 执行
opscli query run --payload /tmp/advanced_query.json --pretty
```

### 环比查询（MOY 月环比，当前推荐方案）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 手写含 comparison 字段的 payload，覆盖当期 + 对比期的 WHERE 范围
cat > /tmp/moy_query.json << 'EOF'
{
  "tableId": 1104,
  "query": {
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "dept_name"},
      {"expr": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')", "alias": "month"},
      {
        "expr": "ds_xxx.price", "alias": "price_prev",
        "comparison": "MOY",
        "params": {"date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')", "dim": ["dept_name"], "type": "MOM_MONTH", "cacl_type": "ORIGINAL", "aggregation": "SUM"}
      },
      {
        "expr": "ds_xxx.price", "alias": "price_diff",
        "comparison": "MOY",
        "params": {"date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')", "dim": ["dept_name"], "type": "MOM_MONTH", "cacl_type": "COMPARE", "aggregation": "SUM"}
      },
      {
        "expr": "ds_xxx.price", "alias": "price_pct",
        "comparison": "MOY",
        "params": {"date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')", "dim": ["dept_name"], "type": "MOM_MONTH", "cacl_type": "PERCENT", "aggregation": "SUM"}
      }
    ],
    "groupBy": ["dept_name", "month"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-03-01"},
        {"field": "ds_xxx.date_id", "operator": "lte", "value": "2026-04-22"}
      ]
    },
    "orderBy": [{"expr": "month", "desc": true}, {"expr": "price_diff", "desc": true}],
    "limit": 100, "offset": 0
  }
}
EOF

# 2. 执行查询
opscli query run --payload /tmp/moy_query.json --pretty

# 3. 结果说明：
#    price_prev = 上月销售额（LAG值）
#    price_diff = 本月增减额（当期 - 上期）
#    price_pct  = 环比变化率（小数，×100 得百分比）
#    当期实际值 = price_prev + price_diff
```

### 环比查询（dataComparison，推荐首选）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# dataComparison payload 结构（服务端一次 SQL，推荐优先使用）
cat > /tmp/dc_query.json << 'EOF'
{
  "tableId": 1104,
  "query": {
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "dept_name"},
      {"expr": "ds_xxx.price", "alias": "total_price", "aggregation": "SUM"}
    ],
    "groupBy": ["dept_name"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-04-01"},
        {"field": "ds_xxx.date_id", "operator": "lte", "value": "2026-04-22"}
      ]
    },
    "orderBy": [{"expr": "total_price", "desc": true}],
    "limit": 50, "offset": 0
  },
  "dataComparison": {
    "switch": true,
    "field": "ds_xxx.date_id",
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  }
}
EOF
# 响应自动包含：total_price / last_total_price / diff_total_price / pct_total_price
```

### 数据更新 → 重新查询

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli skills status --pretty
opscli skills upgrade ops-dataset-query
opscli query metadata --dataset sales_order_d --pretty
```

---

## 安装与管理

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli skills install ops-dataset-query            # 安装
opscli skills install ops-dataset-query --force     # 强制重装
opscli skills status --pretty                       # 查看版本
opscli skills upgrade ops-dataset-query             # 升级
```
