# opscli 数据查询服务优化方案 v2（深度分析版）

> 版本：v2.0 | 日期：2026-05-06 | 状态：待确认
> 本方案基于对 `data-query-service-dev-guide.md`（1,173 行）、`query-patterns.md`（225 行）等完整文档的深度分析后重构。

---

## 一、深度分析：原始设计的核心语义

### 1.1 comparison 的本质位置

通过对文档第八章（SELECT 字段开发规范）的深度阅读，发现 **`comparison`（MOY/ACC/PPT）在原始设计中是 `select` 字段的一个属性**，与 `expr`、`alias`、`aggregation` 并列：

```json
{
  "expr": "ds_xxx.price",
  "alias": "f_692e9ad694bcd_3240",
  "comparison": "MOY",
  "params": { ... }
}
```

**关键语义**：
- `comparison` 描述的是**"这个字段如何被计算"**，它不是独立的查询维度，而是 select 字段的**计算方式修饰符**
- MOY/ACC/PPT 本质上都是**"带高级计算的指标字段"**，它们仍然参与 select 输出、可以被 groupBy 排除、可以被 orderBy 引用
- `params.aggregation` 才是真正的聚合函数（如 SUM），而 `expr` 只是基础字段名

**因此，在简化接口中，`comparison` 必须作为 `metric` 的可选属性，而不是独立的顶层 `comparisons` 数组。**

### 1.2 MOY 的展开机制

原始 payload 中，MOY 需要**为同一个基础字段写 3 条 select 项**，分别对应 3 种 `cacl_type`：

```json
// 同一个 price 字段，需要写 3 次
{"expr": "ds_xxx.price", "alias": "price_prev", "comparison": "MOY", "params": {"cacl_type": "ORIGINAL", ...}},
{"expr": "ds_xxx.price", "alias": "price_diff", "comparison": "MOY", "params": {"cacl_type": "COMPARE", ...}},
{"expr": "ds_xxx.price", "alias": "price_pct",  "comparison": "MOY", "params": {"cacl_type": "PERCENT", ...}}
```

**AI 的痛点**：
- 需要理解 `cacl_type` 的反向语义（`ORIGINAL` = 上期值，不是当期值）
- 需要手动写 3 遍几乎相同的结构
- 需要确保 3 个 `params` 中 `date/dim/type/aggregation` 完全一致

**简化方案**：AI 只需声明一次 MOY，服务端自动展开为 3 个 select 项。

### 1.3 ACC / PPT 的独立性与 MOY 的差异

| 维度 | MOY | ACC | PPT |
|------|-----|-----|-----|
| 输出字段数 | **3 个**（需手动声明 3 次） | 1 个 | 1 个 |
| `params.date` | 必填 | 不需要 | 不需要 |
| `params.dim` | 必填（非日期维度列表） | 固定 `[]` | 固定 `[]` |
| `params.type` | 必填（枚举值） | 不需要 | 不需要 |
| `params.cacl_type` | 必填 | 不需要 | 不需要 |
| groupBy 要求 | **必须含日期字段** | 无特殊要求 | 无特殊要求 |

**结论**：
- ACC/PPT 可以像普通 metric 一样声明（只需加一个 `comparison` 属性）
- MOY 需要特殊处理：AI 声明一次 → 服务端自动展开为 3 个输出字段

### 1.4 where / innerWhere 的职责分离

通过文档第三章和第十章的深度分析：

```
inner_where_enabled = true（子查询类型）
├── innerWhere[0]  →  对应 {where_sub_placeholder_1}，通常传空 []
├── innerWhere[1]  →  对应 {and_sub_placeholder_2}，放业务维度过滤条件
└── where          →  放日期范围条件（translate 逻辑处理）

inner_where_enabled = false（非子查询类型）
└── where          →  放所有过滤条件（维度 + 日期）
```

**关键发现**：
- **日期条件始终放在外层 `where`**，无论是否子查询类型（10.3 节明确说明）
- `innerWhere` 中**不放**日期条件
- 子查询类型的日期通过外层 `where` 的 translate 逻辑注入，Python 服务自动转换为内层日期过滤

**简化接口设计验证**：
- `filters` 中的时间范围条件（`between`）统一放入外层 `where` ✅
- `filters` 中的业务维度条件根据 `inner_where_enabled` 自动分配到 `where` 或 `innerWhere[1]` ✅

### 1.5 translate 的推断逻辑

document 5.3 节列出 20+ 种 translate 映射：

| 过滤字段 | translate 枚举值 | 含义 |
|----------|-----------------|------|
| `platform_name` | `PLATFORM_TO_SKU` | 平台 → 公司 SKU |
| `channel_name` | `CHANNEL_TO_SKU` | 渠道 → 公司 SKU |
| `ed_sku` | `SKU_TO_ASIN` | 公司 SKU → ASIN |
| `asin` | `ASIN_TO_SKU` | ASIN → 公司 SKU |

**关键发现**：
- translate 的映射关系是**字段名 → 枚举值**的固定映射
- 某些字段有多个可选 translate（如 `ed_sku` 可以是 `SKU_TO_ASIN` 或 `SKU_TO_MSKU`）
- translate 只在 `in` / `eq` 等值匹配操作符时有意义

**简化方案**：服务端根据 `dm_select_column_relations` 表的实时数据动态构建 `translate`。AI 不传 `translate`，后端查询该表获取 `source_column_name`，再映射为对应的 `translate` 枚举值。查不到记录时，该条件不传 `translate` 字段。

### 1.6 dataComparison 与 MOY 的本质区别

| 对比维度 | dataComparison | MOY |
|----------|---------------|-----|
| 计算方式 | 条件聚合（一次 SQL 中分别聚合当期/对比期） | 窗口函数 LAG() |
| 适用场景 | 汇总对比（如本月 vs 上月同期汇总） | 趋势分析（如按月分组展示各月及上月值） |
| 字段裂变 | 所有 metric 自动裂变为 4 个 | 只有声明了 MOY 的字段才会产生输出 |
| 日期要求 | `where` 覆盖当期，`dataComparison` 提供对比期 | `where` 必须覆盖**当期 + 对比期**的完整历史 |
| groupBy | 普通维度分组 | **必须包含日期维度** |

**结论**：两者是独立的高级特性，可以共存，但通常不会同时使用。简化接口中应分别提供 `dataComparison` 和 `metrics[].comparison` 两种声明方式。

---

## 二、优化后的简化接口设计

### 2.1 请求体结构

```json
{
  "tableId": 1104,

  "dimensions": [
    {
      "field": "dept_name",
      "alias": "f_ZPKzwnJBRKWaIE2E"
    },
    {
      "field": "date_id",
      "alias": "f_5zYACh3U2XSKPjFc",
      "format": "%Y-%m"
    }
  ],

  "metrics": [
    {
      "field": "price",
      "aggregation": "SUM",
      "alias": "f_8rq7HbE5oJm3vL9w"
    },
    {
      "field": "order_qty",
      "aggregation": "SUM",
      "alias": "f_2xP9nQ4rKtYwZcAe"
    },
    {
      "field": "price",
      "aggregation": "SUM",
      "alias": "f_MoYmCmPaRtIsOn",
      "comparison": "MOY",
      "moyType": "MOM_MONTH"
    }
  ],

  "filters": [
    {
      "field": "platform_name",
      "operator": "in",
      "value": ["Amazon", "eBay"]
    },
    {
      "field": "country_name",
      "operator": "=",
      "value": "美国"
    },
    {
      "field": "date_id",
      "operator": "between",
      "value": ["2026-04-01", "2026-04-22"]
    }
  ],

  "dataComparison": {
    "field": "date_id",
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  },

  "orderBy": [
    {"field": "f_8rq7HbE5oJm3vL9w", "desc": true}
  ],

  "limit": 20,
  "offset": 0,
  "dryRun": false
}
```

### 2.2 字段详细说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tableId` | integer | 是 | 数据集 ID |
| `dimensions` | array | 否 | 维度列表（至少一个 dimension 或 metric） |
| `dimensions[].field` | string | 是 | **field_name**（如 `dept_name`），服务端自动拼接 `dataset_alias.` 前缀 |
| `dimensions[].alias` | string | **是** | **global_alias**，格式为 `f_` + 随机字符串（如 `f_ZPKzwnJBRKWaIE2E`） |
| `dimensions[].format` | string | 否 | 日期格式（如 `%Y-%m`），用于 MOY 分组和日期维度展示 |
| `metrics` | array | 否 | 指标列表 |
| `metrics[].field` | string | 是 | **field_name**，服务端自动拼接 `dataset_alias.` 前缀 |
| `metrics[].aggregation` | string | 否 | 聚合函数（SUM/COUNT/AVG 等），省略时服务端按 metadata 自动推断 |
| `metrics[].alias` | string | **是** | **global_alias**，格式为 `f_` + 随机字符串 |
| `metrics[].comparison` | string | 否 | 高级计算：`MOY` / `ACC` / `PPT` |
| `metrics[].moyType` | string | 否 | MOY 子类型：`MOM_DAY` / `MOM_MONTH` / `MOM_WEEK` / `YOY_MONTH` / `YOY_YEAR` 等 |
| `filters` | array | 否 | 过滤条件（扁平列表，默认 AND 连接） |
| `filters[].field` | string | 是 | **field_name**，服务端自动拼接 `dataset_alias.` 前缀 |
| `filters[].operator` | string | 是 | 操作符，支持符号（`=`/`>=`/`<=`/`>`/`<`）和语义（`eq`/`in`/`between`/`like`/`is_null`） |
| `filters[].value` | any | 否 | 过滤值（`is_null` 时省略；`between` 传 `[start, end]`） |
| `dataComparison` | object | 否 | 数据对比（环比/同比） |
| `dataComparison.field` | string | 是 | **field_name**，服务端自动拼接 `dataset_alias.` 前缀 |
| `dataComparison.startDate` | string | 是 | 对比期开始 |
| `dataComparison.endDate` | string | 是 | 对比期结束 |
| `orderBy` | array | 否 | 排序 |
| `orderBy[].field` | string | 是 | **global_alias**（维度/指标声明的 `alias` 值） |
| `orderBy[].desc` | boolean | 否 | 是否降序，默认 false |
| `limit` | integer | 否 | 返回行数，默认 20 |
| `offset` | integer | 否 | 偏移量，默认 0 |
| `dryRun` | boolean | 否 | 仅生成 SQL，不执行 |

### 2.3 与上一版的关键改进

| 改进点 | 上一版（v1） | 当前版（v2） | 理由 |
|--------|------------|------------|------|
| comparison 位置 | 独立 `comparisons` 数组 | **`metrics[].comparison` 属性** | 符合原始语义：comparison 是 select 字段的计算方式修饰符，不是独立查询维度 |
| MOY 声明方式 | 需传 `calcType`，一行一个输出 | **一行声明，服务端自动展开为 3 个字段** | AI 无需理解 `ORIGINAL`/`COMPARE`/`PERCENT` 的反向语义 |
| MOY alias | 需手动为每个 calcType 指定 alias | **基于传入的 `alias` 自动生成**（`{alias}_prev`/`{alias}_diff`/`{alias}_pct`） | 减少 AI 认知负担 |
| ACC/PPT 声明 | 在 comparisons 数组中声明 | **在 metrics 中加 `comparison` 属性** | 与普通 metric 声明方式一致，语义更自然 |
| 操作符支持 | 仅语义操作符（eq/gte/in） | **同时支持符号（`=`/`>=`/`<=`）和语义操作符** | AI 更自然地使用 `=` 而不是 `eq` |

---

## 三、服务端转换逻辑详细设计

### 3.1 核心转换流程

```php
function buildSimpleQueryPayload(array $simple, Table $table, array $fields): array
{
    $datasetAlias = $table->dataset_alias;
    $isInnerWhere = (bool) $table->inner_where_enabled;

    // Step 1: 构建 select + groupBy
    $select = [];
    $groupBy = [];

    // 1.1 处理 dimensions
    foreach ($simple['dimensions'] as $dim) {
        $resolved = resolveField($dim['field'], $fields);
        $alias = $dim['alias'] ?? $resolved['global_alias'];
        $expr = $dim['format']
            ? "DATE_FORMAT({$datasetAlias}.{$resolved['field_name']}, '{$dim['format']}')"
            : "{$datasetAlias}.{$resolved['field_name']}";
        $select[] = ['expr' => $expr, 'alias' => $alias];
        $groupBy[] = $alias;
    }

    // 1.2 处理 metrics
    foreach ($simple['metrics'] as $metric) {
        $resolved = resolveField($metric['field'], $fields);
        $baseAlias = $metric['alias'];  // alias 必填，使用传入的 global_alias

        if (!empty($metric['comparison'])) {
            $select = array_merge($select, buildComparisonSelect($metric, $resolved, $datasetAlias, $simple['dimensions']));
        } elseif (!empty($resolved['summary_expression'])) {
            // 公式字段
            $select[] = ['expr' => $resolved['summary_expression'], 'alias' => $baseAlias];
        } else {
            // 普通聚合字段
            $select[] = [
                'expr' => "{$datasetAlias}.{$resolved['field_name']}",
                'alias' => $baseAlias,
                'aggregation' => $metric['aggregation'] ?? 'SUM'
            ];
        }
    }

    // Step 2: 处理 filters → where / innerWhere
    $whereConditions = [];
    $innerWhereConditions = [];

    foreach ($simple['filters'] as $filter) {
        $resolved = resolveField($filter['field'], $fields);

        // 构建条件字段：
        // - where 中保持 origin_name（ds_xxx.platform_name）
        // - innerWhere 中替换为 bc.platform_name（内层原始表别名）
        $conditionField = $isInnerWhere
            ? 'bc.' . $resolved['field_name']
            : $filter['field'];  // 直接使用 AI 传入的 origin_name

        $condition = [
            'field' => $conditionField,
            'operator' => standardizeOperator($filter['operator']),
            'value' => $filter['value'] ?? null,
        ];

        // 动态构建 translate：只有从 dm_select_column_relations 查到数据时才添加 translate
        $translate = buildTranslate($datasetAlias, $resolved['field_name'], $filter['operator']);
        if ($translate) {
            $condition['translate'] = $translate;
        }

        if ($isInnerWhere) {
            $innerWhereConditions[] = $condition;
        } else {
            $whereConditions[] = $condition;
        }
    }

    // Step 3: 构建 where / innerWhere 结构
    $query = [
        'select' => $select,
        'groupBy' => $groupBy,
        'orderBy' => buildOrderBy($simple['orderBy'] ?? [], $select),
        'limit' => $simple['limit'] ?? 20,
        'offset' => $simple['offset'] ?? 0,
    ];

    if (!empty($whereConditions)) {
        $query['where'] = ['operator' => 'AND', 'conditions' => $whereConditions];
    }

    if ($isInnerWhere) {
        $query['innerWhere'] = [
            [],  // innerWhere[0]：外层子查询，通常为空
            !empty($innerWhereConditions)
                ? ['operator' => 'AND', 'conditions' => $innerWhereConditions]
                : []
        ];
    }

    // Step 4: 构建最终 payload
    $result = ['query' => $query];

    // dataComparison
    if (!empty($simple['dataComparison'])) {
        $dateField = resolveField($simple['dataComparison']['field'], $fields);
        $result['dataComparison'] = [
            'switch' => true,
            'field' => "{$datasetAlias}.{$dateField['field_name']}",
            'startDate' => $simple['dataComparison']['startDate'],
            'endDate' => $simple['dataComparison']['endDate'],
        ];
    }

    if (!empty($simple['dryRun'])) {
        $result['dryRun'] = true;
    }

    return $result;
}
```

### 3.2 MOY 自动展开逻辑

```php
function buildComparisonSelect(array $metric, array $resolved, string $datasetAlias, array $dimensions): array
{
    $comparison = strtoupper($metric['comparison']);
    $baseAlias = $metric['alias'];  // alias 必填，使用传入的 global_alias
    $aggregation = $metric['aggregation'] ?? 'SUM';

    if ($comparison === 'MOY') {
        // 自动查找日期维度
        $dateDim = findDateDimension($dimensions);
        $nonDateDims = buildNonDateDims($dimensions);

        $dateExpr = $dateDim['format']
            ? "DATE_FORMAT({$datasetAlias}.{$dateDim['field_name']}, '{$dateDim['format']}')"
            : "{$datasetAlias}.{$dateDim['field_name']}";

        $moyType = $metric['moyType'] ?? 'MOM_MONTH';

        return [
            [ // ORIGINAL → 上期值
                'expr' => "{$datasetAlias}.{$resolved['field_name']}",
                'alias' => "{$baseAlias}_prev",
                'comparison' => 'MOY',
                'params' => [
                    'date' => $dateExpr,
                    'dim' => $nonDateDims,
                    'type' => $moyType,
                    'cacl_type' => 'ORIGINAL',
                    'aggregation' => $aggregation,
                ]
            ],
            [ // COMPARE → 差值
                'expr' => "{$datasetAlias}.{$resolved['field_name']}",
                'alias' => "{$baseAlias}_diff",
                'comparison' => 'MOY',
                'params' => [
                    'date' => $dateExpr,
                    'dim' => $nonDateDims,
                    'type' => $moyType,
                    'cacl_type' => 'COMPARE',
                    'aggregation' => $aggregation,
                ]
            ],
            [ // PERCENT → 变化率
                'expr' => "{$datasetAlias}.{$resolved['field_name']}",
                'alias' => "{$baseAlias}_pct",
                'comparison' => 'MOY',
                'params' => [
                    'date' => $dateExpr,
                    'dim' => $nonDateDims,
                    'type' => $moyType,
                    'cacl_type' => 'PERCENT',
                    'aggregation' => $aggregation,
                ]
            ],
        ];
    }

    if ($comparison === 'ACC') {
        return [[
            'expr' => "{$datasetAlias}.{$resolved['field_name']}",
            'alias' => "{$baseAlias}_acc",
            'comparison' => 'ACC',
            'params' => ['dim' => [], 'aggregation' => $aggregation]
        ]];
    }

    if ($comparison === 'PPT') {
        return [[
            'expr' => "{$datasetAlias}.{$resolved['field_name']}",
            'alias' => "{$baseAlias}_ppt",
            'comparison' => 'PPT',
            'params' => ['dim' => [], 'aggregation' => $aggregation]
        ]];
    }

    throw new InvalidArgumentException("不支持的高级计算类型: {$comparison}");
}
```

### 3.3 translate 构建规则（基于 `dm_select_column_relations` 表查询）

> ⚠️ **重要**：`translate` 不是硬编码映射，而是根据 `dm_select_column_relations` 表的实时数据动态构建。

**表结构**：
```sql
CREATE TABLE dm_select_column_relations (
    id                 bigint unsigned auto_increment primary key,
    column_name        varchar(255)         not null comment '列名',
    verbose_name       varchar(1024)        null comment '显示名称',
    dataset_alias      varchar(255)         null comment '数据集dataset_alias',
    source_column_name varchar(255)         null comment '需要转换的字段名（源字段）',
    disable            tinyint(1) default 0 not null comment '是否禁用:0启用,1禁用',
    -- ... 其他字段
);
```

**构建逻辑**：
1. 根据当前查询的 `dataset_alias` + `column_name` 查询 `dm_select_column_relations`
2. 获取 `source_column_name`（即该字段需要被翻译成的目标字段）
3. 根据 `column_name → source_column_name` 的组合，映射为对应的 `translate` 枚举值

```php
function buildTranslate(string $datasetAlias, string $columnName, string $operator): ?string
{
    // translate 只在值匹配操作符时有效
    if (!in_array($operator, ['eq', 'in', '=', '=='])) {
        return null;
    }

    // 1. 查询 dm_select_column_relations
    $relation = \DB::connection('ops_metrics')
        ->table('dm_select_column_relations')
        ->where('dataset_alias', $datasetAlias)
        ->where('column_name', $columnName)
        ->where('disable', 0)
        ->first();

    if (!$relation || empty($relation->source_column_name)) {
        return null;
    }

    $sourceColumn = $relation->source_column_name;

    // 2. 根据 column_name → source_column_name 映射为 translate 枚举值
    return resolveTranslateEnum($columnName, $sourceColumn);
}

/**
 * 字段名 → translate 枚举值映射表
 * 键：column_name，值：source_column_name → translate_enum
 */
function resolveTranslateEnum(string $columnName, string $sourceColumn): ?string
{
    $map = [
        'platform_name' => [
            'sku'  => 'PLATFORM_TO_SKU',
        ],
        'country_name' => [
            'sku'  => 'COUNTRY_TO_SKU',
        ],
        'channel_name' => [
            'sku'  => 'CHANNEL_TO_SKU',
        ],
        'team_name' => [
            'sku'  => 'TEAM_TO_SKU',
        ],
        'team_username' => [
            'sku'  => 'TEAM_USER_TO_SKU',
        ],
        'develop_username' => [
            'sku'  => 'DEVELOP_USER_TO_SKU',
        ],
        'asin' => [
            'sku'  => 'ASIN_TO_SKU',
            'mku'  => 'ASIN_TO_MSKU',   // source_column_name 为 mku
        ],
        'ed_sku' => [
            'asin' => 'SKU_TO_ASIN',
            'mku'  => 'SKU_TO_MSKU',
        ],
        'sell_sku' => [
            'asin' => 'MSKU_TO_ASIN',
            'sku'  => 'MSKU_TO_SKU',
        ],
        'product_name' => [
            'asin' => 'PRODUCT_NAME_TO_ASIN',
            'mku'  => 'PRODUCT_NAME_TO_MSKU',
        ],
        'model' => [
            'asin' => 'MODEL_TO_ASIN',
            'mku'  => 'MODEL_TO_MSKU',
        ],
    ];

    return $map[$columnName][$sourceColumn] ?? null;
}
```

**说明**：
- `source_column_name` 的值（如 `sku` / `asin` / `mku`）来自 `dm_select_column_relations` 表的实时数据
- 如果表中未找到对应记录，或 `source_column_name` 为空，则不添加 `translate`
- 如果 `source_column_name` 的值在映射表中无对应枚举，返回 `null`（走普通过滤）

### 3.4 操作符标准化映射

```php
$operatorMap = [
    '=' => 'eq', '==' => 'eq',
    '!=' => 'neq', '<>' => 'neq',
    '>' => 'gt', '>=' => 'gte',
    '<' => 'lt', '<=' => 'lte',
    'contains' => 'like',
];
```

---

## 四、AI 认知负担对比

### 4.1 原始完整接口 vs 简化接口

| 概念 | 原始接口 | 简化接口 | 变化 |
|------|----------|----------|------|
| `innerWhere` 层级映射 | **必须理解** `innerWhere[0]`→外层子查询、`innerWhere[1]`→内层原始表 | **完全隐藏** | 消除 |
| `innerWhere` 字段前缀 | **必须区分** `bc.` vs `ds_xxx.` | **完全隐藏** | 消除 |
| `translate` 枚举 | **必须记住** 20+ 种映射关系 | **完全隐藏** | 消除 |
| `query.from` 结构 | **必须理解** table/alias/database/permission | **完全隐藏** | 消除 |
| `dataComparison.field` | **必须写成** `ds_xxx.date_id` | **AI 直接传 `field_name`** | 消除 |
| MOY `params.date` | **必须与 groupBy 日期格式完全一致** | **自动从 dimensions[].format 推断** | 消除 |
| MOY `params.dim` | **必须手动列出** groupBy 中所有非日期维度 | **自动从 dimensions 推断** | 消除 |
| MOY `cacl_type` | **必须理解** `ORIGINAL`=上期值（反向语义） | **完全隐藏**，服务端自动生成 3 个字段 | 消除 |
| `comparison` 声明位置 | `select` 字段属性（与 `expr`/`alias` 并列） | **`metrics[].comparison` 属性** | 语义对齐 |
| 字段引用格式 | **必须写** `ds_xxx.field_name` | **AI 直接传 `field_name`** | 消除 |
| 公式字段 | **必须判断** has_formula_config，选择 summary_expression | **自动展开**（服务端按 metadata 处理） | 简化 |

### 4.2 AI 只需理解的概念（简化接口）

```
tableId          → 数据集 ID
dimensions       → 分组维度
metrics          → 聚合指标（comparison 是可选属性）
filters          → 过滤条件（origin_name + 操作符 + 值，时间范围也用 between）
orderBy          → 排序
limit/offset     → 分页
dataComparison   → 环比/同比（指定日期字段 + 对比期日期）
```

**共 7 个核心概念**，且都是**业务语义概念**，不涉及任何服务端实现细节。

---

## 五、文档瘦身方案

### 5.1 新的 AI 参考文档结构

| 文档 | 行数目标 | 核心内容 |
|------|---------|----------|
| `simple-query-guide.md`（新增） | **~250 行** | 简化接口字段说明、8 个核心概念、6 个常见查询示例、错误码 |
| `query-patterns.md`（精简版） | **~100 行** | dataComparison / MOY / ACC / PPT 的简化声明方式 |
| `cli.md`（精简） | ~350 行 | CLI 命令参考、认证流程、工作流示例 |
| `mcp.md`（精简） | ~300 行 | MCP Tool 参考、认证流程、工作流示例 |
| **合计** | **~1,000 行** | 较原来减少 **~71%** |

### 5.2 从 AI 文档中移除的内容

以下内容移入**服务端开发内部文档**（不对 AI 暴露）：

1. **`innerWhere` 层级映射原理和详细结构**（第三章 3.3、第十章 10.2）
2. **`translate` 完整枚举表**（20+ 种映射关系，第五章 5.3）
3. **权限占位符替换原理和完整权限字段枚举表**（第四章 4.2-4.4）
4. **子查询类型判断方法**（第十章 10.2 PHP 伪代码）
5. **`from` 子句的详细结构说明**（第二章 2.1、第三章）
6. **交叉表/透视表多次查询的 PHP 层处理逻辑**（第七章）
7. **完整的请求体完整结构参考**（旧版，第二章 2.1）
8. **SQL 生成原理**（如 dataComparison 的 SQL 改写示意，第六章 6.1）
9. **`cacl_type` 语义说明**（`ORIGINAL`/`COMPARE`/`PERCENT`，query-patterns.md）
10. **alias 命名规范**（第十章 10.1，系统生成 alias，AI 不需要关心）

### 5.3 新的 `simple-query-guide.md` 大纲

```markdown
# 简化查询接口指南（AI 参考版）

## 核心原则
大模型只需提供业务语义参数，服务端自动处理技术实现细节。

## 请求体结构
（JSON 示例 + 字段表格，~80 行）

## 核心概念说明
- dimensions：分组维度
- metrics：聚合指标
- filters：过滤条件
- filters：过滤条件（含时间范围，用 between 操作符）
- dataComparison：数据对比
- comparison：高级计算（MOY/ACC/PPT）
- orderBy：排序
- limit/offset：分页

## 常见查询示例
1. 普通聚合查询
2. 带数据对比的查询（dataComparison）
3. MOY 月环比趋势查询
4. ACC 累加查询
5. PPT 占比查询
6. 带过滤条件的查询

## 操作符速查
| 符号 | 语义 |
|------|------|
| = / == | eq |
| != / <> | ne |
| > | gt |
| >= | gte |
| < | lt |
| <= | lte |
| in | in |
| between | between |
| like | like |

## 错误处理
（常见错误码，~30 行）
```

---

## 六、向后兼容性

| 接口/命令 | 行为 |
|----------|------|
| `POST /v1/data-metrics/cli-query` | **保持不变**，完整 query payload 继续支持 |
| `POST /v1/data-metrics/cli-query/simple` | **新增**，接收简化格式 |
| `opscli query build` | **保持不变** |
| `opscli query run` | **保持不变** |
| `opscli query simple` | **新增**，使用简化接口 |
| `opscli query chart` | **保持不变** |

---

## 七、实施计划

### Phase 1：服务端增强（PHP）— 最高优先级
1. `CliQueryApiController` 新增 `simpleQuery` Action
2. 新增 `SimpleQueryBuilder` 服务类：
   - 字段解析（`resolveField`）：从 `origin_name`（`dataset_alias.field_name`）中提取 `field_name`，再匹配 metadata
   - select + groupBy 构建
   - filters → where / innerWhere 自动分配
   - filters → where / innerWhere 自动分配（含时间范围条件）
    - translate 动态构建（基于 dm_select_column_relations 表查询）
    - comparison（MOY/ACC/PPT）自动展开
    - dataComparison 自动适配
    - orderBy 自动映射到 alias
3. 编写单元测试覆盖：
    - 子查询类型 / 非子查询类型
    - 带/不带时间范围条件
   - 带/不带 dataComparison
   - MOY 自动展开（3 个字段）
    - ACC / PPT 构建
    - translate 动态构建（基于 dm_select_column_relations 表查询）

### Phase 2：客户端适配（opscli Python）
1. `QueryClient` 新增 `cli_simple_query` 方法
2. `QueryManager` 新增 `build_simple` / `build_simple_and_run` 方法
3. `commands/cli.py` 新增 `simple` 子命令

### Phase 3：文档重构
1. 编写 `simple-query-guide.md`（~250 行）
2. 精简 `cli.md` / `mcp.md`
3. 将服务端技术细节移入内部开发文档

### Phase 4：SKILL 适配
1. 更新 `ops-dataset-query` SKILL.md，默认推荐简化接口
2. 更新 MCP Tool 定义
3. 端到端测试

---

## 八、预期收益

| 指标 | 现状 | 优化后 |
|------|------|--------|
| AI 参考文档总行数 | ~3,442 行 | ~1,000 行（**减少 71%**） |
| 大模型需理解的核心概念数 | 15+（含 innerWhere/translate/from/权限等） | **7 个纯业务概念** |
| `innerWhere` 构建错误率 | 高 | **0%**（服务端处理） |
| `translate` 选择错误率 | 高（20+ 种枚举） | **0%**（服务端推断） |
| MOY `cacl_type` 误解率 | 高（`ORIGINAL` 语义反向） | **0%**（服务端自动生成） |
| MOY `params.dim/date` 错误率 | 中 | **大幅降低**（自动推断） |
| `dataComparison.field` 格式错误 | 中（易漏数据集别名前缀） | **0%**（AI 直接传 `field_name`） |
| 新数据集接入认知成本 | 高（需理解 inner_where_enabled） | 低（统一简化接口） |

---

## 九、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 服务端动态构建 translate 不够精确 | 中 | 基于 `dm_select_column_relations` 表实时查询，如表中数据缺失导致 translate 遗漏，可通过完整 query 接口手动覆盖 |
| MOY 自动生成的 alias 与业务预期不符 | 低 | 支持 `metrics[].alias` 作为基础前缀（如 `"alias": "sales"` 生成 `sales_prev`/`sales_diff`/`sales_pct`） |
| 简化接口无法满足所有边缘场景 | 低 | 完整 query 接口继续支持，边缘场景手动构造 |
| 服务端转换逻辑复杂，引入新 bug | 中 | 编写完整单元测试覆盖各种数据集类型、filters 组合、comparisons 场景 |
| 字段解析歧义（同名不同数据集） | 低 | 简化接口要求显式传 `tableId`，字段解析限定在目标数据集内 |

---

## 十、结论

通过对 `data-query-service-dev-guide.md` 等完整文档的深度分析，确认：

1. **`comparison`（MOY/ACC/PPT）本质上是 `select` 字段的计算方式修饰符**，在简化接口中应作为 `metrics` 的可选属性，而非独立的顶层数组。这与原始设计的语义完全一致。

2. **MOY 需要特殊处理**：原始接口要求为同一个基础字段写 3 遍几乎相同的结构（仅 `cacl_type` 不同），且 `cacl_type` 语义反向（`ORIGINAL` = 上期值）。简化接口中 AI 只需声明一次 MOY，服务端自动展开为 3 个输出字段，彻底消除 `cacl_type` 的认知负担。

3. **技术实现层应完全下沉到服务端**：`innerWhere` 层级映射、`translate` 动态构建（基于 `dm_select_column_relations` 表查询）、`from` 子句构建、`dataComparison.field` 前缀补全、MOY `params.dim/date` 推断等，都是服务端已有 metadata 可以自动完成的，不应让 AI 承担。

4. **简化接口将 AI 需要理解的概念从 15+ 个减少到 7 个纯业务概念**，文档体量减少 **71%**，且从根本上消除了 innerWhere、translate、cacl_type 等高失败率构造点。

**建议优先实施 Phase 1（服务端 PHP 增强）**，因为新增 `/cli-query/simple` 接口不依赖客户端改动，即可让直接 HTTP 调用的场景立即受益。
