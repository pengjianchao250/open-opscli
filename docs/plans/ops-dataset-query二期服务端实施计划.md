# ops-dataset-query 二期服务端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展 `data-metrics` 服务端，让 `dm_dataset_query_intents` 和字段导出包含足够的约束和语义信息，使客户端意图路由无需猜测即可工作

**Architecture:** 通过 Laravel 迁移向两张表新增列（`dm_dataset_query_intents` + `dm_table_columns`），同步更新 `DatasetSkillService` 的 SELECT 语句和 CSV 导出方法，并新增字段语义索引导出 API；所有改动均向后兼容，新列允许 NULL 或带默认值

**Tech Stack:** PHP 8.1、Laravel 10、MySQL（ops_metrics 连接）、`DatasetSkillService.php`、`DatasetSkillApiController.php`、`routes.php`

**项目根目录:** `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/`

---

## 文件索引

| 操作 | 文件路径 |
|------|---------|
| 新建 | `src/database/migrations/2026_06_02_000001_add_routing_fields_to_dm_dataset_query_intents.php` |
| 修改 | `src/Services/DatasetSkillService.php`（`loadDatasetQueryIntents()` + `buildDatasetCatalogForUser()` + `toFieldExportRow()` + `createFieldExportResponseForUser()`） |
| 新建 | `src/database/migrations/2026_06_02_000002_add_snapshot_semantic_to_dm_table_columns.php` |
| 修改 | `src/Services/DatasetSkillService.php`（dimension `buildFields()` 块 + `toFieldExportRow()` + CSV 表头） |
| 新建 | `src/database/migrations/2026_06_02_000003_create_dm_field_semantic_index_table.php` |
| 修改 | `src/Services/DatasetSkillService.php`（新增 `buildFieldSemanticIndexForUser()` 方法） |
| 修改 | `src/Http/Controllers/DatasetSkillApiController.php`（新增 `exportFieldSemanticIndex()`） |
| 修改 | `src/Http/routes.php`（注册新路由） |

---

## 任务 S-1：`dm_dataset_query_intents` 新增约束字段迁移

**Files:**
- 新建: `src/database/migrations/2026_06_02_000001_add_routing_fields_to_dm_dataset_query_intents.php`

- [ ] **步骤 1：写失败测试**

```bash
# 确认新字段当前不存在
php artisan tinker --execute="
use Illuminate\Support\Facades\Schema;
\$cols = Schema::connection('ops_metrics')->getColumnListing('dm_dataset_query_intents');
\$missing = array_filter(['routing_status','execution_dataset_id','avoid_when','clarify_when','hard_constraints','time_basis','min_grain'], fn(\$c) => !in_array(\$c, \$cols));
echo empty(\$missing) ? 'ALREADY_EXISTS' : 'NOT_FOUND: '.implode(',',\$missing);"
```

预期输出：`NOT_FOUND: routing_status,execution_dataset_id,...`

- [ ] **步骤 2：创建迁移文件**

```php
<?php
// src/database/migrations/2026_06_02_000001_add_routing_fields_to_dm_dataset_query_intents.php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * 为 dm_dataset_query_intents 新增意图路由约束字段。
 *
 * routing_status:        'direct_intent'（直接数据集）| 'embedded_intent'（嵌入其他意图）
 * execution_dataset_id:  embedded_intent 时指向实际执行的数据集 dm_tables.id
 * avoid_when:            AI 应避免推荐此意图的场景描述数组（JSON）
 * clarify_when:          需向用户澄清的场景描述数组（JSON）
 * hard_constraints:      硬性约束，AI 必须遵守（JSON）
 * time_basis:            时间基准，如 "transaction_date" / "ad_date"
 * min_grain:             最小粒度，如 "day" / "week"
 */
return new class extends Migration
{
    public function getConnection(): ?string
    {
        return 'ops_metrics';
    }

    public function up(): void
    {
        Schema::connection($this->getConnection())
            ->table('dm_dataset_query_intents', function (Blueprint $table) {
                // 路由类型：direct_intent 表示该意图直接对应某数据集
                // embedded_intent 表示该意图嵌套在其他意图下，需跳转到 execution_dataset_id
                $table->string('routing_status', 40)
                      ->notNull()
                      ->default('direct_intent')
                      ->comment('direct_intent | embedded_intent')
                      ->after('table_id');

                // embedded_intent 时的实际执行数据集，NULL 表示与 table_id 相同
                $table->unsignedBigInteger('execution_dataset_id')
                      ->nullable()
                      ->default(null)
                      ->comment('embedded_intent 时指向实际执行的 dm_tables.id')
                      ->after('routing_status');

                // AI 应避免推荐此数据集的场景，如"当用户要按ASIN分析时不推荐汇总表"
                $table->json('avoid_when')
                      ->nullable()
                      ->comment('AI 应避免推荐此意图的场景描述数组')
                      ->after('execution_dataset_id');

                // 触发澄清对话的场景，如"当用户提到 SP 词/SBV/报告周期"
                $table->json('clarify_when')
                      ->nullable()
                      ->comment('需向用户澄清的场景描述数组')
                      ->after('avoid_when');

                // 硬性约束，AI 必须严格遵守，如"该数据集不支持按天粒度以下查询"
                $table->json('hard_constraints')
                      ->nullable()
                      ->comment('AI 查询时必须遵守的硬性约束数组')
                      ->after('clarify_when');

                // 时间基准字段名，告诉 AI 此数据集用哪个日期字段做时间过滤
                $table->string('time_basis', 80)
                      ->nullable()
                      ->comment('时间基准字段名，如 transaction_date / ad_date')
                      ->after('hard_constraints');

                // 最小查询粒度，防止 AI 请求不可能的粒度
                $table->string('min_grain', 20)
                      ->nullable()
                      ->comment('最小粒度：day / week / month')
                      ->after('time_basis');

                $table->index('routing_status', 'idx_dm_dqi_routing_status');
                $table->index('execution_dataset_id', 'idx_dm_dqi_execution_dataset_id');
            });
    }

    public function down(): void
    {
        Schema::connection($this->getConnection())
            ->table('dm_dataset_query_intents', function (Blueprint $table) {
                $table->dropIndex('idx_dm_dqi_routing_status');
                $table->dropIndex('idx_dm_dqi_execution_dataset_id');
                $table->dropColumn([
                    'routing_status',
                    'execution_dataset_id',
                    'avoid_when',
                    'clarify_when',
                    'hard_constraints',
                    'time_basis',
                    'min_grain',
                ]);
            });
    }
};
```

- [ ] **步骤 3：运行迁移**

```bash
cd /Applications/MxSrvs/www/auto-scheduler
php artisan migrate --path=vendor/aukey/data-metrics/src/database/migrations/2026_06_02_000001_add_routing_fields_to_dm_dataset_query_intents.php
```

预期输出：`Migrated: ... 2026_06_02_000001_add_routing_fields_to_dm_dataset_query_intents`（0 错误）

- [ ] **步骤 4：验证字段存在**

```bash
php artisan tinker --execute="
use Illuminate\Support\Facades\Schema;
\$cols = Schema::connection('ops_metrics')->getColumnListing('dm_dataset_query_intents');
\$required = ['routing_status','execution_dataset_id','avoid_when','clarify_when','hard_constraints','time_basis','min_grain'];
\$missing = array_filter(\$required, fn(\$c) => !in_array(\$c, \$cols));
echo empty(\$missing) ? 'PASS: 所有字段已存在' : 'FAIL: '.implode(',',\$missing);"
```

预期输出：`PASS: 所有字段已存在`

---

## 任务 S-2：更新 `DatasetSkillService` 读取和返回意图约束字段

**Files:**
- 修改: `src/Services/DatasetSkillService.php`（两处）

- [ ] **步骤 1：确认当前 SELECT 缺少新字段**

```bash
grep -n "avoid_when\|clarify_when\|hard_constraints\|routing_status\|time_basis\|min_grain" \
  /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Services/DatasetSkillService.php
```

预期输出：空（无命中）

- [ ] **步骤 2：更新 `loadDatasetQueryIntents()` 的 SELECT 列表**

定位 `src/Services/DatasetSkillService.php` 第 643 行（`->select([` 块），将原 SELECT 替换为：

```php
            ->select([
                'i.intent_code',
                'i.intent_name',
                'i.table_id',
                'i.routing_status',
                'i.execution_dataset_id',
                'i.use_cases',
                'i.keywords',
                'i.scenario_description',
                'i.priority',
                'i.recommended_dimensions',
                'i.recommended_metrics',
                'i.default_filters',
                'i.comparison_strategy',
                'i.avoid_when',
                'i.clarify_when',
                'i.hard_constraints',
                'i.time_basis',
                'i.min_grain',
                'i.notes',
                't.dataset_alias',
                't.table_name',
            ])
```

- [ ] **步骤 3：更新 `buildDatasetCatalogForUser()` 的 map 闭包**

定位 `src/Services/DatasetSkillService.php` 第 144 行（`->map(function ($row) use ($selectColumnsMap) {`），在 `'notes' => ...` 那行之前追加以下 7 行：

```php
                    'routing_status' => $row->routing_status ?: 'direct_intent',
                    'execution_dataset_id' => $row->execution_dataset_id ? (int) $row->execution_dataset_id : null,
                    'avoid_when' => $this->decodeCatalogJson($row->avoid_when, []),
                    'clarify_when' => $this->decodeCatalogJson($row->clarify_when, []),
                    'hard_constraints' => $this->decodeCatalogJson($row->hard_constraints, []),
                    'time_basis' => $row->time_basis ?: null,
                    'min_grain' => $row->min_grain ?: null,
```

- [ ] **步骤 4：验证 catalog API 包含新字段**

```bash
cd /Applications/MxSrvs/www/auto-scheduler
php artisan tinker --execute="
use Aukey\DataMetrics\Services\DatasetSkillService;
\$svc = app(DatasetSkillService::class);
\$catalog = \$svc->buildDatasetCatalogForUser(1);
\$intent = \$catalog['intents'][0] ?? [];
\$expected = ['routing_status','avoid_when','clarify_when','hard_constraints','time_basis','min_grain'];
\$missing = array_filter(\$expected, fn(\$k) => !array_key_exists(\$k, \$intent));
echo empty(\$missing) ? 'PASS' : 'FAIL missing: '.implode(',',\$missing);"
```

预期输出：`PASS`

---

## 任务 S-3：`dm_table_columns` 新增快照标记和语义标签字段

**Files:**
- 新建: `src/database/migrations/2026_06_02_000002_add_snapshot_semantic_to_dm_table_columns.php`

- [ ] **步骤 1：确认字段不存在**

```bash
php artisan tinker --execute="
use Illuminate\Support\Facades\Schema;
\$cols = Schema::connection('ops_metrics')->getColumnListing('dm_table_columns');
\$check = array_filter(['snapshot_metric','semantic_tags'], fn(\$c) => !in_array(\$c, \$cols));
echo empty(\$check) ? 'ALREADY_EXISTS' : 'NOT_FOUND: '.implode(',',\$check);"
```

预期输出：`NOT_FOUND: snapshot_metric,semantic_tags`

- [ ] **步骤 2：创建迁移文件**

```php
<?php
// src/database/migrations/2026_06_02_000002_add_snapshot_semantic_to_dm_table_columns.php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * 为 dm_table_columns（维度列）新增快照标记和语义标签。
 *
 * snapshot_metric: 1 表示该维度列是快照字段（如库存）；
 *                  快照字段只能用于明细查询，不能 SUM/AVG/GROUP BY 聚合。
 * semantic_tags:   JSON 数组，存储该字段的业务语义标签，
 *                  如 ["库存", "warehouse", "总库存", "可用库存"]，
 *                  供字段语义索引模糊匹配使用。
 */
return new class extends Migration
{
    public function getConnection(): ?string
    {
        return 'ops_metrics';
    }

    public function up(): void
    {
        Schema::connection($this->getConnection())
            ->table('dm_table_columns', function (Blueprint $table) {
                // snapshot_metric: 库存类快照字段标记，1=快照，0=可聚合
                // 紧跟 filterable 之后，便于管理员在后台一眼看到聚合限制
                $table->tinyInteger('snapshot_metric')
                      ->notNull()
                      ->default(0)
                      ->comment('快照字段标记：1=不可聚合（库存等），0=普通可聚合')
                      ->after('filterable');

                // semantic_tags: 业务同义词和别名，供 AI 字段语义索引模糊搜索
                $table->json('semantic_tags')
                      ->nullable()
                      ->comment('字段业务语义标签数组，供 AI 语义搜索使用')
                      ->after('snapshot_metric');

                $table->index('snapshot_metric', 'idx_dm_tc_snapshot_metric');
            });
    }

    public function down(): void
    {
        Schema::connection($this->getConnection())
            ->table('dm_table_columns', function (Blueprint $table) {
                $table->dropIndex('idx_dm_tc_snapshot_metric');
                $table->dropColumn(['snapshot_metric', 'semantic_tags']);
            });
    }
};
```

- [ ] **步骤 3：运行迁移**

```bash
php artisan migrate --path=vendor/aukey/data-metrics/src/database/migrations/2026_06_02_000002_add_snapshot_semantic_to_dm_table_columns.php
```

预期输出：`Migrated: ... 2026_06_02_000002_...`（0 错误）

- [ ] **步骤 4：验证字段**

```bash
php artisan tinker --execute="
use Illuminate\Support\Facades\Schema;
\$cols = Schema::connection('ops_metrics')->getColumnListing('dm_table_columns');
echo in_array('snapshot_metric', \$cols) && in_array('semantic_tags', \$cols) ? 'PASS' : 'FAIL';"
```

预期输出：`PASS`

---

## 任务 S-4：字段导出包含 `snapshot_metric` 和 `has_formula_config`

**Files:**
- 修改: `src/Services/DatasetSkillService.php`（dimension 构建块 + `toFieldExportRow()` + CSV 表头）

- [ ] **步骤 1：确认维度行当前没有 `snapshot_metric` 键**

```bash
grep -n "snapshot_metric" \
  /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Services/DatasetSkillService.php
```

预期输出：空

- [ ] **步骤 2：在 dimension buildFields 块中加入 `snapshot_metric`**

定位 `DatasetSkillService.php` 约 480-500 行的 dimension map 闭包，找到 `'is_dttm' => ...` 那行，在它**之前**追加：

```php
                'snapshot_metric' => (int) ((bool) $column->snapshot_metric),
```

完整上下文（确认插入位置正确）：

```php
                // 改前
                'is_dttm' => (int) ((bool) $column->is_dttm),

                // 改后
                'snapshot_metric' => (int) ((bool) $column->snapshot_metric),
                'is_dttm' => (int) ((bool) $column->is_dttm),
```

**注意**：metric 行已有 `has_formula_config`，无需重复添加；dimension 行不需要 `has_formula_config`（维度没有公式）。

- [ ] **步骤 3：更新 `toFieldExportRow()` 追加两列**

将原 `toFieldExportRow()` 方法（约 551-566 行）替换为：

```php
    protected function toFieldExportRow(array $row): array
    {
        return [
            $row['table_id'],
            $row['dataset_alias'],
            $row['dataset_name'],
            $row['field_name'],
            $row['verbose_name'],
            $row['global_alias'] ?? null,
            $row['field_type'],
            $row['summary_expression'] ?? null,
            $row['detail_expression'] ?? null,
            $row['description'],
            $row['remarks'] ?? '',
            // 新增列（客户端 v1.1.0 依赖这两列做字段能力判断）
            $row['snapshot_metric'] ?? 0,
            $row['has_formula_config'] ?? 0,
        ];
    }
```

- [ ] **步骤 4：更新 CSV 表头**

定位 `createFieldExportResponseForUser()` 中的 `fputcsv($handle, [...])`（约 204-216 行），将表头数组替换为：

```php
            fputcsv($handle, [
                'table_id',
                'dataset_alias',
                'dataset_name',
                'field_name',
                'verbose_name',
                'global_alias',
                'field_type',
                'summary_expression',
                'detail_expression',
                'description',
                'remarks',
                'snapshot_metric',
                'has_formula_config',
            ]);
```

- [ ] **步骤 5：验证导出 CSV 包含新列**

```bash
php artisan tinker --execute="
use Aukey\DataMetrics\Services\DatasetSkillService;
\$svc = app(DatasetSkillService::class);
\$payload = \$svc->buildExportPayloadForUser(1);
\$row = \$payload['fields']->first() ?? [];
echo array_key_exists('snapshot_metric', \$row) && array_key_exists('has_formula_config', \$row)
    ? 'PASS: 两列均存在' : 'FAIL: 缺少列';"
```

预期输出：`PASS: 两列均存在`

- [ ] **步骤 6：验证 CSV 表头列数（应为 13）**

```bash
cd /Applications/MxSrvs/www/auto-scheduler
php -r "
\$line = '\"table_id\",\"dataset_alias\",\"dataset_name\",\"field_name\",\"verbose_name\",\"global_alias\",\"field_type\",\"summary_expression\",\"detail_expression\",\"description\",\"remarks\",\"snapshot_metric\",\"has_formula_config\"';
echo count(str_getcsv(\$line)) === 13 ? 'PASS: 13 列' : 'FAIL';
"
```

预期输出：`PASS: 13 列`

---

## 任务 S-5（P1）：新增字段语义索引导出 API

> P1 优先级，需 P0 任务（S-1 ~ S-4）全部通过后再执行。

**Files:**
- 新建: `src/database/migrations/2026_06_02_000003_create_dm_field_semantic_index_table.php`
- 修改: `src/Services/DatasetSkillService.php`（新增 `buildFieldSemanticIndexForUser()`）
- 修改: `src/Http/Controllers/DatasetSkillApiController.php`（新增 `exportFieldSemanticIndex()`）
- 修改: `src/Http/routes.php`（注册路由）

### S-5-A：创建 `dm_field_semantic_index` 表

- [ ] **步骤 1：写失败测试**

```bash
php artisan tinker --execute="
use Illuminate\Support\Facades\Schema;
echo Schema::connection('ops_metrics')->hasTable('dm_field_semantic_index') ? 'ALREADY_EXISTS' : 'NOT_FOUND';"
```

预期：`NOT_FOUND`

- [ ] **步骤 2：创建迁移文件**

```php
<?php
// src/database/migrations/2026_06_02_000003_create_dm_field_semantic_index_table.php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * 创建字段语义索引表：为 AI 提供"业务用语 → 数据集字段"的映射关系。
 *
 * 设计思路：
 *   1. 一条记录代表"在某个数据集中，某个业务词汇指向某个字段"
 *   2. 同一 table_id + field_name 可有多条记录（多个同义词）
 *   3. 同一 semantic_term 可指向不同数据集的不同字段（通过 table_id 区分）
 *   4. 通过 needs_disambiguation 标记是否需要 AI 追问澄清
 */
return new class extends Migration
{
    public function getConnection(): ?string
    {
        return 'ops_metrics';
    }

    public function up(): void
    {
        Schema::connection($this->getConnection())
            ->create('dm_field_semantic_index', function (Blueprint $table) {
                $table->id()->comment('主键ID');

                // 关联数据集
                $table->unsignedBigInteger('table_id')
                      ->comment('关联 dm_tables.id');

                // 字段名（对应 dm_table_columns.column_name 或 dm_sql_metrics.metric_name）
                $table->string('field_name', 120)
                      ->comment('物理字段名');

                // 字段类型
                $table->enum('field_type', ['dimension', 'metric'])
                      ->comment('字段类型：dimension / metric');

                // 业务语义词，用户可能说的话，如"SP销售额""广告花费""库存量"
                $table->string('semantic_term', 120)
                      ->comment('业务语义词，用户可能用到的表达');

                // 是否需要 AI 追问，如"销售额"可能指 SP/SB/SD 需要澄清
                $table->boolean('needs_disambiguation')
                      ->default(false)
                      ->comment('1=AI 需要追问澄清广告类型等，0=直接映射');

                // 歧义澄清提示，当 needs_disambiguation=1 时使用
                $table->text('disambiguation_hint')
                      ->nullable()
                      ->comment('给 AI 的澄清提示，如"请问是哪种广告类型的销售额？"');

                // 推荐聚合方式（仅 metric 类型有效）
                $table->string('aggregation_hint', 40)
                      ->nullable()
                      ->comment('推荐聚合方式，如 SUM / 公式计算 / snapshot_only');

                // 状态
                $table->boolean('status')
                      ->default(true)
                      ->comment('1=启用，0=停用');

                $table->unsignedBigInteger('created_by')->nullable()->comment('创建人ID');
                $table->unsignedBigInteger('updated_by')->nullable()->comment('更新人ID');
                $table->timestamps();
                $table->softDeletes();

                // 查询索引
                $table->index(['table_id', 'status'], 'idx_dm_fsi_table_status');
                $table->index(['semantic_term', 'status'], 'idx_dm_fsi_term_status');
                $table->unique(['table_id', 'field_name', 'semantic_term'], 'uk_dm_fsi_table_field_term');

                $table->comment('字段语义索引：业务用语到数据集字段的映射表，供 AI 意图路由使用');
            });
    }

    public function down(): void
    {
        Schema::connection($this->getConnection())
            ->dropIfExists('dm_field_semantic_index');
    }
};
```

- [ ] **步骤 3：运行迁移**

```bash
php artisan migrate --path=vendor/aukey/data-metrics/src/database/migrations/2026_06_02_000003_create_dm_field_semantic_index_table.php
```

预期：`Migrated: ... 2026_06_02_000003_...`

- [ ] **步骤 4：验证表存在**

```bash
php artisan tinker --execute="
use Illuminate\Support\Facades\Schema;
echo Schema::connection('ops_metrics')->hasTable('dm_field_semantic_index') ? 'PASS' : 'FAIL';"
```

预期：`PASS`

### S-5-B：`DatasetSkillService` 新增 `buildFieldSemanticIndexForUser()`

- [ ] **步骤 1：在 `DatasetSkillService.php` 末尾（最后一个 `}` 之前）新增方法**

```php
    /**
     * 为用户构建字段语义索引。
     *
     * 返回用户有权限的数据集中，所有字段的业务语义词条目，
     * 供 AI 客户端通过用户输入匹配到候选字段。
     *
     * @param  int  $userId
     * @return array{version: string, generated_at: string, entry_count: int, entries: array}
     */
    public function buildFieldSemanticIndexForUser(int $userId): array
    {
        $allowedDatasetIds = $this->userDatasetPermissionService
            ->getUserAuthorizedDatasetIdsWithAdmin($userId);

        if (empty($allowedDatasetIds)) {
            return [
                'version'      => $this->getManifest()['version'] ?? 'v0.0.0',
                'generated_at' => now()->toISOString(),
                'entry_count'  => 0,
                'entries'      => [],
            ];
        }

        // 拉取该用户有权限且已启用 CLI 的数据集别名，用于补充导出数据集基本信息
        $tableAliasMap = DB::connection('ops_metrics')
            ->table('dm_tables')
            ->whereIn('id', $allowedDatasetIds)
            ->where('is_cli_enabled', 1)
            ->whereNull('deleted_at')
            ->pluck('dataset_alias', 'id');

        // 查询语义索引
        $entries = DB::connection('ops_metrics')
            ->table('dm_field_semantic_index')
            ->whereIn('table_id', $allowedDatasetIds)
            ->where('status', 1)
            ->whereNull('deleted_at')
            ->select([
                'table_id',
                'field_name',
                'field_type',
                'semantic_term',
                'needs_disambiguation',
                'disambiguation_hint',
                'aggregation_hint',
            ])
            ->orderBy('table_id')
            ->orderBy('field_name')
            ->get()
            ->map(function ($row) use ($tableAliasMap) {
                return [
                    'table_id'             => (int) $row->table_id,
                    'dataset_alias'        => $tableAliasMap->get($row->table_id, ''),
                    'field_name'           => $row->field_name,
                    'field_type'           => $row->field_type,
                    'semantic_term'        => $row->semantic_term,
                    'needs_disambiguation' => (bool) $row->needs_disambiguation,
                    'disambiguation_hint'  => $row->disambiguation_hint ?: null,
                    'aggregation_hint'     => $row->aggregation_hint ?: null,
                ];
            })
            ->values()
            ->all();

        return [
            'version'      => $this->getManifest()['version'] ?? 'v0.0.0',
            'generated_at' => now()->toISOString(),
            'entry_count'  => count($entries),
            'entries'      => $entries,
        ];
    }
```

- [ ] **步骤 2：验证方法可调用（表为空时返回 entry_count=0）**

```bash
php artisan tinker --execute="
use Aukey\DataMetrics\Services\DatasetSkillService;
\$svc = app(DatasetSkillService::class);
\$index = \$svc->buildFieldSemanticIndexForUser(1);
echo array_key_exists('entry_count', \$index) && array_key_exists('entries', \$index) ? 'PASS' : 'FAIL';"
```

预期：`PASS`

### S-5-C：Controller + 路由

- [ ] **步骤 1：确认路由不存在**

```bash
grep "field-semantic-index" \
  /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Http/routes.php
```

预期：空（无命中）

- [ ] **步骤 2：在 `DatasetSkillApiController.php` 新增 `exportFieldSemanticIndex()`**

定位 `catalog` 方法，在其之后追加：

```php
    /**
     * 导出字段语义索引（供 AI 客户端进行业务词→字段映射）。
     *
     * GET /api/v1/data-metrics/datasets/skill/field-semantic-index
     */
    public function exportFieldSemanticIndex(Request $request): JsonResponse
    {
        $user = $request->user();
        $index = $this->datasetSkillService->buildFieldSemanticIndexForUser($user->id);

        return response()->json($index);
    }
```

- [ ] **步骤 3：在 `routes.php` 注册路由**

定位 `catalog` 路由（约 65 行），在其下方追加：

```php
        Route::get('/skill/field-semantic-index', [DatasetSkillApiController::class, 'exportFieldSemanticIndex']);
```

- [ ] **步骤 4：验证路由已注册**

```bash
php artisan route:list --path=skill/field-semantic-index
```

预期输出：包含一条 `GET` + `skill/field-semantic-index` 的路由记录

- [ ] **步骤 5：HTTP 集成验证（需已登录用户的 Token）**

```bash
TOKEN=$(opscli auth token get -s ops 2>/dev/null)
curl -s -H "Authorization: Bearer ${TOKEN}" \
     "http://localhost/api/v1/data-metrics/datasets/skill/field-semantic-index" | \
python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS' if 'entry_count' in d else 'FAIL')"
```

预期输出：`PASS`

---

## 验收检查清单

| ID | 检查项 | 验证命令 |
|----|--------|---------|
| V-S1 | `dm_dataset_query_intents` 新增 7 列 | `SHOW COLUMNS FROM dm_dataset_query_intents LIKE 'routing_status'` |
| V-S2 | catalog API 返回 `routing_status`/`avoid_when`/`clarify_when` | tinker 调用 `buildDatasetCatalogForUser(1)` 检查 intents[0] 键 |
| V-S3 | `dm_table_columns` 新增 `snapshot_metric`/`semantic_tags` | `SHOW COLUMNS FROM dm_table_columns LIKE 'snapshot_metric'` |
| V-S4 | 字段 CSV 导出 13 列（含 `snapshot_metric`/`has_formula_config`） | 下载 CSV 验证表头 |
| V-S5 | `dm_field_semantic_index` 表已创建 | tinker `Schema::hasTable(...)` |
| V-S6 | `/skill/field-semantic-index` 路由可访问 | HTTP GET 返回 200 + `entry_count` |

---

## 执行顺序

```
S-1（迁移 intents 新字段）
  → S-2（更新 Service 读写 intents 新字段）
  → S-3（迁移 dm_table_columns 快照字段）
  → S-4（更新字段导出含 snapshot_metric + has_formula_config）
  → S-5（P1：语义索引表 + API）
```

P0 阶段（S-1 ~ S-4）完成后，客户端即可基于 catalog 中的 `routing_status`/`avoid_when`/`clarify_when` 实现意图路由，字段 CSV 携带 `snapshot_metric` 可防止 AI 聚合快照字段。S-5 为 P1，数据录入完成后再接入客户端语义搜索。
