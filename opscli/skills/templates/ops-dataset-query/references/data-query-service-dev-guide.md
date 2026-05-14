# 数据查询服务开发说明文档

> 版本：1.1 | 更新日期：2026-04-11 | 适用人员：后端开发、前端开发
>
> **v1.1 变更**：新增高级计算算法（同环比/累加/占比）、WHERE 条件 translate 翻译枚举、完整权限字段枚举表

---

## 目录

1. [概述](#一概述)
2. [请求与响应结构完整参考](#二请求与响应结构完整参考)
3. [数据集类型详解](#三数据集类型详解)
4. [权限控制机制](#四权限控制机制)
5. [WHERE 条件构建指南](#五where-条件构建指南)
6. [dataComparison 数据对比](#六datacomparison-数据对比)
7. [多次查询场景说明](#七多次查询场景说明)
8. [SELECT 字段开发规范](#八select-字段开发规范)
9. [分页与排序规范](#九分页与排序规范)
10. [开发注意事项](#十开发注意事项)

> **快速导航**：[同环比 MOY](#841-同环比moy) | [累加 ACC](#842-累加acc) | [占比 PPT](#843-占比ppt) | [translate 翻译枚举](#54-translate-条件字段翻译枚举) | [权限字段枚举](#44-权限字段完整枚举)

---

## 一、概述

### 1.1 服务定位

数据查询服务（Data Query Service）是北极星运营系统的核心数据检索层，负责将前端图表配置（如柱状图、折线图、交叉表、指标卡等）转换为结构化的 Python API 请求，并将查询结果返回给前端渲染。

PHP 层（`QueryBuilder`）承担以下职责：

- 解析图表配置，拼装 Python API 所需的请求体
- 根据图表类型决定是否发起多次查询（如交叉表的小计/总计、堆叠图的两阶段查询等）
- 合并多次查询结果，组装最终数据结构

Python 服务承担以下职责：

- 接收结构化查询请求，生成并执行 SQL
- 处理权限占位符替换
- 处理 dataComparison（数据对比）的 SQL 改写
- 返回查询结果和执行元信息

### 1.2 支持的数据源

| 数据源标识 | 说明 |
|------------|------|
| `doris_analytics` | Apache Doris 分析型数据库（主力数据源） |

数据源标识通过请求体的 `dataSource` 字段传入，Python 服务根据该值选择对应的数据库连接。

### 1.3 认证方式

Python API 支持两种认证方式（二选一）：

| 认证方式 | 请求头 | 示例 |
|----------|--------|------|
| Bearer Token | `Authorization: Bearer <token>` | `Authorization: Bearer eyJhbGci...` |
| API Key | `X-API-Key: <key>` | `X-API-Key: sk-prod-xxxxx` |

### 1.4 基础信息

| 项目 | 说明 |
|------|------|
| 基础 URL | `http://localhost:8000` |
| 核心查询端点 | `POST /api/v1/query` |
| Content-Type | `application/json` |

---

## 二、请求与响应结构完整参考

### 2.1 请求体完整结构

```json
{
  // ============ 顶层字段 ============
  "userEmail": "{userEmail}",    // 用户邮箱，用于权限控制和审计追踪（必填）
  "dataSource": "doris_analytics",         // 数据源标识符（必填）
  "dryRun": false,                         // 干运行模式：true 时仅生成 SQL 不执行，用于调试

  // ============ 核心查询配置 ============
  "query": {

    // --- FROM 子句配置 ---
    "from": {
      "table": "string",          // 表名或子查询 SQL 字符串（必填，详见第三章）
      "alias": "string",          // 数据集别名，格式通常为 ds_[随机哈希]（必填）
      "database": "string",       // 数据库名，子查询时传空字符串 ""（普通表时传库名）
      "permission": ["string"]    // 权限控制维度数组，如 ["channel_uuid","listing_uuid"]
    },

    // --- SELECT 字段配置 ---
    "select": [
      {
        "expr": "string",         // 字段表达式或完整计算表达式（必填）
        "alias": "string",        // 字段别名（必填）。仅支持英文/数字/下划线且不能以数字开头，推荐直接使用字段 metadata 中的 global_alias，不支持中文别名
        "aggregation": "string"   // 聚合函数（可选），如 SUM/COUNT/AVG/MAX/MIN/DISTINCT_COUNT
      }
    ],

    // --- JOIN 配置（可选）---
    "joins": [
      {
        "type": "LEFT",           // JOIN 类型：LEFT / RIGHT / INNER / FULL
        "table": "string",        // 被 JOIN 的表名或子查询
        "alias": "string",        // JOIN 表别名
        "on": "string"            // ON 条件表达式
      }
    ],

    // --- WHERE 外层条件（非子查询类型用此字段，子查询类型的外层日期条件也在此）---
    "where": {
      "operator": "AND",          // 逻辑操作符：AND | OR
      "conditions": [
        // 叶子节点（过滤条件）
        {
          "field": "ds_xxx.date_id",
          "operator": "between",
          "value": ["2026-03-13", "2026-04-11"]
        },
        // 逻辑节点（嵌套分组）
        {
          "operator": "OR",
          "conditions": [
            { "field": "ds_xxx.platform_name", "operator": "eq", "value": "Amazon" },
            { "field": "ds_xxx.platform_name", "operator": "eq", "value": "eBay" }
          ]
        }
      ]
    },

    // --- GROUP BY（用 alias 引用）---
    "groupBy": ["f_xxx_alias_1", "f_xxx_alias_2"],

    // --- HAVING 条件（可选）---
    "having": [
      { "field": "f_xxx_alias", "operator": "gt", "value": 0 }
    ],

    // --- ORDER BY ---
    "orderBy": [
      { "expr": "f_xxx_alias", "desc": false }   // expr 为 select 中的 alias
    ],

    // --- 分页 ---
    "limit": 20,
    "offset": 0,

    // --- 缓存控制 ---
    "cacheControl": {
      "enabled": true,       // 是否启用缓存
      "forceRefresh": false, // 是否强制刷新缓存
      "ttl": 300             // 缓存时间（秒）
    }
  },

  // ============ 数据对比配置（同/环比，可选）============
  "dataComparison": {
    "switch": true,                                // true 开启对比
    "field": "ds_xxx.date_id",                    // 日期字段（数据集别名.date_id）
    "startDate": "2026-02-11",                    // 对比期开始日期
    "endDate": "2026-03-12"                       // 对比期结束日期
  }
}
```

### 2.2 响应体结构

```json
{
  "success": true,         // 查询是否成功

  // 查询结果数组，每个元素为一行数据，key 为 select 中指定的 alias
  "data": [
    {
      "f_f3969fbc48264125": "OR-C",
      "f_754ed2fb474f09f9": "115654.6169",
      "last_f_754ed2fb474f09f9": "108601.5413",   // dataComparison 开启时裂变的上期字段
      "diff_f_754ed2fb474f09f9": "7053.0756",     // 绝对差值字段
      "pct_f_754ed2fb474f09f9": "0.0649"          // 环比变化率字段
    }
  ],

  // 查询元信息
  "meta": {
    "dataSource": "doris_analytics",     // 数据源
    "queryId": "q_abc123",              // 查询唯一 ID（用于追踪）
    "timestamp": "2026-04-11T08:00:00Z",// 查询时间
    "executionTimeMs": 1045,             // SQL 执行耗时（毫秒）
    "rowCount": 20,                      // 本次返回的行数
    "totalCount": 652,                   // 满足条件的总行数（分页时使用）
    "generatedSql": "SELECT ...",        // 生成的 SQL（调试用）
    "dialect": "doris",                  // SQL 方言
    "cached": false                      // 是否命中缓存
  },

  // 错误信息（success 为 false 时有值）
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "字段 from.table 不能为空"
  }
}
```

---

## 三、数据集类型详解

数据集类型决定了 `from.table` 的结构。判断依据是 `from.table` 的内容中是否包含内层 WHERE 占位符。

### 3.1 判断方法

```
from.table 中含有 {where_sub_placeholder_N} 或 {and_sub_placeholder_N}
    → 子查询类型（inner_where_enabled = true）→ 使用简化接口 query_simple

from.table 中只含有 {permission_placeholder_N}，没有上述占位符
    → 非子查询类型（标准模式）→ 使用 where
```

### 3.2 非子查询类型（标准模式）

**特征**：`from.table` 是一个封装好的视图或子查询 SQL，内部仅含权限占位符，**不含** `{where_sub_placeholder_N}` 或 `{and_sub_placeholder_N}`。

**过滤条件**：全部放在外层 `where` 中，包括维度过滤和日期范围过滤。

**完整示例**：

```json
{
  "query": {
    "from": {
      "table": "{table}",
      "database": "",
      "alias": "ds_d35ac6f3910c",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_d35ac6f3910c.platform_name", "alias": "f_dim001" },
      { "expr": "ds_d35ac6f3910c.price", "alias": "f_metric001", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.platform_name", "operator": "in", "value": ["Amazon"] },
        { "field": "ds_d35ac6f3910c.country_name", "operator": "in", "value": ["美国"] },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2026-03-13", "2026-04-11"] }
      ]
    },
    "groupBy": ["f_dim001"],
    "limit": 20,
    "offset": 0
  },
  "dataSource": "doris_analytics",
  "userEmail": "{userEmail}"
}
```

### 3.3 子查询类型（inner_where_enabled = true）

**特征**：`from.table` 是多层嵌套的 SQL 字符串，内部含有以下占位符：

| 占位符 | 说明 |
|--------|------|
| `{where_sub_placeholder_1}` | 第一层子查询的 WHERE 位置 |
| `{and_sub_placeholder_2}` | 第二层 AND 条件位置 |
| `{permission_placeholder_1}` | 权限条件 1（由 `from.permission[0]` 驱动，Python 服务内部替换） |
| `{permission_placeholder_2}` | 权限条件 2（由 `from.permission[1]` 驱动，Python 服务内部替换） |

> **子查询类型数据集必须使用简化接口**（`query_simple` / `opscli query simple`），由服务端自动处理过滤条件的注入，禁止手写完整 payload。

### 3.4 两种类型对比总结

| 对比维度 | 非子查询类型 | 子查询类型 |
|----------|------------|-----------|
| from.table 内容 | 普通视图/封装子查询 | 多层嵌套 SQL 含内层占位符 |
| 内层占位符 | 无 | 含 `{where_sub_placeholder_N}` / `{and_sub_placeholder_N}` |
| 查询方式 | 可手写完整 payload | 必须使用简化接口（服务端自动处理） |
| database 字段 | 普通表时传库名 | 子查询时传空字符串 `""` |

---

## 四、权限控制机制

### 4.1 permission 字段说明

`from.permission` 是一个字符串数组，声明该数据集的权限控制维度：

| 维度值 | 含义 |
|--------|------|
| `channel_uuid` | 店铺级权限（按渠道 UUID 控制） |
| `listing_uuid` | 商品级权限（按 listing 复合主键 UUID 控制） |

```json
"permission": ["channel_uuid", "listing_uuid"]
```

### 4.2 占位符替换原理

Python 服务在执行 SQL 前，会将 `from.table` 中的权限占位符替换为子查询，从权限表中动态获取当前用户被授权的数据范围：

| 占位符 | 替换为 |
|--------|--------|
| `{permission_placeholder_1}` | `SELECT DISTINCT auth_value FROM base.v_user_permission_flat WHERE user_email = '<userEmail>' AND field_type = 'channel_uuid'` |
| `{permission_placeholder_2}` | `SELECT DISTINCT auth_value FROM base.v_user_permission_flat WHERE user_email = '<userEmail>' AND field_type = 'listing_uuid'` |

> `{permission_placeholder_N}` 中的 N 与 `from.permission` 数组的下标（从 1 开始）一一对应。

### 4.3 多权限维度 OR 逻辑

当 `from.permission` 包含两个维度时，两个权限条件使用 `OR` 连接，满足任一权限即可查看数据：

```sql
-- 最终生成的权限 SQL 片段（示意）
AND (
    bc.channel_uuid IN (SELECT DISTINCT auth_value FROM base.v_user_permission_flat WHERE user_email = '{userEmail}' AND field_type = 'channel_uuid')
    OR
    bc.listing_uuid IN (SELECT DISTINCT auth_value FROM base.v_user_permission_flat WHERE user_email = '{userEmail}' AND field_type = 'listing_uuid')
)
```

### 4.4 权限字段完整枚举

`from.permission` 数组中可传入的权限字段枚举值如下（对应 `base.v_user_permission_flat` 表中的 `field_type`）：

| 分组 | 字段值 | 字段名称 | 备注 |
|------|--------|---------|------|
| 全渠道 | `dept_id` | 部门 ID | — |
| 全渠道 | `channel_uuid` | 渠道 UUID | 生成规则：部门 + 平台 + 佰易账号 + 国家 |
| 全渠道 | `channel_code` | 渠道 CODE | 生成规则：平台 + 佰易账号 + 国家 |
| 部分渠道 | `listing_uuid` | LISTING UUID | 生成规则：平台 + 佰易账号 + 国家 + 渠道SKU |
| 部分渠道 | `listing_uuid_share` | 共享 LISTING UUID | 佰易数据集使用；生成规则：平台 + 佰易账号 + 国家 + 渠道SKU |
| 部分渠道 | `asin_uuid` | ASIN UUID | 生成规则：平台 + 佰易账号 + 国家 + ASIN |
| 部分渠道 | `asin_uuid_share` | 共享 ASIN UUID | 佰易数据集使用；生成规则：平台 + 佰易账号 + 国家 + ASIN |
| 部分渠道 | `ed_sku` | 公司 SKU | — |
| 部分渠道 | `team_uuid` | 销售小组 UUID | 生成规则：部门 + 大组 + 销售小组 |
| 部分渠道 | `dev_team_uuid` | 开发小组 UUID | 生成规则：部门 + 大组 + 开发小组 |
| 部分渠道 | `asin_ps_uuid` | ASIN PS UUID | 运营监控数据集（爬虫数据集）使用；生成规则：平台 + 国家 + ASIN |

> **说明**："全渠道"字段控制整个渠道的数据访问；"部分渠道"字段控制渠道内更细粒度（SKU/ASIN/团队）的数据访问。多个字段同时使用时，Python 服务将生成 OR 逻辑的子查询。

---

## 五、WHERE 条件构建指南

### 5.1 操作符完整列表

| 操作符 | SQL 语义 | value 类型 | 示例 |
|--------|----------|-----------|------|
| `eq` | `=` | string / number | `{ "field": "platform", "operator": "eq", "value": "Amazon" }` |
| `ne` | `!=` | string / number | `{ "field": "status", "operator": "ne", "value": 0 }` |
| `gt` | `>` | number | `{ "field": "price", "operator": "gt", "value": 100 }` |
| `gte` | `>=` | number | `{ "field": "price", "operator": "gte", "value": 100 }` |
| `lt` | `<` | number | `{ "field": "price", "operator": "lt", "value": 1000 }` |
| `lte` | `<=` | number | `{ "field": "price", "operator": "lte", "value": 1000 }` |
| `like` | `LIKE` | string（含 `%` 通配符） | `{ "field": "name", "operator": "like", "value": "%iphone%" }` |
| `not_like` | `NOT LIKE` | string | - |
| `in` | `IN` | array | `{ "field": "country", "operator": "in", "value": ["美国","英国"] }` |
| `not_in` | `NOT IN` | array | `{ "field": "status", "operator": "not_in", "value": [0, -1] }` |
| `between` | `BETWEEN` | `[min, max]` 二元数组 | `{ "field": "date_id", "operator": "between", "value": ["2026-01-01","2026-03-31"] }` |
| `not_between` | `NOT BETWEEN` | `[min, max]` 二元数组 | - |
| `is_null` | `IS NULL` | 无需传 value | `{ "field": "remark", "operator": "is_null" }` |
| `is_not_null` | `IS NOT NULL` | 无需传 value | `{ "field": "remark", "operator": "is_not_null" }` |
| `regexp` | `REGEXP` | string（正则表达式） | `{ "field": "sku", "operator": "regexp", "value": "^A[0-9]{4}" }` |
| `not_regexp` | `NOT REGEXP` | string | - |

### 5.2 树形嵌套结构规范

WHERE 条件支持任意层级的树形嵌套，节点分为两类：

**逻辑节点**（分组节点）：

```json
{
  "operator": "AND",      // 必填：AND | OR
  "conditions": [...],    // 必填：子节点数组（可以是逻辑节点或叶子节点）
  "negate": false,        // 可选：true 时对整个节点取反（NOT）
  "case_sensitive": true  // 可选：false 时字符串比较大小写不敏感
}
```

> 逻辑节点不能包含 `field` 属性。

**叶子节点**（条件节点）：

```json
{
  "field": "ds_xxx.platform_name",   // 必填：字段名（含数据集别名）
  "operator": "in",                   // 必填：操作符（见上表）
  "value": ["Amazon", "eBay"],        // 按操作符要求传值
  "negate": false,                    // 可选：取反
  "case_sensitive": true              // 可选：大小写敏感
}
```

> 叶子节点不能包含 `conditions` 属性。

**嵌套示例（AND 中含 OR 子组）**：

```json
{
  "operator": "AND",
  "conditions": [
    { "field": "ds_xxx.date_id", "operator": "between", "value": ["2026-03-13", "2026-04-11"] },
    {
      "operator": "OR",
      "conditions": [
        { "field": "ds_xxx.platform_name", "operator": "eq", "value": "Amazon" },
        { "field": "ds_xxx.platform_name", "operator": "eq", "value": "eBay" }
      ]
    },
    { "field": "ds_xxx.order_status", "operator": "not_in", "value": [-1, 0] }
  ]
}
```

### 5.3 translate 条件字段翻译枚举

在 WHERE 条件的叶子节点中，可以额外传入 `translate` 字段，指示 Python 服务在执行过滤前将用户输入的值转换为另一种 ID 类型。例如，用户选择"渠道名称"过滤时，后端需将渠道名称翻译为对应的 ASIN 或 SKU 后再过滤底层数据。

**带 translate 的叶子节点示例**：

```json
{
  "field": "ds_d35ac6f3910c.channel_name",
  "operator": "in",
  "translate": "SKU_TO_ASIN",
  "value": ["Ohwill-SF-美国", "Onbrill-SF-美国", "CP-美国"]
}
```

**translate 枚举值完整列表**：

| 过滤字段（field_name）| translate 枚举值 | 含义 |
|----------------------|-----------------|------|
| `date_id` | — | 日期字段，无需翻译 |
| `platform_name` | `PLATFORM_TO_SKU` | 平台 → 公司 SKU |
| `country_name` | `COUNTRY_TO_SKU` | 国家 → 公司 SKU |
| `channel_name` | `CHANNEL_TO_SKU` | 渠道 → 公司 SKU |
| `team_name` | `TEAM_TO_SKU` | 销售小组 → 公司 SKU |
| `team_username` | `TEAM_USER_TO_SKU` | 销售人员 → 公司 SKU |
| `develop_username` | `DEVELOP_USER_TO_SKU` | 开发人员 → 公司 SKU |
| `asin` | `ASIN_TO_MSKU` | ASIN → 渠道 SKU |
| `asin` | `ASIN_TO_SKU` | ASIN → 公司 SKU |
| `ed_sku`（公司SKU）| `SKU_TO_ASIN` | 公司 SKU → ASIN |
| `ed_sku`（公司SKU）| `SKU_TO_MSKU` | 公司 SKU → 渠道 SKU |
| `sell_sku`（渠道SKU）| `MSKU_TO_ASIN` | 渠道 SKU → ASIN |
| `sell_sku`（渠道SKU）| `MSKU_TO_SKU` | 渠道 SKU → 公司 SKU |
| `product_name` | `PRODUCT_NAME_TO_ASIN` | 产品名称 → ASIN |
| `product_name` | `PRODUCT_NAME_TO_MSKU` | 产品名称 → 渠道 SKU |
| `model` | `MODEL_TO_ASIN` | 产品型号 → ASIN |
| `model` | `MODEL_TO_MSKU` | 产品型号 → 渠道 SKU |

> **注意**：`translate` 是可选字段。当过滤值本身就是底层表字段的原始值时（如直接按 `date_id` 过滤日期），无需传 translate。

### 5.4 小计/总计查询中的 WHERE 特殊处理

当交叉表或透视表做小计、总计的补充查询时，PHP 层会在原始 WHERE 基础上追加**当前分页行维度的 IN 条件**，以确保结果仅涵盖当前页的维度值：

```json
{
  "operator": "AND",
  "conditions": [
    {
      "...原始 WHERE 条件（日期、维度等）..."
    },
    {
      "operator": "AND",
      "negate": false,
      "case_sensitive": true,
      "conditions": [
        {
          "field": "ds_xxx.large_team_name",
          "operator": "in",
          "value": ["OR-C", "OR-E"]           // 当前页出现的大团队名
        },
        {
          "field": "ds_xxx.develop_username",
          "operator": "in",
          "value": ["向建权", "张茜荛"]        // 当前页出现的开发人员名
        }
      ]
    }
  ]
}
```

---

## 六、dataComparison 数据对比

### 6.1 基本原理

当 `dataComparison.switch = true` 时，Python 服务不会执行两次独立查询，而是将当期和对比期的数据**合并到一次 SQL** 中执行。

**强制约束**：开启 `dataComparison` 时，请求必须同时包含主查询周期的日期过滤条件。主周期来自 `query.where` / 简化接口 `filters`，对比周期来自 `dataComparison.startDate` 和 `dataComparison.endDate`。不要只传 `dataComparison`；缺少主周期日期过滤时，SQL 改写可能无法正确生成当期条件，并报 `QS-EXE-005 missing ')' at '{'` 等解析错误。

核心机制是通过条件聚合（Conditional Aggregation）实现：

```sql
-- Python 生成的对比 SQL 核心逻辑（示意）
SELECT
    ds_xxx.large_team_name AS f_dim001,
    -- 当期聚合（只累加日期在当期范围内的行）
    SUM(IF(ds_xxx.date_id BETWEEN '2026-03-13' AND '2026-04-11', ds_xxx.price, 0)) AS f_metric001,
    -- 对比期聚合（只累加日期在对比期范围内的行）
    SUM(IF(ds_xxx.date_id BETWEEN '2026-02-11' AND '2026-03-12', ds_xxx.price, 0)) AS last_f_metric001
FROM (...)  AS ds_xxx
WHERE
    -- WHERE 日期范围自动扩展为当期 OR 对比期的并集
    (ds_xxx.date_id BETWEEN '2026-03-13' AND '2026-04-11'
     OR ds_xxx.date_id BETWEEN '2026-02-11' AND '2026-03-12')
GROUP BY f_dim001
```

### 6.2 字段裂变规则

开启 dataComparison 后，每个度量字段（指标字段）会自动裂变为 4 个字段：

| 字段名格式 | 含义 | 说明 |
|-----------|------|------|
| `f_xxx` | 当期值 | 原始别名，主查询当期聚合结果 |
| `last_f_xxx` | 上期值 | 对比期聚合结果 |
| `diff_f_xxx` | 绝对差值 | `f_xxx - last_f_xxx` |
| `pct_f_xxx` | 环比变化率 | `(f_xxx - last_f_xxx) / ABS(last_f_xxx)`；当上期为 0 时返回 `null` |

> 维度字段（groupBy 中的字段）不会裂变，只有度量字段（有 aggregation 的字段）才会裂变。

### 6.3 date 字段填写规则

| 数据集类型 | dataComparison.field 的值 |
|-----------|--------------------------|
| 非子查询类型 | `数据集别名.date_id`，如 `ds_6fbfb45edd2a.date_id` |
| 子查询类型 | 同上，`数据集别名.date_id`（日期过滤通过外层 `where` 的 translate 逻辑处理） |

### 6.4 配置完整示例

**请求（交叉表开启数据对比）**：

```json
{
  "query": {
    "from": {
      "table": "{table}",
      "database": "",
      "alias": "ds_6fbfb45edd2a",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      {
        "expr": "ds_6fbfb45edd2a.large_team_name",
        "alias": "f_f3969fbc48264125"
      },
      {
        "expr": "ds_6fbfb45edd2a.price",
        "alias": "f_754ed2fb474f09f9",
        "aggregation": "SUM"
      }
    ],
    "groupBy": ["f_f3969fbc48264125"],
    "where": {
      "conditions": [
        {
          "field": "ds_6fbfb45edd2a.date_id",
          "operator": "between",
          "value": ["2026-03-13", "2026-04-11"]
        }
      ],
      "operator": "AND"
    },
    "limit": 20,
    "offset": 0
  },
  "dataSource": "doris_analytics",
  "userEmail": "{userEmail}",
  "dataComparison": {
    "switch": true,
    "field": "ds_6fbfb45edd2a.date_id",   // 数据集别名.date_id
    "startDate": "2026-02-11",              // 对比期开始
    "endDate": "2026-03-12"                 // 对比期结束
  }
}
```

**响应数据样例（裂变字段）**：

```json
{
  "success": true,
  "data": [
    {
      "f_f3969fbc48264125": "OR-C",
      "f_754ed2fb474f09f9": "115654.6169",        // 当期值
      "last_f_754ed2fb474f09f9": "108601.5413",   // 上期值
      "diff_f_754ed2fb474f09f9": "7053.0756",     // 绝对差值
      "pct_f_754ed2fb474f09f9": "0.0649"          // 环比变化率（约 6.49%）
    },
    {
      "f_f3969fbc48264125": "OR-E",
      "f_754ed2fb474f09f9": "98320.1100",
      "last_f_754ed2fb474f09f9": "102500.0000",
      "diff_f_754ed2fb474f09f9": "-4179.8900",
      "pct_f_754ed2fb474f09f9": "-0.0408"         // 负值表示下降
    }
  ],
  "meta": {
    "rowCount": 2,
    "totalCount": 15,
    "executionTimeMs": 1045,
    "cached": false
  }
}
```

---

## 七、多次查询场景说明

PHP 层（`QueryBuilder`）根据图表类型会对 Python API 发起多次查询，然后合并结果。

### 7.1 多次查询汇总表

| 场景 | 适用图表类型 | Python API 调用次数 | 说明 |
|------|------------|-------------------|------|
| 标准单次查询 | 所有普通图表 | 1 | 一次 API 调用获取所有数据 |
| 堆叠图二阶段查询 | 堆叠柱状图、堆叠折线图 | 2 | 第一次取分页维度，第二次取完整堆叠数据 |
| 交叉表列枚举 | crosstab / pivot_table | 2 | 第一次枚举列维度所有组合（上限由 `CROSSTAB_COLUMN_ENUM_LIMIT` 控制，默认 10000）|
| 交叉表矩阵取数 | crosstab / pivot_table | 2 | 按行×列笛卡尔矩阵取数 |
| 行小计 | crosstab / pivot_table | +1 | 按首维度 + 列维度分组聚合 |
| 行总计 | crosstab / pivot_table | +1 | 按列维度分组或无分组 |
| 全局指标总计 | crosstab / pivot_table（有列维度）| +1 | `groupBy=[]`，`limit=1` |
| 列总计 | crosstab / pivot_table（showColTotal=true）| +1 | 按行维度分组 |
| dim_summary（维度汇总）| crosstab / pivot_table（多维 + 列维度）| +1 | 按首维度分组 |
| 右轴独立查询 | combo_bar_line* 系列 | 2 | 右轴指标仅按 xAxis 聚合，不含其他分组 |
| 指标卡汇总 | metric_trend | 2 | 第二次查询 `groupBy=[]`，`limit=1`，获取全局汇总值 |

### 7.2 各场景 WHERE 特殊处理说明

**堆叠图二阶段查询**：
- 第一次查询：正常分页，获取当前页的维度值列表
- 第二次查询：WHERE 中追加第一次查询结果的维度 IN 条件，去掉 limit/offset

**交叉表列枚举查询**：
- 只 SELECT 列维度字段，DISTINCT 去重
- limit 由环境变量 `CROSSTAB_COLUMN_ENUM_LIMIT` 控制
- 不传 `dataComparison`（无需对比期数据）

**小计/总计补充查询**：
- WHERE 中额外追加当前页行维度的 IN 条件（详见第五章 5.3 节）
- orderBy 仅保留维度相关的排序（去掉指标排序避免结果错位）

**指标卡汇总查询**：
- `groupBy` 传空数组 `[]`
- `limit` 传 `1`
- `offset` 传 `0`

---

## 八、SELECT 字段开发规范

### 8.1 两种字段格式

**格式一：简化格式（推荐，适用于普通字段 + 标准聚合）**

```json
{ "expr": "ds_xxx.price", "alias": "f_metric001", "aggregation": "SUM" }
```

生成 SQL：`SUM(ds_xxx.price) AS f_metric001`

**格式二：完整表达式格式（适用于复杂计算场景）**

```json
{
  "expr": "ROUND(SUM(ds_xxx.ads_total_spend_cny) / SUM(ds_xxx.ads_sales_cny), 4)",
  "alias": "f_metric002"
}
```

生成 SQL：`ROUND(SUM(ds_xxx.ads_total_spend_cny) / SUM(ds_xxx.ads_sales_cny), 4) AS f_metric002`

> 完整表达式格式中，`aggregation` 字段不传（或传 `null`），Python 服务直接将 `expr` 透传到 SQL 中，不做额外包裹。

#### 8.1.1 公式指标查询规范

当字段 metadata 中存在 `formula_config` / `summary_expression` / `detail_expression` 时，说明该字段是公式指标。**手写 query payload 时**，不能再按普通指标写成 `expr + aggregation` 的简化格式，而应直接使用公式表达式。

聚合查询场景应使用 `summary_expression`，查询结构示例：

```json
{
  "expr": "ROUND(SUM(dsp)/SUM(price), 4)",
  "alias": "f_yZZfW7cNu8nYMGCS"
}
```

对应 SQL：

```sql
ROUND(SUM(dsp)/SUM(price), 4) AS f_yZZfW7cNu8nYMGCS
```

明细查询场景应使用 `detail_expression`；如果字段同时提供了 `detail_expression` 与 `summary_expression`，应按查询场景选择分支：

- 明细查询：使用 `detail_expression`
- 聚合 / 分组查询：使用 `summary_expression`

错误示例：

```json
{
  "expr": "sell_qty_days",
  "alias": "f_yZZfW7cNu8nYMGCS",
  "aggregation": "SUM"
}
```

> 原因：公式指标的聚合逻辑已经内置在公式表达式中，再额外传 `aggregation` 会导致语义错误或二次聚合。
>
> 如果使用的是 `opscli query build` 这类上层构造工具，可以让工具根据 metadata 自动将公式字段展开成完整表达式；但最终发送到查询服务的原始 payload 结构仍应以上述完整表达式格式为准。

常见对照示例：

| 场景 | 正确写法 | 说明 |
|------|----------|------|
| 普通求和指标 | `{ "expr": "ds_xxx.price", "alias": "f_price", "aggregation": "SUM" }` | 普通物理字段，可用简化格式 |
| 公式占比指标 | `{ "expr": "ROUND(SUM(dsp)/SUM(price), 4)", "alias": "f_yZZfW7cNu8nYMGCS" }` | 公式已自带聚合逻辑，不再传 `aggregation` |
| 公式平均指标 | `{ "expr": "ROUND(SUM(original_price) / SUM(order_qty), 4)", "alias": "f_xxx_avg_price" }` | 这类“平均价/占比/比率”字段通常应走完整表达式格式 |
| 错误示例 | `{ "expr": "sell_qty_days", "alias": "f_xxx", "aggregation": "SUM" }` | 会导致公式字段被当作普通字段处理 |

### 8.2 聚合函数参考列表

| 聚合函数 | 说明 | 示例 |
|----------|------|------|
| `SUM` | 求和 | 销售额、广告花费 |
| `COUNT` | 计数 | 订单数 |
| `AVG` | 平均值 | 平均单价 |
| `MAX` | 最大值 | 最高价格 |
| `MIN` | 最小值 | 最低价格 |
| `DISTINCT_COUNT` | 去重计数（COUNT DISTINCT） | 店铺数、SKU 数 |
| `STDDEV` | 样本标准差 | |
| `STDDEV_POP` | 总体标准差 | |
| `VARIANCE` | 样本方差 | |
| `VAR_POP` | 总体方差 | |
| `MEDIAN` | 中位数 | |
| `PERCENTILE` | 百分位数 | |
| `FIRST` | 组内第一个值 | |
| `LAST` | 组内最后一个值 | |
| `GROUP_CONCAT` | 字符串拼接 | |
| `ROUND` | 四舍五入（通常在 expr 中使用） | |
| `ABS` | 绝对值 | |
| `CEIL` | 向上取整 | |
| `FLOOR` | 向下取整 | |
| `SUBSTRING` | 字符串截取 | |

### 8.3 维度字段与指标字段区分

| 字段类型 | 是否传 aggregation | 是否出现在 groupBy | dataComparison 是否裂变 |
|----------|-------------------|-------------------|------------------------|
| 维度字段（维度） | 不传 | 出现在 groupBy | 不裂变 |
| 指标字段（度量） | 传聚合函数 | 不出现在 groupBy | 裂变为 4 个字段 |

### 8.4 高级计算算法（comparison 字段）

当 select 字段中包含 `comparison` 属性时，Python 服务将对该字段启用对应的高级计算算法，在 SQL 层通过窗口函数或二次聚合完成复杂运算。

目前支持三种算法：

| `comparison` 值 | 算法名称 | 说明 |
|----------------|---------|------|
| `MOY` | 同环比 | 将当期值与历史对应期做差值/百分比计算 |
| `ACC` | 累加 | 按时间序列做滚动累计值（Running Total） |
| `PPT` | 占比 | 将当前指标值除以全局总量（Percentage of Total） |

#### 8.4.1 同环比（MOY）

**完整字段结构**：

```json
// 前提：groupBy 数组中必须同时包含日期字段和非日期维度字段
// 例如：
// "groupBy": ["dept_name", "DATE_FORMAT(date_id, '%Y-%m-%d')"]

{
  "expr": "price",
  "alias": "f_692e9ad694bcd_3240",
  "comparison": "MOY",
  "params": {
    "date": "DATE_FORMAT(date_id, '%Y-%m-%d')",  // groupBy 中的日期字段（带格式）
    "dim": ["dept_name"],                         // groupBy 中除日期外的所有维度字段
    "type": "MOM_DAY",                            // 同环比类型枚举值（见下表）
    "cacl_type": "ORIGINAL",                      // 计算类型：ORIGINAL/COMPARE/PERCENT
    "aggregation": "SUM"                          // 先聚合，再做同环比计算
  }
}
```

**params 字段说明**：

| 字段 | 名称 | 说明 | 示例 |
|------|------|------|------|
| `date` | 日期字段（含格式） | 必须与 `groupBy` 中的日期格式完全一致 | `DATE_FORMAT(date_id, '%Y-%m-%d')` |
| `dim` | 非日期维度字段列表 | `groupBy` 中除日期字段之外的所有字段 | `["dept_name"]` |
| `type` | 同环比类型枚举值 | 见下方类型枚举表 | `MOM_DAY` |
| `cacl_type` | 同环比计算类型 | `ORIGINAL`=原值，`COMPARE`=差值，`PERCENT`=百分比 | `ORIGINAL` |
| `aggregation` | 聚合函数 | 先按此函数聚合，再进行同环比计算 | `SUM` |

**type 枚举值完整列表**：

| 日期粒度 | 名称 | `type` 枚举值 | groupBy 中日期格式示例 |
|---------|------|-------------|----------------------|
| 天粒度 | 日环比 | `MOM_DAY` | `DATE_FORMAT(date_id, '%Y-%m-%d')` |
| 天粒度 | 周同比 | `YOY_WEEK` | `DATE_FORMAT(date_id, '%Y-%m-%d')` |
| 天粒度 | 月同比 | `YOY_MONTH` | `DATE_FORMAT(date_id, '%Y-%m-%d')` |
| 天粒度 | 年同比 | `YOY_YEAR` | `DATE_FORMAT(date_id, '%Y-%m-%d')` |
| 周粒度 | 周环比 | `MOM_WEEK` | `DATE_FORMAT(date_id, '%x-%v')` |
| 周粒度 | 年同比 | `YOY_YEAR` | `DATE_FORMAT(date_id, '%x-%v')` |
| 月粒度 | 月环比 | `MOM_MONTH` | `DATE_FORMAT(date_id, '%Y-%m')` |
| 月粒度 | 年同比 | `YOY_YEAR` | `DATE_FORMAT(date_id, '%Y-%m')` |
| 季粒度 | 季环比 | `MOM_QUARTER` | `DATE_FORMAT(date_id, '%Y-%q')` |
| 季粒度 | 年同比 | `YOY_YEAR` | `DATE_FORMAT(date_id, '%Y-%q')` |
| 年粒度 | 年环比 | `MOM_YEAR` | `DATE_FORMAT(date_id, '%Y')` |

**交叉表 / 透视表特殊规则**：

| 场景 | 同环比处理规则 |
|------|-------------|
| 行小计（首维度为日期时） | **需要计算**同环比 |
| 行小计（首维度非日期时） | **不计算**，显示 `-` |
| 行总计 | **不计算**，显示 `-` |

**特殊备注**：

1. 计算公式字段（自定义 expr 表达式）暂不兼容同环比，需后续开发支持。
2. 时间维度存在多个颗粒度时（如同时有年、年月、年月日），`params.date` 传**最小颗粒度**的日期格式（如年月日），且 `groupBy` 中的时间维度也只传最小颗粒度字段。

---

#### 8.4.2 累加（ACC）

按时间序列做滚动累计值（Running Total）：先对每行数据执行聚合函数，再在时间维度上做滚动求和。

**完整字段结构**：

```json
{
  "expr": "price",
  "alias": "f_692e9ad694bcd_3240",
  "comparison": "ACC",
  "params": {
    "dim": [],           // 分组累加维度，暂不支持，固定传 []
    "aggregation": "SUM" // 先聚合再累加
  }
}
```

**params 字段说明**：

| 字段 | 名称 | 说明 |
|------|------|------|
| `dim` | 分组累加维度 | 暂不支持分组累加，固定传空数组 `[]` |
| `aggregation` | 聚合函数 | 先按此函数聚合，再在时间轴上做累加 |

**交叉表 / 透视表特殊规则**：

| 场景 | 累加处理规则 |
|------|------------|
| 行小计 | **不计算**，显示 `-` |
| 行总计 | **不计算**，显示 `-` |

---

#### 8.4.3 占比（PPT）

将当前维度的指标值除以全局（或组内）总量，计算占比百分比。先聚合，再除以总量。

**完整字段结构**：

```json
{
  "expr": "price",
  "alias": "f_692e9ad694bcd_3240",
  "comparison": "PPT",
  "params": {
    "dim": [],           // 分组占比维度，暂不支持，固定传 []
    "aggregation": "SUM" // 先聚合再算占比
  }
}
```

**params 字段说明**：

| 字段 | 名称 | 说明 |
|------|------|------|
| `dim` | 分组占比维度 | 暂不支持分组占比，固定传空数组 `[]` |
| `aggregation` | 聚合函数 | 先按此函数聚合，再计算占比 |

**交叉表 / 透视表特殊规则**：

| 场景 | 占比处理规则 |
|------|------------|
| 行小计 | **需要计算**占比 |
| 行总计 | **需要计算**占比 |

> ⚠️ **注意**：PPT 与 ACC 在小计/总计处理上规则相反。PPT 的小计/总计需展示合计行的占比；ACC 则不适合在汇总行展示滚动累加值，均显示 `-`。

---

#### 8.4.4 三种算法对比速查

| 对比维度 | MOY（同环比） | ACC（累加） | PPT（占比） |
|----------|-------------|-----------|-----------|
| `comparison` 值 | `MOY` | `ACC` | `PPT` |
| `params.date` | 必填（日期格式字段） | 不需要 | 不需要 |
| `params.dim` | 必填（非日期维度列表） | 固定 `[]` | 固定 `[]` |
| `params.type` | 必填（枚举值） | 不需要 | 不需要 |
| `params.cacl_type` | 必填 | 不需要 | 不需要 |
| `params.aggregation` | 必填 | 必填 | 必填 |
| 小计是否计算 | 首维度为日期时计算 | 不计算（显示 `-`） | 计算 |
| 总计是否计算 | 不计算（显示 `-`） | 不计算（显示 `-`） | 计算 |
| groupBy 要求 | 必须含日期字段 | 无特殊要求 | 无特殊要求 |

---

## 九、分页与排序规范

### 9.1 分页参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `limit` | integer | 每页返回行数 |
| `offset` | integer | 跳过行数（从 0 开始） |

```json
// 第 1 页，每页 20 条
{ "limit": 20, "offset": 0 }

// 第 2 页，每页 20 条
{ "limit": 20, "offset": 20 }
```

**不传分页的场景**（矩阵查询、小计/总计补充查询）：不传 `limit` 和 `offset` 字段，Python 服务返回全量数据。

### 9.2 排序规范

```json
"orderBy": [
  { "expr": "f_metric001", "desc": true },    // 按指标降序
  { "expr": "f_dim001", "desc": false }        // 按维度升序
]
```

**规范要点**：

- `expr` 的值必须是 `select` 中某个字段的 `alias`，不能使用原始字段名
- 多个排序条件按数组顺序依次生效（先排第一个，再排第二个）
- `desc: true` 表示降序（DESC），`desc: false` 表示升序（ASC）
- 小计/总计查询中，orderBy 仅保留与维度字段对应的排序条件（指标排序会被自动移除）

---

## 十、开发注意事项

### 10.1 alias 命名规范

PHP 端生成字段别名的规则如下：

- **格式**：`f_[随机哈希]`，例如 `f_XdPACWQYZuZBZTBGN9ZL`、`f_754ed2fb474f09f9`
- **维度字段和指标字段**使用相同的命名规则，均为 `f_` 前缀
- **dataComparison 裂变字段**命名规则（以原始别名 `f_xxx` 为例）：
  - `last_f_xxx`：上期值
  - `diff_f_xxx`：绝对差值
  - `pct_f_xxx`：环比变化率

> 开发时不要在业务逻辑中硬编码 alias 值，应以图表配置的 fieldId 或字段映射关系来识别字段。

### 10.2 子查询类型判断方法

```php
// PHP 伪代码示例
function isSubQueryType(string $tableSQL): bool {
    return str_contains($tableSQL, '{where_sub_placeholder_')
        || str_contains($tableSQL, '{and_sub_placeholder_');
}

// 使用示例
if (isSubQueryType($dataset['table'])) {
    // 子查询类型：必须使用简化接口，由服务端自动处理过滤条件注入
    // 禁止手写完整 payload，改用 query_simple / opscli query simple
} else {
    // 非子查询类型：所有条件放 where
    $request['query']['where'] = buildWhere($filters, $dateRange);
}
```

### 10.3 日期条件处理

| 数据集类型 | 日期条件位置 | 字段格式 |
|-----------|------------|---------|
| 非子查询类型 | `where.conditions` 中 | `数据集别名.date_id` |
| 子查询类型（inner_where_enabled）| `where.conditions` 中（translate 逻辑处理）| `数据集别名.date_id` |
| dataComparison 开启后 | Python 自动扩展 WHERE 日期范围为 `当期 OR 对比期` 的并集 | 无需 PHP 手动处理 |

### 10.4 错误处理

**错误响应格式**：

```json
{
  "success": false,
  "data": null,
  "meta": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "字段 from.table 不能为空"
  }
}
```

**常见错误码**：

| 错误码 | 原因 | 处理建议 |
|--------|------|---------|
| `VALIDATION_ERROR` | 请求参数校验失败（字段缺失或类型错误）| 检查请求体结构是否符合规范 |
| `DATA_SOURCE_ERROR` | 数据源连接失败或超时 | 检查 dataSource 标识是否正确，重试 |
| `SQL_EXECUTION_ERROR` | SQL 执行报错（语法错误、字段不存在等）| 开启 dryRun 调试生成的 SQL |
| `PERMISSION_DENIED` | userEmail 对应用户权限为空 | 检查用户权限配置 |
| `TIMEOUT_ERROR` | 查询超时 | 缩小时间范围或添加更多过滤条件 |

**调试技巧**：

```json
// 使用 dryRun 模式仅生成 SQL，不执行，方便排查 SQL 问题
{ "dryRun": true, "..." }

// 响应中的 meta.generatedSql 包含最终执行的 SQL 字符串
```

### 10.5 缓存使用建议

```json
"cacheControl": {
  "enabled": true,       // 生产环境建议开启缓存
  "forceRefresh": false, // 手动刷新时传 true
  "ttl": 300             // 缓存 5 分钟（秒）
}
```

- 交互式筛选场景（用户频繁切换筛选条件）：建议 `ttl` 设置为 `60`（1 分钟）
- 定时刷新的报表场景：建议 `ttl` 设置为 `300`（5 分钟）
- 小计/总计补充查询：可复用主查询的缓存配置

### 10.6 列枚举上限控制

交叉表的列维度枚举上限通过环境变量控制：

```
CROSSTAB_COLUMN_ENUM_LIMIT=10000   # 默认值 10000
```

当列维度的组合数超出上限时，多余的列不会展示，建议在前端提示用户缩小筛选范围。

---

## 附录：opscli 本地数据集 CSV 列说明

> 以下为 `opscli skills install ops-dataset-query` 安装后 `data/` 目录中 CSV 文件的列定义，供字段索引检索时参考。

### `data/datasets.csv` 列

| 列名 | 说明 |
|------|------|
| `table_id` | 数据集在系统中的唯一 ID |
| `dataset_alias` | 数据集别名（英文，用于 `--dataset` 参数） |
| `dataset_name` | 数据集中文名 |
| `dataset_type` | 数据集类型（table / query） |
| `dataset_category` | 业务分类（如：销售、库存、物流） |
| `from_table` | 源数据库表名 |
| `database` | 数据库标识 |
| `data_source` | 数据源标识 |
| `main_dttm_col` | 主时间字段 |
| `description` | 数据集描述 |
| `keywords` | 搜索关键词标签 |

### `data/dataset_fields.csv` 列

| 列名 | 说明 |
|------|------|
| `dataset_alias` | 所属数据集别名 |
| `dataset_name` | 所属数据集中文名 |
| `dataset_type` | 数据集类型 |
| `dataset_category` | 业务分类 |
| `field_name` | 字段名（英文，用于 `--dimension` / `--metric` 参数） |
| `verbose_name` | 字段中文名 |
| `field_type` | 字段类型：`dimension`（维度）/ `metric`（指标） |
| `data_type` | 数据类型：`STRING`、`INTEGER`、`DECIMAL`、`BOOLEAN` 等 |
| `is_dttm` | 是否为时间字段（`true`/`false`） |
| `is_restricted` | 是否受权限限制 |
| `expression` | 计算表达式（派生字段） |
| `description` | 字段描述 |
| `keywords` | 搜索关键词标签 |

---

*文档由 auto-scheduler 开发团队维护，如有疑问请联系数据平台组。*
