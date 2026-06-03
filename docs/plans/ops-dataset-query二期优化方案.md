# ops-dataset-query 二期优化方案

> **文档版本**：v1.0  
> **创建日期**：2026-06-02  
> **适用范围**：opscli `ops-dataset-query` Skill 客户端优化 + `auto-scheduler/data-metrics` 服务端查询能力开发  
> **范围说明**：服务端仅涉及数据查询能力和数据表设计，不做后台管理 UI

---

## 一、背景与现状

### 1.1 一期成果回顾

一期完成了取数底座的核心能力：

- `opscli query simple` / `query_simple` MCP 工具查询入口
- `opscli query intent` 远端 Catalog 意图匹配
- `opscli skills upgrade ops-dataset-query` 本地数据升级
- SKILL.md 14条铁律 + QUERY_SPEC.md 13条规范
- `ops-feedback` 查询闭环反馈机制

### 1.2 现状差距分析

| 层次 | 现状 | 关键缺口 |
|------|------|---------|
| **结构化产物** | 草案已完成（intent_taxonomy v1.2，16个意图，6个业务域） | 仅存草案目录，未落地到 Skill，未被任何流程消费 |
| **opscli Skill 模板** | `data_state=placeholder`，rules 规则文档完备 | 缺 `dataset_profiles.yml`、`field_semantic_index.yml`、本地路由脚本 |
| **服务端 Catalog** | `dm_dataset_query_intents` 表已存在，`buildDatasetCatalogForUser` 已实现 | `avoid_when`/`clarify_when`/`routing_status`/`hard_constraints` 字段缺失 |
| **服务端字段元数据** | `dm_table_columns` 有 groupby/filterable/is_dttm | 无 `snapshot_metric`/`formula_config`/`semantic_tags` |
| **服务端关系图谱** | `TableRelation` 模型存在 | 关系类型不完整，无 API 端点暴露给客户端 |
| **字段语义解析** | rules.md 有人工规则，search.py 做关键词搜索 | 无系统化语义索引，无法处理 SP/库存/销售额等多义词消歧 |

### 1.3 二期优化目标

```
当前：用户问题 → 远端 Catalog 匹配 → 未命中 → 关键词搜索（精度差）
目标：用户问题 → 远端 Catalog 匹配 → 未命中 → 本地意图路由 → 语义字段解析 → Query Plan → 执行
```

核心目标分三层：

1. **语义准确率提升**：引入本地意图路由 + 字段语义索引，减少误选数据集和误选字段
2. **业务约束自动化**：快照字段禁聚合、公式字段禁二次聚合从"规则文本"变成"代码门禁"
3. **跨端数据一致**：服务端管理 intent 约束和字段语义，客户端通过 skills_upgrade 同步，避免双端维护漂移

---

## 二、客户端（opscli）优化方案

### 2.1 P0 — 结构化产物落地到 `data/` 目录

**现状**：草案文件存在 WeWork 缓存目录（`ops-dataset-query-structured-artifacts/`），没有任何代码消费。

**操作**：将以下文件写入 `opscli/skills/templates/ops-dataset-query/data/`：

| 文件 | 来源 | 用途 |
|------|------|------|
| `intent_taxonomy.yml` | 草案目录 | 16个业务意图分类，trigger_keywords，业务域 |
| `dataset_profiles.yml` | 草案目录 | 数据集画像：routing_status、hard_constraints、clarify_when、avoid_when |
| `dataset_relationships.yml` | 草案目录 | 数据集关联图谱：主从/合并/替代/下钻/禁止直连 |
| `field_semantic_index.yml` | 草案目录 | 字段语义索引：SP歧义、快照字段、公式字段消歧 |
| `routing_eval_cases.yml` | 草案目录 | 路由回归测试用例 |
| `query_plan.schema.json` | 草案目录 | 查询计划标准结构 |

**同步更新** `data/VERSION.json`：

```json
{
  "name": "ops-dataset-query",
  "version": "1.1.0",
  "data_state": "ready"
}
```

**验收标准**：`opscli skills list` 显示版本 1.1.0，`data_state=ready`，`scripts/search.py` 能正常读取 datasets.csv。

---

### 2.2 P0 — 新增 `scripts/route_intent.py` 本地意图路由脚本

**现状痛点**：远端 catalog 未命中时直接跌落到 search.py 关键词搜索，无法处理：
- `embedded_intent` 映射（即时销售 → 即时综合中的 order_sale_trend_set）
- `avoid_when` 拦截（SP词组分析不能用SP广告数据集）
- `clarify_when` 触发（用户说"SP"无法判断 SPU 还是 Sponsored Products）

**脚本接口**：

```
python scripts/route_intent.py "<用户自然语言问题>" [--top-n 3]
```

**内部流程**：

```
1. 加载 data/intent_taxonomy.yml
2. 按 trigger_keywords、business_domain、analysis_intent 对用户问题打分召回候选意图
3. 读取 data/dataset_profiles.yml，对每个候选意图：
   a. 检查 routing_status
      - embedded_intent → 填入 execution_dataset（parent_dataset），记录口径映射说明
      - direct_intent → 直接使用 table_id / dataset_alias
   b. 检查 avoid_when → 若命中，降低候选权重或标记为不适用
   c. 检查 clarify_when → 若命中，置 requires_clarification=true，填写 clarification_reasons
   d. 检查 hard_constraints → 填入响应供 AI 使用
4. 按权重排序，返回 top-N 候选
```

**输出格式**（JSON，与服务端 catalog intent 结构对齐）：

```json
{
  "query": "近30天各部门销售额",
  "top_results": [
    {
      "rank": 1,
      "intent_id": "billing_sales_review",
      "intent_name": "账单销售复盘",
      "primary_dataset": "账单销售数据集",
      "execution_dataset": "账单销售数据集",
      "execution_alias": "ds_9e288aa0df06",
      "table_id": 2,
      "confidence": 0.87,
      "matched_keywords": ["销售额", "部门"],
      "requires_clarification": false,
      "clarification_reasons": [],
      "hard_constraints": ["已售天数字段只能用于明细表或无聚合过滤条件"]
    }
  ]
}
```

**SKILL.md 联动**：Catalog 未命中时，优先调用 `python scripts/route_intent.py`，再回退到 `search.py`。

---

### 2.3 P1 — 新增 `scripts/build_query_plan.py` 查询计划生成器

**动机**：SKILL.md 铁律十要求查询前生成 Query Plan，但目前没有脚本支撑，完全依赖 AI 按规则文本推断，缺乏一致性。

**脚本接口**：

```
python scripts/build_query_plan.py \
  --intent-result <route_intent 输出文件或 JSON string> \
  --user-query "<用户问题>" \
  --dimensions "dept_name,asin" \
  --metrics "sale_amount,ad_cost" \
  --filters "date_range=2026-05-01~2026-05-31"
```

**内部流程**：

```
1. 接收 route_intent 输出（含 execution_alias、intent_id、hard_constraints）
2. 从 data/field_semantic_index.yml 查用户指定字段的候选字段和消歧规则
3. 从 data/dataset_fields.csv 或 query_metadata.json 校验字段存在性
4. 对每个字段标记：
   - formula_field=true → 不传 aggregation
   - snapshot_field=true → 禁聚合，只能明细表
   - formula_config.summary_expression 存在 → 使用 summary_expression
5. 检查所有 hard_constraints 是否满足
6. 若存在 requires_clarification → 输出澄清项，不输出可执行查询参数
7. 按 query_plan.schema.json 结构输出完整查询计划
```

**输出示例**：

```json
{
  "user_query": "近30天各部门销售额",
  "intent_id": "billing_sales_review",
  "table_id": 2,
  "dataset_alias": "ds_9e288aa0df06",
  "execution_dataset": "账单销售数据集",
  "requires_clarification": false,
  "dimensions": ["dept_name"],
  "metrics": [
    {
      "field": "sale_amount",
      "formula_field": false,
      "aggregation": "SUM"
    }
  ],
  "filters": [
    {
      "field": "date",
      "operator": "between",
      "value": ["2026-05-02", "2026-05-31"]
    }
  ],
  "hard_constraints_checked": true,
  "warnings": []
}
```

---

### 2.4 P1 — `references/rules.md` 补充字段语义索引利用流程

**现状**：rules.md 是规则集，没有描述如何利用 `field_semantic_index.yml`，AI 仍在做纯关键词搜索。

**新增内容**（补充到第零章澄清总则后）：

```markdown
## 零-A、字段语义解析流程（强制）

在用字段名构造查询前，必须按以下顺序解析：

1. 先在 data/field_semantic_index.yml 中查 semantic_groups
2. 按 business_domain 过滤候选字段（而非只做字段名关键词匹配）
3. 命中多个候选 → 走 clarify_when 规则，使用 AskUserQuestion 确认
4. 命中 formula_rule=true 字段（如 ACOS/ROAS/转化率）→ 标记 no_aggregation=true，不传 aggregation
5. 命中 snapshot_rule=true 字段（如 总库存/海外仓库存/在途库存）→ 标记 snapshot_only=true，仅用于明细或无聚合条件查询
6. 再通过 dataset_fields.csv 或 query_metadata 校验字段真实存在（字段语义索引只负责候选推荐，不替代存在性校验）

特别注意以下多义词（必须澄清）：
- SP → 可能是 SPU 产品编码，也可能是 Sponsored Products 广告
- 销售额 → 广告销售额、总销售额、账单销售额含义不同
- 库存 → 物控库存、快照库存、补货库存含义不同
- 转化率 → 广告转化率、自然转化率含义不同
```

---

### 2.5 P1 — SKILL.md 补充本地路由回退链描述

**新增到铁律三（Catalog 意图匹配）后**：

```markdown
### 铁律三-B：Catalog 未命中完整回退链

远端 Catalog 未命中时，按以下顺序回退（禁止直接跳到 search.py）：

1. 远端 catalog (query_intent_match / opscli query intent) → 命中 → 遵循 intent_constraints
   ↓ 未命中（静默，不向用户提示）
2. 本地 intent_taxonomy.yml 关键词匹配 (scripts/route_intent.py)
   → 命中 direct_intent → 正常路由到 table_id / dataset_alias
   → 命中 embedded_intent → 使用 execution_dataset 执行，输出口径映射说明
   → 命中 requires_clarification=true → 先用 AskUserQuestion 澄清，不执行查询
   ↓ 未命中
3. search.py 本地关键词搜索（现有逻辑）
   → 匹配到1个 → AskUserQuestion 确认后执行
   → 匹配到≥2个 → AskUserQuestion 列出候选
   → 匹配到0个 → 提示无匹配，询问是否查看全量数据集列表
```

---

### 2.6 P2 — `scripts/updater.py` 扩展拉取新数据端点

当服务端新增 API 端点后，updater.py 需同步支持拉取：

| 新增端点 | 本地写入文件 |
|----------|------------|
| `GET /api/v1/data-metrics/datasets/skill/field-semantic-index` | `data/field_semantic_index.yml` |
| `GET /api/v1/data-metrics/datasets/skill/relationships` | `data/dataset_relationships.yml` |
| `GET /api/v1/data-metrics/datasets/skill/intent-profiles` | `data/dataset_profiles.yml` |

**扩展策略**：在 `SkillsUpdater.fetch_manifest()` 增加版本对比，如果服务端 manifest 中包含 `has_semantic_index=true` 才触发下载（避免对旧版本服务端的兼容性问题）。

---

### 2.7 客户端文件变更汇总

```
opscli/skills/templates/ops-dataset-query/
├── data/
│   ├── VERSION.json                  ← 版本从 1.0.2 升到 1.1.0，data_state=ready
│   ├── dataset_profiles.yml          ← 新增（从草案目录落地）
│   ├── dataset_relationships.yml     ← 新增（从草案目录落地）
│   ├── field_semantic_index.yml      ← 新增（从草案目录落地，后续由服务端维护）
│   ├── intent_taxonomy.yml           ← 新增（从草案目录落地）
│   ├── routing_eval_cases.yml        ← 新增（从草案目录落地）
│   ├── query_plan.schema.json        ← 新增（从草案目录落地）
│   ├── dataset_fields.csv            ← 已有（placeholder → 正式数据）
│   ├── datasets.csv                  ← 已有
│   └── dataset_select_columns.csv    ← 已有
├── references/
│   ├── rules.md                      ← 修改：补充字段语义解析流程（零-A章节）
│   ├── simple-query-guide.md         ← 已有，无需改动
│   ├── cli.md                        ← 已有，无需改动
│   └── mcp.md                        ← 已有，无需改动
├── scripts/
│   ├── route_intent.py               ← 新增（本地意图路由）
│   ├── build_query_plan.py           ← 新增（查询计划生成）
│   ├── updater.py                    ← 修改：新增字段语义索引/关系图谱拉取
│   ├── search.py                     ← 已有，无需改动
│   └── query.py                      ← 已有，无需改动
├── SKILL.md                          ← 修改：补充铁律三-B（本地路由回退链）
└── QUERY_SPEC.md                     ← 已有，无需改动
```

---

## 三、服务端（data-metrics）开发方案

> **范围**：仅数据查询能力 + 数据表结构设计，不涉及后台管理 UI。

### 3.1 P0 — `dm_dataset_query_intents` 表扩展

**现状**：该表已存在，已有 `intent_code/keywords/recommended_dimensions/default_filters/comparison_strategy` 等字段。对比草案 `dataset_profiles.yml` 有以下关键字段缺失，导致客户端无法获得完整业务约束。

**Migration**：

```php
Schema::connection('ops_metrics')->table('dm_dataset_query_intents', function (Blueprint $table) {
    $table->enum('routing_status', ['direct_intent', 'embedded_intent'])
          ->default('direct_intent')
          ->after('priority')
          ->comment('路由模式：direct_intent=可直接路由；embedded_intent=需映射到父数据集执行');

    $table->unsignedInteger('execution_dataset_id')
          ->nullable()
          ->after('routing_status')
          ->comment('embedded_intent 时实际执行的目标数据集 table_id，direct_intent 时为 null');

    $table->json('avoid_when')
          ->nullable()
          ->after('notes')
          ->comment('不适用场景列表，JSON array of string');

    $table->json('clarify_when')
          ->nullable()
          ->after('avoid_when')
          ->comment('必须澄清的场景列表，JSON array of string');

    $table->json('hard_constraints')
          ->nullable()
          ->after('clarify_when')
          ->comment('硬约束列表，JSON array of string（如：仅亚马逊平台、不含SBV等）');

    $table->string('time_basis', 100)
          ->nullable()
          ->after('hard_constraints')
          ->comment('时间口径说明（如：订单下单时间、包裹发货时间、天）');

    $table->string('min_grain', 200)
          ->nullable()
          ->after('time_basis')
          ->comment('数据最小颗粒度（如：部门+渠道+渠道SKU+天）');
});
```

**对应更新** `DatasetSkillService::buildDatasetCatalogForUser()` 中的 `catalogIntents` 映射，在 catalog 响应中注入新字段：

```php
return [
    'intent_code'          => $row->intent_code,
    'intent_name'          => $row->intent_name,
    'table_id'             => (int) $row->table_id,
    'dataset_alias'        => $row->dataset_alias,
    'dataset_name'         => $row->table_name,
    'routing_status'       => $row->routing_status ?? 'direct_intent',           // 新增
    'execution_dataset_id' => $row->execution_dataset_id ? (int) $row->execution_dataset_id : null, // 新增
    'use_cases'            => $this->decodeCatalogJson($row->use_cases, []),
    'keywords'             => $this->decodeCatalogJson($row->keywords, []),
    'scenario_description' => $row->scenario_description ?: '',
    'priority'             => (int) $row->priority,
    'recommended_dimensions' => $this->decodeCatalogJson($row->recommended_dimensions, []),
    'recommended_metrics'    => $this->decodeCatalogJson($row->recommended_metrics, []),
    'default_filters'        => $this->decodeCatalogJson($row->default_filters, []),
    'comparison_strategy'    => $this->decodeCatalogJson($row->comparison_strategy, [...]),
    'avoid_when'             => $this->decodeCatalogJson($row->avoid_when, []),         // 新增
    'clarify_when'           => $this->decodeCatalogJson($row->clarify_when, []),       // 新增
    'hard_constraints'       => $this->decodeCatalogJson($row->hard_constraints, []),   // 新增
    'time_basis'             => $row->time_basis ?: '',                                 // 新增
    'min_grain'              => $row->min_grain ?: '',                                  // 新增
    'notes'                  => $row->notes ?: '',
    'select_columns'         => $selectColumnsMap[$row->dataset_alias] ?? [],
];
```

**为什么在服务端管理而不只在客户端 yml 里**：
- `avoid_when` / `clarify_when` 需要按用户权限过滤（无权限数据集的约束无需下发）
- `routing_status` + `execution_dataset_id` 随产品迭代动态变化，服务端管理后无需重新打包 opscli
- embedded_intent 的 execution_dataset_id 需要关联 `dm_tables.id`，服务端有完整的数据集表

---

### 3.2 P0 — `dm_table_columns` 补充字段语义元数据

**现状**：表有 `groupby/filterable/is_dttm/expression`，但缺少以下关键元数据，导致：
1. opscli 无法在不依赖网络的情况下判断字段是公式字段还是快照字段
2. 服务端 `CliQueryService.executeSimpleForUser()` 无法做聚合类型的前置校验

**Migration**：

```php
Schema::connection('ops_metrics')->table('dm_table_columns', function (Blueprint $table) {
    $table->tinyInteger('snapshot_metric')
          ->default(0)
          ->after('filterable')
          ->comment('是否为快照类字段（如库存快照），禁止聚合，只能用于明细表或无聚合过滤条件查询');

    $table->json('formula_config')
          ->nullable()
          ->after('snapshot_metric')
          ->comment('公式字段配置 JSON：{"summary_expression":"...","detail_expression":"..."}，非空时禁止传额外 aggregation');

    $table->json('semantic_tags')
          ->nullable()
          ->after('formula_config')
          ->comment('语义标签数组，用于字段语义索引匹配（如["库存","快照","总库存"]）');

    $table->string('platform_restriction', 50)
          ->nullable()
          ->after('semantic_tags')
          ->comment('平台限制（如 amazon_only，null=无限制）');
});
```

**字段说明与业务映射**：

| 新字段 | 业务含义 | 示例 |
|--------|---------|------|
| `snapshot_metric=1` | 库存快照字段，只能明细查询，不能 SUM/AVG | 总库存、海外仓库存、在途库存、采购库存 |
| `formula_config` 非空 | 公式字段，使用 summary_expression 而非标准聚合 | ACOS、ROAS、转化率、平均CPC |
| `semantic_tags` | 字段的业务别名/同义词列表 | `["总库存", "库存", "库存总量"]` |
| `platform_restriction=amazon_only` | 该字段仅亚马逊平台可用 | SP广告数据集中的 SP 专属字段 |

**对应更新** `DatasetSkillService` 的 CSV/JSON 导出，在 export 响应中注入 `snapshot_metric` 和 `formula_config` 字段，供 opscli 在 `dataset_fields.csv` 中缓存。

---

### 3.3 P1 — 新增 `dm_field_semantic_index` 表 + API 端点

**动机**：`field_semantic_index.yml` 目前只有手动维护的草案版本。将其持久化到数据库后，可以：
1. 随 Skill 版本按用户权限动态下发
2. 由数据团队直接维护，不依赖前端发版

**表结构设计**：

```php
Schema::connection('ops_metrics')->create('dm_field_semantic_index', function (Blueprint $table) {
    $table->increments('id');

    $table->string('semantic_group', 100)
          ->comment('语义组（如 organization_fields、product_identity_fields、time_fields）');

    $table->string('term', 100)
          ->comment('业务术语（如 销售、SP、库存、总库存）');

    $table->string('business_domain', 50)
          ->nullable()
          ->comment('业务域过滤（如 ads、sales、inventory，null=通用）');

    $table->json('common_fields')
          ->nullable()
          ->comment('通用字段名列表，如 ["dept_name", "team_name"]');

    $table->json('domain_specific_fields')
          ->nullable()
          ->comment('特定域专属字段，如 {"inventory_pmc": ["sale_group_name", "org_name"]}');

    $table->json('clarify_when')
          ->nullable()
          ->comment('必须澄清的场景列表，JSON array of string');

    $table->json('disambiguation')
          ->nullable()
          ->comment('消歧规则，如 {"possible_meanings": ["SPU产品编码","SP广告"], "resolve_rule": "广告语境优先..."}');

    $table->tinyInteger('formula_rule')
          ->default(0)
          ->comment('是否为公式类指标（ACOS/ROAS等），1=禁止额外传 aggregation');

    $table->tinyInteger('snapshot_rule')
          ->default(0)
          ->comment('是否为快照类字段（库存等），1=只能明细表，禁聚合');

    $table->integer('sort_order')->default(0);

    $table->tinyInteger('status')->default(1)->comment('1=启用 0=停用');

    $table->timestamps();
    $table->softDeletes();

    $table->index('term', 'idx_fsi_term');
    $table->index('semantic_group', 'idx_fsi_group');
    $table->index('business_domain', 'idx_fsi_domain');
    $table->index(['status', 'deleted_at'], 'idx_fsi_status');
});
```

**API 端点**：

```
GET /api/v1/data-metrics/datasets/skill/field-semantic-index
```

- 认证后按用户权限过滤（亚马逊权限用户才返回 SP/SBV 相关语义）
- 返回格式：按 semantic_group 分组的完整语义索引
- opscli `skills_upgrade` 时下载，写入 `data/field_semantic_index.yml`

在 `DatasetSkillApiController` 中新增方法：

```php
public function fieldSemanticIndex(Request $request): JsonResponse
{
    $userId = auth()->id();
    if (!$userId) {
        return ApiResponse::unauthorized('未授权访问');
    }

    return ApiResponse::success(
        $this->datasetSkillService->buildFieldSemanticIndexForUser((int) $userId)
    );
}
```

在 `routes.php` 中注册：

```php
Route::get('/datasets/skill/field-semantic-index', [DatasetSkillApiController::class, 'fieldSemanticIndex']);
```

---

### 3.4 P1 — 扩展数据集关系表 + API 端点

**现状**：`TableRelation` / `TableRelationCondition` 模型已存在，但 `relation_type` 枚举值需确认是否覆盖草案 `dataset_relationships.yml` 中的所有类型。

**需要支持的关系类型**：

| 关系类型 | 含义 | opscli 使用场景 |
|---------|------|---------------|
| `sub_table` | 主从关系（如即时综合包含销售子表口径） | embedded_intent 映射依据 |
| `substitute` | 替代关系（当 A 不可用时使用 B） | 优雅降级路由 |
| `drill_down` | 下钻关系（汇总 → 明细） | 用户要明细时自动路由到更细粒度数据集 |
| `merge_fallback` | 合并回退（非亚马逊广告 → 广告费数据集） | 平台限制触发时的回退路由 |
| `disabled_direct` | 禁止直连（必须通过父表访问） | 拦截错误路由，返回正确入口 |

**如果 `TableRelation.relation_type` 字段不存在或枚举不完整，需补充**：

```php
Schema::connection('ops_metrics')->table('dm_table_relations', function (Blueprint $table) {
    // 若原字段为 string 或枚举不全，添加/修改
    $table->string('relation_type', 50)
          ->default('sub_table')
          ->comment('关系类型：sub_table/substitute/drill_down/merge_fallback/disabled_direct')
          ->change();

    $table->string('condition_description', 500)
          ->nullable()
          ->comment('关系触发条件描述（如：非亚马逊平台触发、embedded_intent触发）');
});
```

**API 端点**：

```
GET /api/v1/data-metrics/datasets/skill/relationships
```

- 返回格式：`{from_dataset_alias: [{relation_type, to_dataset_alias, to_table_id, condition_description}]}`
- opscli `skills_upgrade` 时下载，写入 `data/dataset_relationships.yml`

在 `DatasetSkillApiController` 中新增方法：

```php
public function datasetRelationships(Request $request): JsonResponse
{
    $userId = auth()->id();
    if (!$userId) {
        return ApiResponse::unauthorized('未授权访问');
    }

    return ApiResponse::success(
        $this->datasetSkillService->buildDatasetRelationshipsForUser((int) $userId)
    );
}
```

在 `routes.php` 中注册：

```php
Route::get('/datasets/skill/relationships', [DatasetSkillApiController::class, 'datasetRelationships']);
```

---

### 3.5 P2 — `CliQueryService` 插入 Query Plan 校验层

**现状**：`executeSimpleForUser()` 接收 simplePayload 后直接构建查询，没有前置的字段类型校验。公式字段/快照字段约束完全依赖客户端规则文本，服务端无任何保护。

**目标**：将 SKILL.md 铁律八（公式字段禁聚合）从"AI 规则约束"变成"服务端硬门禁"，一次生效，所有客户端（CLI/MCP/前端）受益。

**在 `executeSimpleForUser()` 进入 `simpleQueryBuilder->build()` 前插入校验**：

```php
// 【新增】Query Plan 前置校验
private function validateQueryPlan(array $simplePayload, int $tableId): void
{
    $allFields = array_merge(
        $simplePayload['dimensions'] ?? [],
        array_column($simplePayload['metrics'] ?? [], 'field')
    );

    foreach ($allFields as $fieldName) {
        $col = TableField::query()
            ->where('table_id', $tableId)
            ->where('field_name', $fieldName)
            ->first();

        if (!$col) {
            continue;
        }

        // 快照字段禁聚合校验
        if ($col->snapshot_metric && !empty($simplePayload['dimensions'])) {
            throw new \InvalidArgumentException(
                "字段 [{$fieldName}] 为快照类字段，不支持聚合分组查询，请去掉维度或改用明细查询"
            );
        }

        // 公式字段禁额外聚合校验
        if (!empty($col->formula_config)) {
            $metric = collect($simplePayload['metrics'] ?? [])
                ->firstWhere('field', $fieldName);
            if ($metric && !empty($metric['aggregation'])) {
                throw new \InvalidArgumentException(
                    "字段 [{$fieldName}] 为公式类指标（{$fieldName}），已内置聚合逻辑，禁止额外传 aggregation 参数"
                );
            }
        }
    }
}
```

---

### 3.6 服务端文件变更汇总

```
vendor/aukey/data-metrics/
├── database/migrations/
│   ├── 2026_06_xx_add_routing_fields_to_dm_dataset_query_intents.php   ← 新增（3.1）
│   ├── 2026_06_xx_add_semantic_fields_to_dm_table_columns.php           ← 新增（3.2）
│   ├── 2026_06_xx_create_dm_field_semantic_index_table.php              ← 新增（3.3）
│   └── 2026_06_xx_extend_dm_table_relations_type.php                    ← 新增（3.4）
├── src/
│   ├── Models/
│   │   ├── FieldSemanticIndex.php     ← 新增（3.3）
│   │   └── TableRelation.php          ← 修改：更新 relation_type 枚举注释
│   ├── Services/
│   │   ├── DatasetSkillService.php    ← 修改：buildDatasetCatalogForUser 注入新字段（3.1）
│   │   │                                        buildFieldSemanticIndexForUser 新增（3.3）
│   │   │                                        buildDatasetRelationshipsForUser 新增（3.4）
│   │   └── CliQueryService.php        ← 修改：executeSimpleForUser 插入校验层（3.5）
│   └── Http/
│       ├── Controllers/
│       │   └── DatasetSkillApiController.php  ← 修改：新增 fieldSemanticIndex、datasetRelationships 方法
│       └── routes.php                          ← 修改：注册两个新端点
```

---

## 四、优先级排期

### P0（本迭代，1周内）

| 编号 | 任务 | 归属 | 预估工时 |
|------|------|------|---------|
| C-1 | 草案文件落地到 `data/` 目录，VERSION.json 升级 | 客户端 | 2h |
| C-2 | 新增 `scripts/route_intent.py` 本地意图路由 | 客户端 | 4h |
| S-1 | `dm_dataset_query_intents` 表加字段 Migration | 服务端 | 2h |
| S-2 | `DatasetSkillService.buildDatasetCatalogForUser()` 注入新字段 | 服务端 | 2h |

**P0 完成标志**：`opscli query intent` 返回带 `routing_status/avoid_when/clarify_when` 的 intent，客户端本地 route_intent.py 可处理 embedded_intent 映射。

### P1（下迭代，2周内）

| 编号 | 任务 | 归属 | 预估工时 |
|------|------|------|---------|
| C-3 | 新增 `scripts/build_query_plan.py` | 客户端 | 6h |
| C-4 | `references/rules.md` 补充字段语义解析流程 | 客户端 | 2h |
| C-5 | `SKILL.md` 补充铁律三-B 本地路由回退链 | 客户端 | 1h |
| S-3 | `dm_table_columns` 加字段 Migration | 服务端 | 3h |
| S-4 | 新增 `dm_field_semantic_index` 表 + Model + Service 方法 + API 端点 | 服务端 | 6h |
| S-5 | 扩展数据集关系表 + `buildDatasetRelationshipsForUser` + API 端点 | 服务端 | 4h |

**P1 完成标志**：`skills_upgrade` 能拉取字段语义索引和数据集关系图谱，`build_query_plan.py` 能输出可执行查询计划。

### P2（再下迭代）

| 编号 | 任务 | 归属 | 预估工时 |
|------|------|------|---------|
| C-6 | `scripts/updater.py` 扩展拉取新端点数据 | 客户端 | 3h |
| S-6 | `CliQueryService.executeSimpleForUser()` 插入 Query Plan 校验层 | 服务端 | 4h |
| C-7 | 路由回归测试：`routing_eval_cases.yml` 全用例验证 | 客户端 | 4h |

**P2 完成标志**：公式字段禁聚合、快照字段禁聚合在服务端硬门禁生效，opscli `skills_upgrade` 能同步完整的语义索引和关系图谱。

---

## 五、数据一致性约定

为避免客户端静态文件和服务端动态数据出现漂移，约定以下规则：

| 数据类型 | 权威来源 | 客户端角色 |
|---------|---------|---------|
| intent 分类与约束 | 服务端 `dm_dataset_query_intents` | 缓存（`intent_taxonomy.yml` + `dataset_profiles.yml`） |
| 字段元数据 | 服务端 `dm_table_columns` | 缓存（`dataset_fields.csv`） |
| 字段语义索引 | 服务端 `dm_field_semantic_index` | 缓存（`field_semantic_index.yml`） |
| 数据集关系图谱 | 服务端 `TableRelation` | 缓存（`dataset_relationships.yml`） |
| 查询组件权限 | 服务端 `SelectColumnConfig/Relation` | 缓存（`dataset_select_columns.csv`） |

**升级触发规则**：manifest 版本变化时，`skills_upgrade` 拉取所有数据文件，保持客户端缓存与服务端一致。

---

## 六、开放问题（待业务确认）

以下问题来自草案 `open_questions.yml`，需要业务侧在实施前确认：

| 问题 | 当前定义 | 待确认内容 | 优先级 |
|------|---------|---------|--------|
| SP词组数据集 | SP广告数据集不含搜索词/关键词/投放词，遇到词组分析必须澄清 | 后续是否有独立搜索词数据集？何时开放路由？ | P0 |
| 报告周期合法值 | 亚马逊目录绩效、搜索词绩效必须选择报告周期 | 报告周期的合法枚举值从哪个查询组件获取？ | P0 |
| 非亚马逊广告明细字段 | 非亚马逊平台广告明细只能用广告费数据集 | 广告费数据集支持哪些非亚马逊平台的明细维度？ | P0 |
| 库存快照字段标记 | 即时综合/即时销售/账单销售中的库存字段属于快照字段 | 哪些字段需要打 `snapshot_metric=1`？请数据侧提供完整清单 | P1 |
| 广告类型枚举值 | 广告类型费数据集用于SP/SD/SB/SBV类型汇总 | `ads_type` 查询组件的标准枚举值？（避免拼写错误） | P1 |
| SBV明细 | SB广告数据集不包含SBV，SBV只能走广告费或广告类型费做汇总 | 是否有独立SBV明细数据集计划？ | P1 |
| 项目二部字段权限 | 即时综合中项目二部专属字段仅项目二部可用 | `dept_name` 中"项目二部"的标准枚举值是什么？ | P1 |

---

## 七、验收标准

### 客户端验收

```bash
# 1. 版本和数据状态
opscli skills list  # 显示 ops-dataset-query v1.1.0，data_state=ready

# 2. 本地意图路由（不依赖网络）
python scripts/route_intent.py "近30天各部门销售额"
# 期望：命中 billing_sales_review 意图，execution_alias=ds_9e288aa0df06

python scripts/route_intent.py "今天实时销售监控"
# 期望：命中 realtime_sales_monitoring 意图，routing_status=embedded_intent，execution_alias=ds_d35ac6f3910c

python scripts/route_intent.py "SP广告活动ACOS分析"
# 期望：命中 amazon_sp_ads_detail 意图，requires_clarification=false

python scripts/route_intent.py "SP词组分析"
# 期望：requires_clarification=true，clarification_reasons 包含"SP广告数据集不含搜索词"

# 3. 路由回归测试（全通过）
python scripts/run_routing_eval.py data/routing_eval_cases.yml
# 期望：所有用例准确率达到业务可接受阈值
```

### 服务端验收

```bash
# 1. Catalog API 包含新字段
curl /api/v1/data-metrics/datasets/skill/catalog | jq '.intents[0].routing_status'
# 期望：返回 "direct_intent" 或 "embedded_intent"

curl /api/v1/data-metrics/datasets/skill/catalog | jq '.intents[0].avoid_when'
# 期望：返回 JSON array of string

# 2. 字段语义索引 API
curl /api/v1/data-metrics/datasets/skill/field-semantic-index
# 期望：返回 semantic_groups 分组的语义索引

# 3. 数据集关系 API
curl /api/v1/data-metrics/datasets/skill/relationships
# 期望：返回按 dataset_alias 分组的关系列表

# 4. 服务端公式字段校验（P2 验收）
# 对含 formula_config 字段传入 aggregation 参数
# 期望：返回 400 错误，错误信息包含"公式类指标，禁止额外传 aggregation"
```

---

> **文档维护**：本方案随实施进展持续更新，每个 P 阶段完成后在本文档对应章节标记完成状态。
