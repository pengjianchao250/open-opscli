# 一期实现：AI 取数能力底座开发需求

> **版本：** v1.3
> **最后更新：** 2026-04-21
> **适用项目：** auto-scheduler（运营系统）+ opscli（CLI 工具）

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [认证规范（全局）](#2-认证规范全局)
3. [opscli 输出格式规范（全局）](#3-opscli-输出格式规范全局)
4. [模块一：auto-scheduler 服务端](#4-模块一auto-scheduler-服务端)
5. [模块二：opscli 客户端](#5-模块二opscli-客户端)
6. [关键约束](#6-关键约束)
7. [验收标准](#7-验收标准)
8. [参考文档](#8-参考文档)

---

## 1. 背景与目标

在 opscli 现有认证体系基础上，构建面向 AI 工具的运营取数能力：

- **auto-scheduler**：新增带权限校验的取数代理接口（`cli-query`）+ 用户授权数据集结构导出接口（`skill/export`）
- **opscli**：新增 `skills` 命令组，支持安装和更新 Skill（含自动同步数据集 CSV）

---

## 2. 认证规范（全局）

所有接口（包括现有 manifest/export/publish）调用时必须同时携带：

| 认证方式 | 传参位置 | 示例 |
|----------|---------|------|
| JWT Bearer Token | `Authorization` 请求头 | `Authorization: Bearer eyJhbGci...` |
| Session ID | Cookie | `polarisUserToken=de01b35eb9fde53540748c71b02db7ec` |

**说明：** 通过同时携带 JWT 和 session_id cookie，可直接复用现有鉴权中间件（`jwt.auth` + `RoutePermissionMiddleware`），无需新增认证逻辑。

**opscli 端实现：**

```python
from opscli.auth import AuthClient

token = AuthClient().get_token("ops")      # JWT Bearer Token
session_id = AuthClient().get_session("ops")  # 读取本地存储的 session_id

headers = {"Authorization": f"Bearer {token}"}
cookies = {"polarisUserToken": session_id}
```

---

## 3. opscli 输出格式规范（全局）

### 3.1 统一输出格式要求

所有 `opscli skills` 子命令**默认输出 JSON**，通过 `--pretty` 参数切换为终端文字模式：

| 模式 | 触发方式 | 输出格式 | 用途 |
|------|---------|---------|------|
| **JSON（默认）** | 无参数 | 标准JSON | AI 工具解析、脚本集成、CI/CD、程序间管道调用 |
| 终端文字 | `--pretty` | typer.echo | 人工阅读，含进度条、对齐表格、颜色 |

**设计理由：**

- opscli 的主要调用者是 AI 工具和脚本，JSON 是机器可读的首选格式
- 默认 JSON 可确保 `opscli skills list | jq .` 等管道操作直接可用
- `--pretty` 保留人工友好体验，仅在需要时手动切换

### 3.2 JSON 输出结构规范

所有命令默认输出 JSON，遵循统一的顶层结构：

```json
{
  "success": true,
  "command": "skills upgrade",
  "data": { ... },
  "error": null
}
```

**失败时：**

```json
{
  "success": false,
  "command": "skills upgrade",
  "data": null,
  "error": {
    "code": "UPDATE_FAILED",
    "message": "网络超时，请检查连接"
  }
}
```

### 3.3 各命令 JSON data 结构

> 以下为默认输出（无需额外参数），加 `--pretty` 才会切换为终端文字表格。

**`skills list`（默认 JSON）：**

```json
{
  "success": true,
  "command": "skills list",
  "data": {
    "skills": [
      {
        "name": "dataset-fields",
        "local_version": "v0.1.0",
        "remote_version": "v0.1.2",
        "has_update": true,
        "installed_paths": [
          { "tool": "claude-code", "path": "~/.claude/skills/dataset-fields" },
          { "tool": "openclaw",    "path": "~/.openclaw/skills/dataset-fields" }
        ]
      }
    ]
  },
  "error": null
}
```

**`skills upgrade`（默认 JSON）：**

```json
{
  "success": true,
  "command": "skills upgrade",
  "data": {
    "updated": [
      {
        "name": "dataset-fields",
        "from_version": "v0.1.0",
        "to_version": "v0.1.2",
        "field_count": 1247,
        "tools": ["claude-code"]
      }
    ],
    "already_latest": [],
    "failed": []
  },
  "error": null
}
```

**`skills install`（默认 JSON）：**

```json
{
  "success": true,
  "command": "skills install",
  "data": {
    "name": "dataset-fields",
    "version": "v0.0.0",
    "installed_paths": [
      { "tool": "claude-code", "path": "~/.claude/skills/dataset-fields" }
    ]
  },
  "error": null
}
```

---

## 4. 模块一：auto-scheduler 服务端

### 4.1 取数代理接口（含权限校验）

**接口：** `POST /api/v1/data-metrics/cli-query`

**功能：** 在现有 PythonApiService 取数链路基础上，增加双层权限前置校验。

#### 4.1.1 权限校验流程

```
① 数据集权限校验（优先）
   $allowedDatasetIds = (new UserOrm())->getCombinedDataSetIds($userId);
   // 校验请求中的 tableId 是否在用户有权限的范围内
   // 不在 → 立即返回 403

② 字段权限校验
   $fieldPermissions = (new AuthService())->fieldValidation($userId)->toArray();
   // fieldValidation 返回 SysFieldPermissionOrm.slug 列表
   // 一期统一按导出 field_name 口径校验：维度=column_name，指标=metric_name
   // 从请求体 select 数组中找出所有 is_restricted=1 且不在 fieldPermissions 中的字段
   // 若存在无权限的受限字段 → 返回 403（明确列出字段名，不静默过滤）

③ 透传取数（两项校验均通过后）
   $pythonApiConfig = (new QueryBuilder)->getPythonApiConfig($data['tableId']);
   $pythonApiService = new PythonApiService($pythonApiConfig);
   $result = $pythonApiService->query($pythonApiQuery);
```

> **重要说明：** 字段权限校验行为是**返回 403 并明确列出无权限的字段名**，不做静默过滤。AI 工具收到 403 后应提示用户该字段无查看权限。

#### 4.1.2 字段权限判断逻辑

```php
// 伪代码
$restrictedFieldsInRequest = collect($selectFields)
    ->filter(fn($f) => $f['is_restricted'] === 1)
    ->pluck('field_name');

$unauthorizedFields = $restrictedFieldsInRequest
    ->diff($fieldPermissions);   // $fieldPermissions 即 slug 列表，等值于 field_name

if ($unauthorizedFields->isNotEmpty()) {
    return response()->json([
        'code' => 403,
        'msg'  => '以下字段无查看权限：' . $unauthorizedFields->implode('、')
    ], 403);
}
```

#### 4.1.3 请求体结构

在现有 PythonApiService query 结构基础上新增 `tableId` 字段：

```json
{
  "tableId": 1288,
  "query": {
    "from": { "table": "...", "alias": "ds_xxx", "database": "", "permission": ["channel_uuid"] },
    "select": [
      { "expr": "ds_xxx.order_amount", "alias": "f_metric001", "aggregation": "SUM" }
    ],
    "where": { "operator": "AND", "conditions": [...] },
    "groupBy": [...],
    "limit": 20,
    "offset": 0
  },
  "dataSource": "doris_analytics",
  "userEmail": "zhangsan@aukeys.com"
}
```

> `tableId` 用于数据集权限校验及获取 Python API 配置，`userEmail` 用于 Python 服务内部权限占位符替换（保持现有机制不变）。

#### 4.1.4 响应规范

**权限校验失败：**

```json
// 无数据集权限
{ "code": 403, "msg": "无该数据集访问权限" }

// 有受限字段无权限（明确列出字段名）
{ "code": 403, "msg": "以下字段无查看权限：order_cost、supplier_price" }
```

**查询成功（透传 Python 服务响应）：**

```json
{
  "success": true,
  "data": [...],
  "meta": { "rowCount": 20, "totalCount": 652, "executionTimeMs": 1045, ... }
}
```

---

### 4.2 用户授权数据集结构导出接口

**接口：** `GET /api/v1/data-metrics/datasets/skill/export`

在现有 `DatasetSkillController` 上扩展，增加用户维度过滤。

#### 4.2.1 与现有全量导出的差异

| 维度 | 现有全量导出（管理员） | 新增用户授权导出 |
|------|---------------------|----------------|
| 数据集范围 | 所有数据集 | `getCombinedDataSetIds($userId)` 过滤 |
| 字段范围 | 全部字段 | 排除受限字段（`is_restricted=1`）中用户无权限的字段 |
| 字段权限依据 | 无 | `fieldValidation($userId)` 返回的 slug 列表 |
| 触发方式 | 管理员手动 / publish 后 | opscli 自动拉取 |
| 用途 | DBA 分析 / 管理运维 | opscli 个人 Skill CSV 同步 |

#### 4.2.2 过滤规则

```
Step 1  用 getCombinedDataSetIds($userId) 获取用户有权限的数据集 ID 列表
        → 仅查询在此范围内的 dm_tables 数据集
        → 仅保留 deleted_at IS NULL 的数据集

Step 2  用 fieldValidation($userId)->toArray() 获取用户字段权限 slug 列表
        → 查询 dm_table_columns：is_active=1 AND deleted_at IS NULL AND chart_id IS NULL
        → 查询 dm_sql_metrics：is_custom=0 AND deleted_at IS NULL
        → 维度字段（dm_table_columns）一期默认按非受限字段处理
        → 指标字段（dm_sql_metrics）若 is_restricted=1，则 metric_name 必须在 slug 列表中，否则排除
        → 指标字段若 is_restricted=0，则直接包含
```

#### 4.2.3 一期导出数据标准结构

一期实现基于真实表结构 `dm_tables + dm_table_columns + dm_sql_metrics` 组装统一字段视图，不再依赖旧的 `dm_table_fields`。

服务端内部先组装一份**标准行结构（FieldExportRow）**，再投影为 Skill CSV 13 列：

| 字段 | 来源 | 必填 | 说明 |
|------|------|------|------|
| `dataset_id` | `dm_tables.id` | 是 | 数据集主键；服务端内部保留，用于排查和后续扩展，不进入一期 CSV |
| `dataset_alias` | `dm_tables.dataset_alias` | 是 | Skill 检索和后续 query 构造使用的主标识；为空时本期不导出该数据集 |
| `dataset_name` | `dm_tables.table_name` | 是 | 数据集名称 |
| `dataset_type` | `dm_tables.dataset_type` | 是 | 数据集类型：`db/sql/union/excel/api` |
| `dataset_category` | `dm_tables.dataset_category` | 是 | 默认值 `normal` |
| `field_name` | `dm_table_columns.column_name` 或 `dm_sql_metrics.metric_name` | 是 | 一期统一的字段英文标识；同时作为受限指标权限比对键 |
| `verbose_name` | `dm_table_columns.verbose_name` 或 `dm_sql_metrics.verbose_name` | 否 | 显示名称；为空时回退 `field_name` |
| `field_type` | 派生 | 是 | `dimension` 或 `metric` |
| `data_type` | `dm_table_columns.type` 或 `dm_sql_metrics.metric_type` | 是 | 字段/指标类型；为空时回退 `text` |
| `origin_name` | `origin_name` | 否 | 原始字段名/来源名，用于搜索增强 |
| `global_alias` | `global_alias` | 否 | 全局别名，用于搜索增强 |
| `expression` | `dm_table_columns.expression` 或 `dm_sql_metrics.expression_raw/formula_config` | 否 | 维度表达式或指标公式摘要 |
| `is_dttm` | `dm_table_columns.is_dttm` | 是 | 维度是否时间字段；指标固定为 `0` |
| `is_restricted` | `dm_sql_metrics.is_restricted` | 是 | 仅指标表有真实字段；维度固定导出 `0` |
| `description` | 字段描述优先，否则 `dm_tables.description/remarks` | 否 | 字段业务描述；字段描述缺失时可回退数据集说明 |
| `field_key` | `global_uuid` 优先，否则 `{dataset_alias}:{field_type}:{field_name}` | 是 | 唯一键；服务端内部保留，不进入一期 CSV |
| `source_table` | 派生 | 是 | `dm_table_columns` 或 `dm_sql_metrics`；服务端内部保留，不进入一期 CSV |

**关键约束：**

- 一期 Skill CSV 仍维持现有 **13 列固定结构**，避免影响已有搜索脚本与安装模板。
- `dataset_alias`、`field_name`、`field_type`、`data_type` 为导出最小必填集，任一缺失则该行跳过。
- `field_name` 的统一规则为：维度取 `column_name`，指标取 `metric_name`。后续 `cli-query` 权限校验和 AI 构造查询时均以该字段为准。
- `field_key` 仅作为服务端内部唯一键使用，不暴露给一期客户端 CSV；后续若需要做增量同步或问题定位，可直接复用。

#### 4.2.4 Skill CSV 导出列（13 列固定）

| CSV 列名 | 值来源 | 导出规则 |
|---------|--------|---------|
| `dataset_alias` | `FieldExportRow.dataset_alias` | 必填 |
| `dataset_name` | `FieldExportRow.dataset_name` | 必填 |
| `dataset_type` | `FieldExportRow.dataset_type` | 必填 |
| `dataset_category` | `FieldExportRow.dataset_category` | 必填 |
| `field_name` | `FieldExportRow.field_name` | 必填 |
| `verbose_name` | `FieldExportRow.verbose_name` | 为空回退 `field_name` |
| `field_type` | `FieldExportRow.field_type` | `dimension/metric` |
| `data_type` | `FieldExportRow.data_type` | 为空回退 `text` |
| `is_dttm` | `FieldExportRow.is_dttm` | `0/1` |
| `is_restricted` | `FieldExportRow.is_restricted` | 维度固定 `0` |
| `expression` | `FieldExportRow.expression` | 可为空 |
| `description` | `FieldExportRow.description` | 可为空 |
| `keywords` | 合并生成 | BM25 搜索字段，不可为空字符串（至少包含 dataset_alias + field_name） |

**`keywords` 合并规则：**

```python
keywords = " ".join(
    unique(
        value for value in [
            dataset_alias,
            dataset_name,
            dataset_type,
            dataset_category,
            field_name,
            verbose_name,
            origin_name,
            global_alias,
            data_type,
            description,
        ]
        if value
    )
)
```

#### 4.2.5 响应格式

沿用现有 13 列 CSV 格式（含 keywords 合并列，UTF-8 BOM），响应头：

```
Content-Type: text/csv; charset=UTF-8
Content-Disposition: attachment; filename="dataset_fields_{version}.csv"
X-Skill-Version: {当前 Manifest 版本}
X-Field-Count: {本用户可见字段总数}
```

**补充说明：**

- `Manifest.field_count` 表示发布时按基础过滤规则统计的全局导出总行数，不含用户权限裁剪。
- `X-Field-Count` 表示当前请求用户最终可见的导出行数，可能小于 `Manifest.field_count`。
- 文件名不包含 `userId`，避免在缓存目录和日志中暴露用户标识。

#### 4.2.6 是否满足构建查询 JSON

**结论：当前 13 列 Skill CSV 不满足直接构建完整查询 JSON，只满足字段搜索和字段选择。**

原因是 Python 查询服务的最小请求体除字段清单外，还依赖以下数据集级元信息：

| 查询 JSON 位置 | 是否能由 13 列 CSV 提供 | 说明 |
|------|------|------|
| `query.from.alias` | 是 | 可由 `dataset_alias` 提供 |
| `query.select[].expr` | 部分满足 | 可拼接简单字段 `ds_alias.field_name`；复杂表达式场景不稳定 |
| `query.select[].aggregation` | 否 | 当前未导出默认聚合函数 |
| `query.from.table` | 否 | 当前未导出可执行 SQL / table 模板 |
| `query.from.database` | 否 | 当前未导出数据库名 |
| `query.from.permission` | 否 | 当前未导出权限维度数组 |
| `query.where` | 部分满足 | 可基于 `field_name` 构造，但缺少 translate 映射 |
| `query.innerWhere` | 否 | 当前无法判断 `inner_where_enabled` 和层级结构 |
| `dataComparison.field` | 部分满足 | 仅可通过 `is_dttm=1` 猜测，缺少稳定主时间字段 |
| `tableId` | 否 | `cli-query` 权限校验必需，当前未导出到客户端文件 |

因此，一期应拆分为两类导出：

- **Skill Search CSV（现有 13 列）**：给 AI 搜索字段、理解字段语义
- **Query Metadata Export（新增）**：给 AI/opscli 构建可执行 query JSON

#### 4.2.7 一期新增：Query Metadata 最小导出清单

建议新增一个**面向构建查询 JSON 的元数据导出结构**，可为 JSON 接口或附加 CSV/JSON 文件；推荐 JSON。

**Dataset 级最小字段：**

| 字段 | 来源 | 必填 | 用途 |
|------|------|------|------|
| `table_id` | `dm_tables.id` | 是 | `cli-query` 顶层 `tableId` |
| `dataset_alias` | `dm_tables.dataset_alias` | 是 | `query.from.alias` |
| `dataset_name` | `dm_tables.table_name` | 是 | 展示/调试 |
| `from_table` | `dm_tables.default_endpoint` 或可执行 SQL 模板 | 是 | `query.from.table` |
| `database` | 由 `database_id` 关联数据源配置得到 | 是 | `query.from.database` |
| `data_source` | 数据源标识，如 `doris_analytics` | 是 | 请求顶层 `dataSource` |
| `permission` | `dm_tables.permission` | 否 | `query.from.permission` 数组 |
| `inner_where_enabled` | `dm_tables.inner_where_enabled` | 是 | 决定使用 `where` 还是 `innerWhere` |
| `main_dttm_col` | `dm_tables.main_dttm_col` | 否 | `dataComparison.field` 默认时间字段 |
| `cache_timeout` | `dm_tables.cache_timeout` | 否 | `query.cacheControl.ttl` 默认值 |
| `dataset_type` | `dm_tables.dataset_type` | 是 | 查询模式判定辅助 |

**Field 级最小字段：**

| 字段 | 来源 | 必填 | 用途 |
|------|------|------|------|
| `field_key` | 内部统一键 | 是 | 稳定引用、排查问题 |
| `dataset_alias` | 继承 | 是 | 组装 `expr/field` |
| `field_name` | 统一字段名 | 是 | `select`/`where` 目标字段 |
| `field_type` | `dimension/metric` | 是 | 决定是否进 `groupBy` |
| `expression` | 真实表达式/公式摘要 | 否 | 复杂 select 候选 |
| `default_aggregation` | 由 `field_config`、指标规则或约定推导 | 否 | 普通 metric 的 `aggregation` |
| `is_dttm` | 现有字段 | 是 | 时间字段候选 |
| `translate` | 过滤翻译枚举 | 否 | where 叶子节点 `translate` |
| `filterable` | 维度取 `dm_table_columns.filterable`；指标默认 `0` | 是 | 是否允许进入过滤条件 |
| `groupable` | 维度取 `dm_table_columns.groupby`；指标默认 `0` | 是 | 是否允许进入 `groupBy` |
| `is_restricted` | 现有字段 | 是 | 查询前权限提示 |

#### 4.2.8 推荐新增接口

为避免破坏现有 Skill 兼容性，一期建议**不改 13 列 CSV 接口**，改为新增元数据接口：

| 接口 | 用途 |
|------|------|
| `GET /api/v1/data-metrics/datasets/skill/export` | 保持现状，输出 13 列搜索 CSV |
| `GET /api/v1/data-metrics/datasets/query-metadata` | 新增，输出用户授权范围内的可执行查询元数据 JSON |

`query-metadata` 响应建议结构：

```json
{
  "datasets": [
    {
      "table_id": 1288,
      "dataset_alias": "sale_order_d",
      "dataset_name": "销售订单日汇总",
      "from_table": "(SELECT ...)",
      "database": "",
      "data_source": "doris_analytics",
      "permission": ["channel_uuid", "listing_uuid"],
      "inner_where_enabled": true,
      "main_dttm_col": "date_id",
      "cache_timeout": 300
    }
  ],
  "fields": [
    {
      "field_key": "sale_order_d:dimension:platform_name",
      "table_id": 1288,
      "dataset_alias": "sale_order_d",
      "field_name": "platform_name",
      "field_type": "dimension",
      "expression": null,
      "default_aggregation": null,
      "is_dttm": 0,
      "translate": "PLATFORM_TO_SKU",
      "filterable": 1,
      "groupable": 1,
      "is_restricted": 0
    }
  ]
}
```

#### 4.2.9 `query-metadata` 服务端组装规则

**Dataset 级组装规则：**

| 输出字段 | 组装规则 |
|------|------|
| `table_id` | 直接取 `dm_tables.id` |
| `dataset_alias` | 直接取 `dm_tables.dataset_alias`，为空则整表跳过 |
| `dataset_name` | 取 `dm_tables.table_name` |
| `from_table` | 优先取可直接用于 Python 查询的 SQL/表模板；一期优先使用 `dm_tables.default_endpoint`，若为空则回退到服务端现有 QueryBuilder 可解析结构 |
| `database` | 通过 `database_id` 关联数据源配置解析；若 `from_table` 为子查询 SQL，则允许返回空串 `\"\"` |
| `data_source` | 从数据源配置映射得到，如 `doris_analytics` |
| `permission` | 取 `dm_tables.permission` JSON；若为空则返回空数组 `[]` |
| `inner_where_enabled` | 直接取 `dm_tables.inner_where_enabled`，布尔化输出 |
| `main_dttm_col` | 取 `dm_tables.main_dttm_col`；为空时允许返回 `null` |
| `cache_timeout` | 取 `dm_tables.cache_timeout`；为空时允许返回 `null` |

**Field 级组装规则：**

| 输出字段 | 维度规则 | 指标规则 |
|------|------|------|
| `field_key` | `global_uuid` 优先，否则 `{dataset_alias}:dimension:{column_name}` | `global_uuid` 优先，否则 `{dataset_alias}:metric:{metric_name}` |
| `field_name` | `column_name` | `metric_name` |
| `field_type` | 固定 `dimension` | 固定 `metric` |
| `expression` | `expression` | `expression_raw` 优先，否则 `formula_config` 摘要 |
| `default_aggregation` | `null` | 从 `field_config.aggregationType` 推导，取不到时按指标类型约定推默认值 |
| `is_dttm` | `is_dttm` | 固定 `0` |
| `translate` | 由字段映射规则推导，取不到时 `null` | 一般为 `null` |
| `filterable` | 取 `dm_table_columns.filterable` | 固定 `0` |
| `groupable` | 取 `dm_table_columns.groupby` | 固定 `0` |
| `is_restricted` | 固定 `0` | 取 `dm_sql_metrics.is_restricted` |

**默认聚合函数推导建议：**

| 场景 | `default_aggregation` |
|------|------|
| `field_config.aggregationType` 有值 | 直接使用 |
| 数值类指标（金额/数量/次数） | `SUM` |
| 占比/率值类指标 | `AVG` 或 `null`，由服务端明确映射 |
| 无法可靠判断 | `null`，由 AI/调用方显式指定 |

#### 4.2.10 `query-metadata` 权限与过滤规则

`query-metadata` 必须与 `skill/export` 保持同口径的用户权限过滤：

1. 仅返回 `getCombinedDataSetIds($userId)` 范围内的数据集
2. 仅返回 `deleted_at IS NULL` 且 `dataset_alias` 非空的数据集
3. 维度字段仅返回 `is_active=1 AND deleted_at IS NULL AND chart_id IS NULL`
4. 指标字段仅返回 `is_custom=0 AND deleted_at IS NULL`
5. `is_restricted=1` 的指标，只有当 `metric_name` 在 `fieldValidation($userId)` 返回的 slug 列表中时才可返回
6. 返回的 `datasets` 与 `fields` 必须相互一致，禁止出现字段引用到未返回的数据集

#### 4.2.11 `query-metadata` 服务端伪代码

```php
public function queryMetadata(Request $request): JsonResponse
{
    $user = auth()->user();
    $userId = $user->id;

    $allowedDatasetIds = (new UserOrm())->getCombinedDataSetIds($userId);
    $fieldPermissions = collect((new AuthService())->fieldValidation($userId)->toArray());

    $tables = DmTable::query()
        ->whereIn('id', $allowedDatasetIds)
        ->whereNull('deleted_at')
        ->whereNotNull('dataset_alias')
        ->where('dataset_alias', '!=', '')
        ->get();

    $tableIds = $tables->pluck('id');

    $columns = DmTableColumn::query()
        ->whereIn('table_id', $tableIds)
        ->where('is_active', 1)
        ->whereNull('deleted_at')
        ->whereNull('chart_id')
        ->get();

    $metrics = DmSqlMetric::query()
        ->whereIn('table_id', $tableIds)
        ->where('is_custom', 0)
        ->whereNull('deleted_at')
        ->get()
        ->filter(function ($metric) use ($fieldPermissions) {
            return !$metric->is_restricted || $fieldPermissions->contains($metric->metric_name);
        });

    return response()->json([
        'datasets' => $this->buildDatasets($tables),
        'fields' => $this->buildFields($tables, $columns, $metrics),
    ]);
}
```

#### 4.2.12 后端实现结构建议

建议沿用现有 `DatasetSkillController + DatasetFieldsExportService` 体系，并补充清晰的 DTO / 映射层：

| 层级 | 建议类/方法 | 职责 |
|------|------|------|
| Controller | `DatasetSkillController::queryMetadata()` | 认证、调用服务、返回 JSON |
| Service | `DatasetFieldsExportService::buildQueryMetadataForUser($userId)` | 统一组织 datasets / fields 元数据 |
| Mapper | `QueryMetadataDatasetMapper` | 将 `dm_tables` 映射为 dataset DTO |
| Mapper | `QueryMetadataFieldMapper` | 将 `dm_table_columns` / `dm_sql_metrics` 映射为 field DTO |
| Policy/Resolver | `QueryMetadataTranslateResolver` | 维护 `field_name -> translate` 枚举映射 |
| Policy/Resolver | `DefaultAggregationResolver` | 维护指标默认聚合推导逻辑 |
| DTO | `QueryMetadataResponse` | 顶层响应结构 |
| DTO | `QueryMetadataDatasetItem` | dataset 项结构 |
| DTO | `QueryMetadataFieldItem` | field 项结构 |

**推荐方法签名：**

```php
class DatasetFieldsExportService
{
    public function buildQueryMetadataForUser(int $userId): array;

    /** @return array<int, array<string, mixed>> */
    protected function buildQueryMetadataDatasets(Collection $tables): array;

    /** @return array<int, array<string, mixed>> */
    protected function buildQueryMetadataFields(
        Collection $tables,
        Collection $columns,
        Collection $metrics,
        Collection $fieldPermissions,
    ): array;
}
```

#### 4.2.13 字段映射表（开发落地版）

**Dataset DTO 映射：**

| DTO 字段 | 表字段/来源 | 备注 |
|------|------|------|
| `table_id` | `dm_tables.id` | 主键 |
| `dataset_alias` | `dm_tables.dataset_alias` | 非空约束 |
| `dataset_name` | `dm_tables.table_name` | 展示名 |
| `from_table` | `dm_tables.default_endpoint` / QueryBuilder 配置 | 需保证可用于 Python 查询 |
| `database` | `database_id` 关联配置 | 子查询可空串 |
| `data_source` | 数据源配置映射 | 如 `doris_analytics` |
| `permission` | `dm_tables.permission` | JSON 数组化 |
| `inner_where_enabled` | `dm_tables.inner_where_enabled` | bool |
| `main_dttm_col` | `dm_tables.main_dttm_col` | 可空 |
| `cache_timeout` | `dm_tables.cache_timeout` | 可空 |

**Field DTO 映射：**

| DTO 字段 | 维度来源 | 指标来源 |
|------|------|------|
| `field_key` | `global_uuid` 或拼接键 | `global_uuid` 或拼接键 |
| `table_id` | `table_id` | `table_id` |
| `dataset_alias` | 由 `table_id` 反查 | 由 `table_id` 反查 |
| `field_name` | `column_name` | `metric_name` |
| `field_type` | `dimension` | `metric` |
| `expression` | `expression` | `expression_raw` / `formula_config` |
| `default_aggregation` | `null` | `field_config.aggregationType` 优先 |
| `is_dttm` | `is_dttm` | `0` |
| `translate` | `QueryMetadataTranslateResolver` 推导 | `null` |
| `filterable` | `filterable` | `0` |
| `groupable` | `groupby` | `0` |
| `is_restricted` | `0` | `is_restricted` |

---

### 4.3 版本感知接口（确认可用）

以下接口在技术方案中已定义，本期确认实现或同步实现：

| 接口 | 说明 |
|------|------|
| `GET /api/v1/data-metrics/datasets/skill/manifest` | 获取版本 Manifest（轻量，仅元数据） |
| `POST /api/v1/data-metrics/datasets/skill/publish` | 管理员发布新版本，写入 system_constant |

---

## 5. 模块二：opscli 客户端

### 5.1 skills 命令组

在 `opscli/cli.py` 注册新命令组，模块路径：`opscli/skills/`

```bash
# 默认输出 JSON（AI 工具 / 脚本调用）
opscli skills install [skill-name]          # 安装指定 Skill；不指定则列出可安装清单（JSON）
opscli skills upgrade [skill-name]          # 升级指定或全部 Skill（JSON）
opscli skills upgrade --force               # 强制重新下载（JSON）
opscli skills list                          # 列出已安装 Skill 及版本状态（JSON）
opscli skills status                        # 检查更新状态（JSON）

# 终端友好输出（人工阅读）
opscli skills install [skill-name] --pretty
opscli skills upgrade --pretty
opscli skills upgrade --force --pretty
opscli skills list --pretty
opscli skills status --pretty
```

**CLI 注册（在 `opscli/cli.py` 追加一行）：**

```python
from opscli.skills.cli import app as skills_app
app.add_typer(skills_app, name="skills")
```

---

### 5.2 skills install 详细设计

#### 5.2.1 SKILL.md 模板来源

SKILL.md 模板**内置于 opscli 包**（硬编码），install 时直接从包内写入目标目录，无需服务端提供模板下载接口。

模板位置：`opscli/skills/templates/{skill-name}/SKILL.md`

当前内置模板：`dataset-fields`（`opscli/skills/templates/dataset-fields/SKILL.md`）

#### 5.2.2 多工具安装支持

**首次安装时，交互式询问用户要安装到哪些 AI 工具：**

```
$ opscli skills install dataset-fields

检测到已安装的 AI 工具：
  [1] Claude Code   (~/.claude/skills/)          ✓ 已检测到
  [2] OpenClaw      (~/.openclaw/skills/)         ✓ 已检测到
  [3] OpenCode      (~/.config/opencode/commands/) ✗ 未检测到

请选择安装目标（多选，逗号分隔，直接回车默认选全部已检测到的）: 1,2
```

工具检测规则（按优先级）：
- `~/.claude/` 目录存在 或 `which claude` 可用 → Claude Code（Tier 1）
- `~/.openclaw/` 目录存在 或 `which openclaw` 可用 → OpenClaw（Tier 1）
- `~/.config/opencode/` 目录存在 或 `which opencode` 可用 → OpenCode（Tier 2，仅写 SKILL.md 描述）

详细工具路径规则见 [opscli多工具Skills支持调研规划.md](opscli多工具Skills支持调研规划.md)。

#### 5.2.3 install 写入内容

```
{target_skills_dir}/{skill-name}/
├── SKILL.md                   # 从 opscli 包内置模板复制
├── data/
│   ├── VERSION.json           # {"version": "v0.0.0"}（初始值，首次 upgrade 后更新）
│   └── dataset_fields.csv     # 只含表头的空文件
└── scripts/
    ├── updater.py             # 从 opscli 包内置复制
    ├── core.py                # 从 opscli 包内置复制
    └── search.py              # 从 opscli 包内置复制
```

install 完成后提示用户执行 `opscli skills upgrade` 拉取真实数据。

---

### 5.3 Skill 发现机制

#### 5.3.1 升级时的扫描路径

`opscli skills upgrade` 扫描以下所有路径（不互斥，全部扫描）：

| 优先级 | 路径 | 说明 |
|--------|------|------|
| ① | `--skills-dir` 参数指定路径 | 显式覆盖，仅扫描此路径 |
| ② | `OPSCLI_SKILLS_DIR` 环境变量 | 仅扫描此路径 |
| ③ | `{当前目录}/.claude/skills/` | 项目级（Claude Code） |
| ④ | `~/.claude/skills/` | 全局（Claude Code） |
| ⑤ | `~/.openclaw/skills/` | 全局（OpenClaw，若已安装） |

> `--skills-dir` 和 `OPSCLI_SKILLS_DIR` 任一存在时，仅扫描指定路径，跳过其余。

**扫描条件：** 子目录中存在 `data/VERSION.json` 文件。

---

### 5.4 dataset-fields Skill 升级流程

```
opscli skills upgrade [dataset-fields]
    │
    ├─ 扫描发现所有目标 Skill 路径（见 5.3.1）
    │
    ├─ get_token("ops")              # AuthClient 获取 JWT
    ├─ get_session("ops")            # 获取 session_id
    │
    ├─ GET /datasets/skill/manifest  # 携带 JWT + polarisUserToken cookie
    │   拉取远端版本 Manifest
    │
    ├─ 读取本地 data/VERSION.json    # 对比本地版本
    │
    ├─ [版本相同且非 --force] → 打印"已是最新"，退出
    │
    └─ [有更新 或 --force]
           ├─ GET /datasets/skill/export   # 拉取用户授权数据集 CSV
           │   携带 JWT + polarisUserToken cookie
           │   响应：仅含当前用户有权限的数据集+字段
           │
           ├─ 流式写入临时文件（避免下载中断损坏现有 CSV）
           ├─ shutil.move() 原子替换 dataset_fields.csv
           └─ 写入 VERSION.json
```

**终端输出示例（`--pretty` 模式）：**

```
$ opscli skills upgrade --pretty

扫描 Skills 目录：
  ~/.claude/skills/       → 发现 1 个 Skill
  ~/.openclaw/skills/     → 发现 1 个 Skill

┌─────────────────┬──────────┬──────────┬──────────────────────┐
│ Skill           │ 本地版本 │ 远端版本 │ 状态                 │
├─────────────────┼──────────┼──────────┼──────────────────────┤
│ dataset-fields  │ v0.1.0   │ v0.1.2   │ ✦ 有更新             │
└─────────────────┴──────────┴──────────┴──────────────────────┘

正在更新 dataset-fields (v0.1.0 → v0.1.2)...
  [claude-code]  下载 dataset_fields_v0.1.2.csv [████████████] ✓
  [openclaw]     复制到 ~/.openclaw/skills/dataset-fields/ ✓
  字段数：1247（本用户可见）

更新完成：1 个已更新，0 个已是最新，0 个失败。
```

---

### 5.5 新增模块结构

```
opscli/
└── skills/
    ├── __init__.py
    ├── cli.py              # Typer 命令组（install/upgrade/list/status）+ --pretty 支持
    ├── manager.py          # SkillsManager（发现/安装/升级逻辑）
    ├── updater.py          # 版本检查 + 流式下载 + 原子替换
    ├── models.py           # SkillInfo、ToolInfo 数据类
    ├── detector.py         # ToolDetector（多 AI 工具检测）
    └── templates/
        └── dataset-fields/
            ├── SKILL.md        # 内置模板
            └── scripts/
                ├── updater.py
                ├── core.py
                └── search.py
```

---

## 6. 关键约束

| # | 约束 | 说明 |
|---|------|------|
| 1 | **权限隔离** | `/skill/export` 必须返回用户个人授权范围内的数据集和字段，绝不返回全量 |
| 2 | **受限字段拒绝** | 用户请求含无权限受限字段时，返回 403 并明确列出字段名；不做静默过滤 |
| 3 | **认证复用** | auto-scheduler 接口复用现有鉴权中间件（JWT + session cookie），无需新增认证逻辑 |
| 4 | **opscli 认证** | opscli 统一通过 `AuthClient().get_token("ops")` + `get_session("ops")` 获取凭证，不引入新认证方式 |
| 5 | **原子性** | CSV 更新必须先写临时文件再 `shutil.move()` 原子替换，禁止直接覆盖写入 |
| 6 | **静默降级** | Layer 1（AI 调用时触发的自动更新）任何异常均需捕获并降级到本地缓存，不抛出异常 |
| 7 | **输出统一** | 所有 `opscli skills` 命令**默认输出 JSON**，支持 `--pretty` 切换终端文字，JSON 结构遵循第 3 章规范 |
| 8 | **模块隔离** | skills 模块接入遵循 CLAUDE.md 铁律1，不修改 auth 或其他现有模块 |
| 9 | **SKILL.md 内置** | install 使用 opscli 包内置模板，服务端无需提供模板下载接口 |
| 10 | **多工具扫描** | upgrade 同时扫描 Claude Code 和 OpenClaw（Tier 1）的 Skills 目录 |
| 11 | **导出结构稳定** | 一期 Skill CSV 固定 13 列，不额外新增 `dataset_id/field_key/source_table` 到客户端文件，避免破坏现有 Skill 脚本兼容性 |
| 12 | **真实表对齐** | 一期字段导出仅基于 `dm_tables + dm_table_columns + dm_sql_metrics`；`dm_sql_metrics.is_custom=1`、`deleted_at IS NOT NULL`、`dm_table_columns.chart_id IS NOT NULL`、`is_active=0` 数据不得导出 |
| 13 | **字段名统一口径** | 导出字段名与权限校验口径统一为：维度=`column_name`，指标=`metric_name` |
| 14 | **计数口径明确** | Manifest 中 `field_count` 为发布时全局统计值；导出响应头 `X-Field-Count` 为用户可见值，二者允许不相等 |

---

## 7. 验收标准

| 场景 | 预期结果 |
|------|---------|
| 用户无权限数据集发起 cli-query | 返回 403：`无该数据集访问权限` |
| 用户对受限字段无权限发起 cli-query | 返回 403：`以下字段无查看权限：order_cost、supplier_price` |
| 用户有权限数据集 + 无受限字段请求 | 正常透传 Python 服务，返回查询数据 |
| `GET /skill/export` 请求 | 仅返回用户有权限的数据集字段，受限字段无权限者不在 CSV 中 |
| `GET /skill/export` 请求返回的 CSV | 列头固定为 13 列，包含 `keywords`，且不包含 `dataset_id`、`field_key` 等内部字段 |
| 导出维度字段 | 来源于 `dm_table_columns`，必须满足 `is_active=1`、`deleted_at IS NULL`、`chart_id IS NULL` |
| 导出指标字段 | 来源于 `dm_sql_metrics`，必须满足 `is_custom=0`、`deleted_at IS NULL` |
| 维度/指标命名 | 维度 `field_name=column_name`，指标 `field_name=metric_name`，与权限判断口径一致 |
| `keywords` 生成 | 至少包含 `dataset_alias + field_name`，其余按非空值合并去重 |
| `opscli skills install dataset-fields` | 交互式询问目标工具 → 在选中工具目录创建 Skill 结构，含空 CSV 和 `v0.0.0` 版本文件 |
| `opscli skills upgrade` | 扫描所有工具 Skills 目录 → 拉取用户授权 CSV → 版本更新 → 打印汇总 |
| `opscli skills upgrade --force` | 强制重新下载，忽略版本比对 |
| `opscli skills upgrade` | 默认输出标准 JSON，符合第 3 章规范 |
| `opscli skills upgrade --pretty` | 输出终端友好文字，含进度条和表格 |
| `opscli skills list` | 默认输出标准 JSON |
| 网络不通时 AI 调用 Skill（Layer 1 自动更新） | 静默降级，使用本地缓存，不抛出异常，不影响搜索功能 |
| 安装了 OpenClaw 时执行 upgrade | 同时更新 `~/.openclaw/skills/dataset-fields/` 下的 CSV |

---

## 8. 参考文档

| 文档 | 路径 |
|------|------|
| 数据集字段技能系统技术方案 | `docs/数据集字段技能系统技术方案.md` |
| 通用 Skill 版本控制架构 | `docs/通用Skill版本控制架构.md` |
| opscli 多工具 Skills 支持调研规划 | `docs/opscli多工具Skills支持调研规划.md` |
| 数据查询服务开发说明文档 | `auto-scheduler/docs/1/数据查询服务开发说明文档.md` |
| opscli CLAUDE.md（开发铁律） | `opscli/CLAUDE.md` |
