# opscli 数据查询服务优化方案

> 版本：v1.0 | 日期：2026-05-06 | 状态：待确认

---

## 一、现状梳理

### 1.1 系统架构

当前数据查询服务采用三层架构：

```
┌─────────────────────────────────────────────────────────────┐
│  客户端 (opscli Python)                                      │
│  ├── query build  →  构造标准 query payload                  │
│  ├── query run    →  透传完整 payload                        │
│  └── query chart  →  通过 chart_uuid 获取结构并执行          │
└─────────────────────────────────────────────────────────────┘
                              │ POST /v1/data-metrics/cli-query
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  服务端 (PHP - auto-scheduler)                               │
│  ├── CliQueryApiController  →  接收 payload，参数校验        │
│  ├── CliQueryService        →  权限检查、构建 from 子句      │
│  └── PythonQueryConfigResolver → 解析表配置、构建 from       │
└─────────────────────────────────────────────────────────────┘
                              │ 转发到 Python API
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  查询引擎 (Python Service)                                   │
│  ├── 生成并执行 SQL                                          │
│  ├── 处理权限占位符替换                                      │
│  ├── 处理 dataComparison SQL 改写                            │
│  └── 处理 innerWhere 子查询嵌套                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 当前请求体结构（完整版）

```json
{
  "tableId": 1104,
  "query": {
    "from": {              /* 服务端实际构建，但文档要求理解 */
      "table": "...",
      "alias": "ds_xxx",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "f_dim001"},
      {"expr": "ds_xxx.price", "alias": "f_metric001", "aggregation": "SUM"}
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
      ]
    },
    "innerWhere": [        /* 子查询类型专用，极易出错 */
      [],
      {
        "operator": "AND",
        "conditions": [
          {"field": "bc.platform_name", "operator": "in", "value": ["Amazon"]}
        ]
      }
    ],
    "groupBy": ["f_dim001"],
    "orderBy": [{"expr": "f_metric001", "desc": true}],
    "limit": 20,
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

---

## 二、核心问题分析

### 2.1 文档体量过大，AI 负担过重

| 文档 | 行数 | 核心内容 |
|------|------|----------|
| `data-query-service-dev-guide.md` | **1,173 行** | 请求体完整结构、数据集类型详解、权限控制、WHERE 构建、translate 枚举、dataComparison、多次查询、SELECT 规范、MOY/ACC/PPT 高级计算、分页排序、开发注意事项 |
| `cli.md` | **1,160 行** | CLI 模式完整使用指南、认证流程、命令参考、工作流示例、AI Agent 规范、字段搜索、降级方案 |
| `mcp.md` | **884 行** | MCP 无状态模式完整指南、认证工具、辅助脚本、Tool 调用参考、工作流示例 |
| `query-patterns.md` | **225 行** | dataComparison / MOY / ACC / PPT 的 payload 结构和示例 |
| **合计** | **≈ 3,442 行** | — |

**问题**：
- 大模型每次构造查询都需要面对超过 3400 行的参考文档，context window 消耗巨大
- 文档中包含大量服务端内部实现细节（如权限占位符替换原理、innerWhere 层级映射、translate 枚举表），对 AI 来说是"噪音"
- 文档之间存在重复内容（如 dataComparison 示例同时在 cli.md、query-patterns.md、mcp.md 中出现）

### 2.2 查询结构复杂，大模型构建失败率高

#### 2.2.1 innerWhere 问题（最严重）

**复杂度来源**：
1. 需要判断数据集类型（`inner_where_enabled`），决定过滤条件放 `where` 还是 `innerWhere`
2. `innerWhere` 是数组，顺序对应子查询嵌套层级：
   - `innerWhere[0]` → 对应 `{where_sub_placeholder_1}`（外层子查询，通常传空）
   - `innerWhere[1]` → 对应 `{and_sub_placeholder_2}`（内层原始表，放业务条件）
3. 日期条件必须放在外层 `where`，业务维度过滤放在 `innerWhere[1]`
4. `innerWhere` 中的字段前缀与外层不同（如 `bc.platform_name` vs `ds_xxx.date_id`）

**大模型典型错误**：
- 把日期条件放进 `innerWhere`
- `innerWhere` 数组层级顺序错误（如把条件放 `innerWhere[0]`）
- 非子查询类型也传 `innerWhere`
- 混淆字段前缀（该用 `bc.` 的用了 `ds_xxx.`）

#### 2.2.2 translate 问题

**复杂度来源**：
- 20+ 种 translate 枚举值（如 `CHANNEL_TO_SKU`、`SKU_TO_ASIN`、`ASIN_TO_MSKU` 等）
- 需要按字段名精确匹配正确的 translate 值
- 不是所有字段都需要 translate，但 AI 无法准确判断

**大模型典型错误**：
- 给不需要 translate 的字段（如 `date_id`）错误添加 translate
- 给需要 translate 的字段选错枚举值（如 `channel_name` 应该用 `CHANNEL_TO_SKU`，但 AI 经常传 `SKU_TO_ASIN`）
- 忘记给需要 translate 的字段添加 translate

#### 2.2.3 dataComparison 问题

**复杂度来源**：
- `field` 必须写成 `数据集别名.date_id` 格式（如 `ds_xxx.date_id`）
- 日期范围同时在 `where` 和 `dataComparison` 中出现，但含义不同
- 子查询类型中，日期条件在 `where` 中通过 translate 逻辑处理

**大模型典型错误**：
- `field` 只写 `date_id`，缺少数据集别名前缀
- `where` 中的日期范围和 `dataComparison` 的日期范围搞混

#### 2.2.4 MOY/ACC/PPT 高级计算问题

**复杂度来源**：
- `comparison` 写在 `select` 字段内部，与普通字段混合
- MOY 的 `params` 结构复杂：`date`、`dim`、`type`、`cacl_type`、`aggregation`
- `params.date` 必须与 `groupBy` 中的日期格式完全一致
- `params.dim` 必须包含 `groupBy` 中除日期外的所有维度

**大模型典型错误**：
- `params.date` 格式与 `groupBy` 不一致
- `params.dim` 遗漏维度或包含日期维度
- `cacl_type` 语义混淆（`ORIGINAL` 实际上表示上期值，不是当期值）

### 2.3 客户端负担过重

当前 AI/大模型需要承担的职责：

| 职责 | 应该由谁负责 | 当前由谁负责 |
|------|-------------|-------------|
| 判断数据集类型（子查询/非子查询） | **服务端**（有 metadata） | 大模型 |
| 决定过滤条件放 where / innerWhere | **服务端**（有 inner_where_enabled） | 大模型 |
| 填充 innerWhere 数组层级 | **服务端**（知道占位符结构） | 大模型 |
| 推断 translate 枚举值 | **服务端**（有字段 metadata） | 大模型 |
| 构建 query.from（alias/permission/table） | **服务端**（已有） | 服务端 ✅ |
| 日期范围语义解析 | **服务端**（有 dateRange 即可） | 大模型 |
| MOY params.dim 推断 | **服务端**（有 groupBy 即可推断） | 大模型 |
| 选择聚合函数和字段别名 | **大模型**（有业务语义） | 大模型 ✅ |
| 构造筛选条件（field/operator/value） | **大模型**（有业务语义） | 大模型 ✅ |

---

## 三、优化方案设计

### 3.1 总体思路

**核心原则**：
> 大模型只负责"业务语义层"（查什么字段、什么条件、什么日期范围），服务端负责"技术实现层"（innerWhere 构建、translate 推断、from 构建、dataComparison 适配）。

**具体策略**：
1. **新增简化查询接口**（Simple Query API）：面向大模型的极简 JSON 格式
2. **服务端增强**：在 PHP 层将简化格式转换为完整的 Python API payload
3. **文档瘦身**：将服务端内部实现细节从 AI 参考文档中移除
4. **向后兼容**：保留现有完整 query 接口，供高级场景手动使用

### 3.2 简化查询接口设计

#### 3.2.1 请求体结构（简化版）

```json
{
  "tableId": 1104,
  "dimensions": [
    {"field": "dept_name", "alias": "dept_name"},
    {"field": "date_id", "alias": "date_id", "format": "%Y-%m"}
  ],
  "metrics": [
    {"field": "price", "aggregation": "SUM", "alias": "total_price"},
    {"field": "order_qty", "aggregation": "SUM", "alias": "total_qty"}
  ],
  "filters": [
    {"field": "platform_name", "operator": "in", "value": ["Amazon", "eBay"]},
    {"field": "country_name", "operator": "eq", "value": "美国"}
  ],
  "dateRange": {
    "field": "date_id",
    "start": "2026-04-01",
    "end": "2026-04-22"
  },
  "dataComparison": {
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  },
  "comparisons": [
    {
      "field": "price",
      "aggregation": "SUM",
      "alias": "price_mom",
      "type": "MOY",
      "moyType": "MOM_MONTH",
      "calcType": "PERCENT"
    }
  ],
  "orderBy": [
    {"field": "total_price", "desc": true}
  ],
  "limit": 20,
  "offset": 0,
  "dryRun": false
}
```

#### 3.2.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tableId` | integer | 是 | 数据集 ID |
| `dimensions` | array | 否 | 维度列表，至少一个 dimension 或 metric |
| `dimensions[].field` | string | 是 | 字段名（支持 field_name / origin_name / global_alias / verbose_name） |
| `dimensions[].alias` | string | 否 | 输出别名，省略时自动使用 global_alias |
| `dimensions[].format` | string | 否 | 日期格式（如 `%Y-%m`），用于 MOY 分组 |
| `metrics` | array | 否 | 指标列表 |
| `metrics[].field` | string | 是 | 字段名 |
| `metrics[].aggregation` | string | 否 | 聚合函数（SUM/COUNT/AVG 等），省略时自动按 metadata 推断 |
| `metrics[].alias` | string | 否 | 输出别名 |
| `filters` | array | 否 | 过滤条件（统一列表，不分 where/innerWhere） |
| `filters[].field` | string | 是 | 字段名 |
| `filters[].operator` | string | 是 | 操作符（eq/ne/gt/gte/lt/lte/in/between/like/is_null） |
| `filters[].value` | any | 否 | 过滤值（is_null 时省略） |
| `dateRange` | object | 否 | 日期范围 |
| `dateRange.field` | string | 是 | 日期字段名 |
| `dateRange.start` | string | 是 | 开始日期 |
| `dateRange.end` | string | 是 | 结束日期 |
| `dataComparison` | object | 否 | 数据对比（环比/同比） |
| `dataComparison.startDate` | string | 是 | 对比期开始 |
| `dataComparison.endDate` | string | 是 | 对比期结束 |
| `comparisons` | array | 否 | 高级计算（MOY/ACC/PPT） |
| `comparisons[].field` | string | 是 | 字段名 |
| `comparisons[].aggregation` | string | 是 | 聚合函数 |
| `comparisons[].alias` | string | 是 | 输出别名 |
| `comparisons[].type` | string | 是 | 计算类型：MOY / ACC / PPT |
| `comparisons[].moyType` | string | 否 | MOY 子类型（MOM_DAY/YOY_MONTH 等） |
| `comparisons[].calcType` | string | 否 | MOY 计算类型（ORIGINAL/COMPARE/PERCENT） |
| `orderBy` | array | 否 | 排序 |
| `orderBy[].field` | string | 是 | 字段名或别名 |
| `orderBy[].desc` | boolean | 否 | 是否降序，默认 false |
| `limit` | integer | 否 | 限制行数，默认 20 |
| `offset` | integer | 否 | 偏移量，默认 0 |
| `dryRun` | boolean | 否 | 仅生成 SQL |

#### 3.2.3 与旧版接口对比

| 维度 | 旧版（完整 query） | 新版（简化接口） |
|------|-------------------|-----------------|
| 文档阅读量 | ~3,400 行 | ~300 行 |
| innerWhere 处理 | AI 需理解子查询层级 | **服务端自动推断** |
| translate 枚举 | AI 需记住 20+ 种映射 | **服务端自动匹配** |
| from 子句 | AI 需理解结构（实际服务端构建） | **完全隐藏** |
| dataComparison.field | AI 需写成 `ds_xxx.date_id` | **自动从 dateRange 推断** |
| MOY params.dim | AI 需手动列出所有非日期维度 | **服务端自动从 dimensions 推断** |
| MOY params.date | AI 需与 groupBy 格式一致 | **自动从 dimensions[].format 推断** |
| 字段引用格式 | `ds_xxx.field_name` | **纯字段名即可**（服务端补前缀） |

### 3.3 服务端转换逻辑设计

在 `CliQueryService` 中新增 `buildSimpleQueryPayload` 方法，将简化格式转换为完整的 Python API payload：

```php
// 伪代码示意
protected function buildSimpleQueryPayload(array $simplePayload, Table $table, array $fields): array
{
    $datasetAlias = $table->dataset_alias;
    $isInnerWhereEnabled = (bool) $table->inner_where_enabled;
    
    // 1. 解析 dimensions 和 metrics，构建 select + groupBy
    $select = [];
    $groupBy = [];
    foreach ($simplePayload['dimensions'] as $dim) {
        $resolved = $this->resolveField($dim['field'], $fields);
        $alias = $dim['alias'] ?? $resolved['global_alias'];
        $expr = $dim['format'] 
            ? "DATE_FORMAT({$datasetAlias}.{$resolved['field_name']}, '{$dim['format']}')"
            : "{$datasetAlias}.{$resolved['field_name']}";
        $select[] = ['expr' => $expr, 'alias' => $alias];
        $groupBy[] = $alias;
    }
    
    foreach ($simplePayload['metrics'] as $metric) {
        $resolved = $this->resolveField($metric['field'], $fields);
        $alias = $metric['alias'] ?? $resolved['global_alias'];
        $expr = "{$datasetAlias}.{$resolved['field_name']}";
        
        // 公式字段自动展开
        if (!empty($resolved['summary_expression'])) {
            $select[] = ['expr' => $resolved['summary_expression'], 'alias' => $alias];
        } else {
            $select[] = [
                'expr' => $expr,
                'alias' => $alias,
                'aggregation' => $metric['aggregation'] ?? 'SUM'
            ];
        }
    }
    
    // 2. 处理 filters：自动分配到 where / innerWhere
    $dateRange = $simplePayload['dateRange'] ?? null;
    $filters = $simplePayload['filters'] ?? [];
    
    $whereConditions = [];
    $innerWhereConditions = [];
    
    foreach ($filters as $filter) {
        $resolved = $this->resolveField($filter['field'], $fields);
        $condition = [
            'field' => $isInnerWhereEnabled ? $resolved['origin_name'] : "{$datasetAlias}.{$resolved['field_name']}",
            'operator' => $filter['operator'],
            'value' => $filter['value'] ?? null,
        ];
        
        // 自动推断 translate
        $translate = $this->inferTranslate($resolved['field_name'], $filter['operator'], $filter['value']);
        if ($translate) {
            $condition['translate'] = $translate;
        }
        
        if ($isInnerWhereEnabled) {
            $innerWhereConditions[] = $condition;
        } else {
            $whereConditions[] = $condition;
        }
    }
    
    // 日期范围处理
    if ($dateRange) {
        $dateField = $this->resolveField($dateRange['field'], $fields);
        $dateCondition = [
            'field' => "{$datasetAlias}.{$dateField['field_name']}",
            'operator' => 'between',
            'value' => [$dateRange['start'], $dateRange['end']],
        ];
        $whereConditions[] = $dateCondition;
    }
    
    // 3. 构建 where / innerWhere
    $where = null;
    $innerWhere = null;
    
    if (!empty($whereConditions)) {
        $where = ['operator' => 'AND', 'conditions' => $whereConditions];
    }
    
    if ($isInnerWhereEnabled) {
        $innerWhere = [
            [],  // innerWhere[0]：外层子查询，通常为空
            !empty($innerWhereConditions) 
                ? ['operator' => 'AND', 'conditions' => $innerWhereConditions]
                : []
        ];
    }
    
    // 4. 处理 comparisons（MOY/ACC/PPT）
    foreach ($simplePayload['comparisons'] ?? [] as $comp) {
        $resolved = $this->resolveField($comp['field'], $fields);
        $alias = $comp['alias'];
        
        $params = [
            'aggregation' => $comp['aggregation'],
            'dim' => [],
        ];
        
        if ($comp['type'] === 'MOY') {
            // 自动推断 date 和 dim
            $dateDim = $this->findDateDimension($simplePayload['dimensions']);
            $params['date'] = $dateDim['format'] 
                ? "DATE_FORMAT({$datasetAlias}.{$dateDim['field']}, '{$dateDim['format']}')"
                : $dateDim['alias'];
            $params['dim'] = array_values(array_filter(
                array_map(fn($d) => $d['alias'] ?? $this->resolveField($d['field'], $fields)['global_alias'], 
                $simplePayload['dimensions']),
                fn($alias) => $alias !== $dateDim['alias']
            ));
            $params['type'] = $comp['moyType'];
            $params['cacl_type'] = $comp['calcType'];
        }
        
        $select[] = [
            'expr' => "{$datasetAlias}.{$resolved['field_name']}",
            'alias' => $alias,
            'comparison' => $comp['type'],
            'params' => $params,
        ];
    }
    
    // 5. 构建完整 query
    $query = [
        'select' => $select,
        'groupBy' => $groupBy,
        'orderBy' => $this->buildOrderBy($simplePayload['orderBy'] ?? [], $select),
        'limit' => $simplePayload['limit'] ?? 20,
        'offset' => $simplePayload['offset'] ?? 0,
    ];
    
    if ($where) {
        $query['where'] = $where;
    }
    if ($innerWhere) {
        $query['innerWhere'] = $innerWhere;
    }
    
    // 6. 构建最终 payload
    $result = ['query' => $query];
    
    if (!empty($simplePayload['dataComparison'])) {
        $result['dataComparison'] = [
            'switch' => true,
            'field' => "{$datasetAlias}.{$dateField['field_name']}",
            'startDate' => $simplePayload['dataComparison']['startDate'],
            'endDate' => $simplePayload['dataComparison']['endDate'],
        ];
    }
    
    if (!empty($simplePayload['dryRun'])) {
        $result['dryRun'] = true;
    }
    
    return $result;
}
```

### 3.4 客户端（opscli）适配

#### 3.4.1 新增简化查询命令

```bash
# 简化查询命令（面向大模型/AI）
opscli query simple \
  --table-id 1104 \
  --dimension dept_name \
  --dimension date_id --dim-format "%Y-%m" \
  --metric price:sum:total_price \
  --metric order_qty:sum:total_qty \
  --filter "platform_name|in|[\"Amazon\",\"eBay\"]" \
  --date-range "date_id,2026-04-01,2026-04-22" \
  --data-comparison "2026-03-01,2026-03-22" \
  --moy "price:sum:price_mom_percent:MOM_MONTH:PERCENT" \
  --order-by total_price:desc \
  --limit 20 \
  --run --pretty
```

#### 3.4.2 `QueryManager` 新增方法

```python
class QueryManager:
    def build_simple(self, *, table_id, dimensions, metrics, filters, 
                     date_range, data_comparison, comparisons, ...) -> dict:
        """构造简化查询 payload，由服务端完成复杂结构转换。"""
        ...
```

### 3.5 文档瘦身方案

#### 3.5.1 新的 AI 参考文档结构

| 文档 | 行数目标 | 内容 |
|------|---------|------|
| `simple-query-guide.md`（新增） | ~300 行 | 简化接口字段说明、常见查询示例、错误处理 |
| `query-patterns.md`（保留精简版） | ~150 行 | dataComparison / MOY / ACC / PPT 简化声明方式 |
| `cli.md`（精简） | ~400 行 | CLI 命令参考、认证流程、工作流示例 |
| `mcp.md`（精简） | ~350 行 | MCP Tool 参考、认证流程、工作流示例 |
| **合计** | **~1,200 行** | 较原来减少 **65%** |

#### 3.5.2 从 AI 文档中移除的内容

以下内容移入服务端开发文档（不对 AI 暴露）：
- `innerWhere` 层级映射原理和详细结构
- `translate` 完整枚举表（20+ 种映射关系）
- 权限占位符替换原理和完整权限字段枚举表
- 子查询类型判断方法（PHP 伪代码）
- `from` 子句的详细结构说明（因为简化接口完全隐藏 from）
- 交叉表/透视表多次查询的 PHP 层处理逻辑
- 完整的请求体完整结构参考（旧版）
- 详细的 SQL 生成原理（如 dataComparison 的 SQL 改写示意）

#### 3.5.3 新的 `simple-query-guide.md` 核心内容

```markdown
# 简化查询接口指南（AI 参考版）

## 核心原则
大模型只需提供业务语义参数，服务端自动处理技术实现细节。

## 请求体结构
```json
{
  "tableId": 1104,
  "dimensions": [{"field": "dept_name"}],
  "metrics": [{"field": "price", "aggregation": "SUM", "alias": "total_price"}],
  "filters": [{"field": "platform_name", "operator": "in", "value": ["Amazon"]}],
  "dateRange": {"field": "date_id", "start": "2026-04-01", "end": "2026-04-22"},
  "dataComparison": {"startDate": "2026-03-01", "endDate": "2026-03-22"},
  "comparisons": [{"field": "price", "type": "MOY", "moyType": "MOM_MONTH", "calcType": "PERCENT"}],
  "orderBy": [{"field": "total_price", "desc": true}],
  "limit": 20
}
```

## 字段说明
（仅列出简化接口的字段，见 3.2.2 节）

## 常见查询示例
1. 普通聚合查询
2. 带数据对比的查询
3. MOY 月环比趋势查询
4. ACC 累加查询
5. PPT 占比查询

## 错误处理
（仅列出简化接口常见错误码）
```

### 3.6 向后兼容性

- 现有 `/v1/data-metrics/cli-query` 接口保持不变，完整 query payload 继续支持
- 新增 `/v1/data-metrics/cli-query/simple` 接口接收简化格式
- CLI 保留现有 `query build` / `query run` 命令
- 新增 `query simple` 命令使用简化接口
- SKILL.md 中同时保留两种模式的说明，但默认推荐简化模式

---

## 四、实施计划

### Phase 1：服务端增强（PHP）
1. 在 `CliQueryApiController` 新增 `simpleQuery` 方法
2. 在 `CliQueryService` 或新增 `SimpleQueryBuilder` 中实现简化格式到完整格式的转换
3. 实现字段解析（`resolveField`）：支持 field_name / origin_name / global_alias / verbose_name
4. 实现 translate 自动推断
5. 实现 innerWhere 自动分配
6. 实现 dataComparison 自动适配
7. 实现 comparisons（MOY/ACC/PPT）的 params 自动构建
8. 编写单元测试

### Phase 2：客户端适配（opscli Python）
1. `QueryClient` 新增 `cli_simple_query` 方法
2. `QueryManager` 新增 `build_simple` / `build_simple_and_run` 方法
3. `commands/cli.py` 新增 `simple` 子命令
4. 更新 `opscli query` 帮助信息

### Phase 3：文档重构
1. 编写 `simple-query-guide.md`
2. 精简 `cli.md`、`mcp.md`
3. 将服务端技术细节移入独立开发文档
4. 更新 `SKILL.md` 推荐阅读入口

### Phase 4：SKILL 适配
1. 更新 `ops-dataset-query` SKILL.md，默认推荐简化接口
2. 更新 MCP Tool 定义（如有需要）
3. 测试完整工作流

---

## 五、预期收益

| 指标 | 现状 | 优化后 | 提升 |
|------|------|--------|------|
| AI 参考文档总行数 | ~3,442 行 | ~1,200 行 | **减少 65%** |
| 大模型构建查询所需知识 | innerWhere/translate/from/权限等 | 仅业务字段和条件 | **大幅减少** |
| innerWhere 构建失败率 | 高（大模型易混淆层级和字段前缀） | **0%**（服务端处理） | **消除** |
| translate 错误率 | 高（20+ 种枚举易选错） | **0%**（服务端自动推断） | **消除** |
| MOY params 错误率 | 中（dim/date 格式易出错） | **大幅降低**（服务端自动推断） | **显著降低** |
| dataComparison.field 错误率 | 中（易漏数据集别名前缀） | **0%**（自动从 dateRange 推断） | **消除** |
| 新数据集接入成本 | 高（需要理解 inner_where_enabled） | 低（统一简化接口） | **大幅降低** |

---

## 六、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 服务端自动推断 translate 可能不够精确 | 中 | 基于 `TableField` metadata 构建 translate 推断规则表，保留手动覆盖能力 |
| 简化接口无法满足所有边缘场景 | 低 | 保留完整 query 接口作为兜底，边缘场景继续手动构造 |
| 现有用户习惯完整 query 接口 | 低 | 完整接口继续支持，不强制迁移；SKILL 文档默认推荐简化接口 |
| 服务端转换逻辑复杂，引入新 bug | 中 | 编写完整单元测试覆盖各种数据集类型、filters 组合、comparisons 场景 |
| 字段解析歧义（同名不同数据集） | 低 | 简化接口要求显式传 `tableId`，字段解析限定在目标数据集内 |

---

## 七、结论

当前数据查询服务的核心痛点是：**AI/大模型承担了过多本应由服务端处理的技术实现细节**（innerWhere 层级映射、translate 枚举推断、from 子句构建等），导致文档体量过大、查询构建失败率高。

本方案通过**新增简化查询接口**，将技术实现层下沉到服务端，让大模型只需关注业务语义层，预期可：
1. 将 AI 参考文档体量减少 **65%**
2. 彻底消除 innerWhere 和 translate 相关的构建错误
3. 显著降低 MOY/ACC/PPT 和 dataComparison 的构建错误率
4. 保持向后兼容，不影响现有完整 query 接口的使用

**建议优先实施 Phase 1（服务端增强）和 Phase 3（文档重构），这两个阶段不依赖客户端改动即可让通过 HTTP 直接调用的场景受益。**
