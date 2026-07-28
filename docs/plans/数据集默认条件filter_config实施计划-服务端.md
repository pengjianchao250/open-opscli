# 数据集默认条件（filter_config）服务端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 filter_config 从后台配置到元数据下发（query-metadata + CSV 导出）与查询强制应用的服务端链路（需求 R1/R2/R3）。

**Architecture:** 新增 `Support/` 纯函数类（filter_config 提取、日期预设解析）作为全包唯一提取入口；在 `DatasetSkillService::buildExportPayloadForUser()` 统一挂载字段级 `filter_config` 与数据集级 `filter_configs`，query-metadata 与三个 CSV 导出免费复用；查询侧在 `SimpleQueryBuilder` 的简化参数层合并默认条件（复用既有 buildFilters/innerWhere 管线），`CliQueryService::executeForUser()` 完整入口做 where 树级兜底。

**Tech Stack:** PHP 8 / Laravel / PHPUnit / Carbon

**需求文档:** `/Users/mask/python3/opscli/docs/design/数据集默认条件filter_config接入需求.md`（已评审定稿，评审结论见其第六节）

**工作目录:** 包仓库 `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/`（自带 .git，直接在此提交）；运行命令基目录 `/Applications/MxSrvs/www/auto-scheduler/`。

## Global Constraints

- 所有代码注释必须使用中文，公开方法必须有中文 docstring 式注释（用户全局规范）
- 只允许 `git commit` 到本地分支，**任何时候不得 `git push`**
- CSV 新增列必须**行尾追加**，表头名称固定：字段 CSV 加 `filter_config`，数据集 CSV 加 `filter_config_count`、`filter_config_names`（评审结论 6）
- 合并规则：`required` 静默 AND 合并 + 同值/子集去重（评审结论 1、2）；`optional` 用户同字段条件优先
- 操作符映射：`equals`→`eq`、`notEquals`→`neq`、`gt/gte/lt/lte` 同名、多枚举值→`in`（评审结论 4，`Converters/QueryBuilder.php:4415` 已确认支持 IN）
- 日期预设在**查询执行时刻**解析，时区 Asia/Shanghai（评审结论 5）
- 度量字段 `filter_agg != none` 按 having 语义纳入本期（评审结论 3）
- 查询结果类导出（图表导出）不在本期范围（评审结论 7）
- `enabled=false` 的配置全链路忽略；`dm_table_columns.field_config` 与 `dm_sql_metrics.field_config` 均未做 casts，读取时需手动 json_decode

---

### Task 1: FilterConfig 提取助手（Support 纯函数类）

**Files:**
- Create: `src/Support/FilterConfig.php`
- Test: `tests/FilterConfigTest.php`

**Interfaces:**
- Consumes: 无（纯函数，仅依赖 PHP 标准库）
- Produces: `FilterConfig::extract($fieldConfig): ?array` —— 入参为 field_config 原始 JSON 字符串或已解码数组；返回规范化数组 `['type','enabled','operator','filter_type','enum_value','value','filter_agg']`，未配置/未启用/解析失败返回 `null`。Task 3/4/5/6/7 全部依赖此方法。

- [ ] **Step 1: 查看现有测试文件风格，确定 namespace 与基类写法**

Run: `head -30 /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/tests/DashboardDetailConfigTest.php`
记录其 namespace、use 语句与基类，新测试文件沿用同样式（下面代码默认 `PHPUnit\Framework\TestCase`，如现有测试用 Laravel TestCase 则同步调整）。

- [ ] **Step 2: 编写失败测试**

```php
<?php

namespace Aukey\DataMetrics\Tests;

use Aukey\DataMetrics\Support\FilterConfig;
use PHPUnit\Framework\TestCase;

class FilterConfigTest extends TestCase
{
    /** 启用的 filter_config 应返回规范化数组，缺省键补默认值 */
    public function testExtractEnabledConfig(): void
    {
        $json = json_encode([
            'displayed' => ['type' => 'text'],
            'filter_config' => [
                'type' => 'required', 'enabled' => true, 'operator' => 'equals',
                'enum_value' => ['QUARTER'], 'value' => null,
                'filter_agg' => 'none', 'filter_type' => 'enum',
            ],
        ]);
        $result = FilterConfig::extract($json);
        $this->assertSame('required', $result['type']);
        $this->assertSame('equals', $result['operator']);
        $this->assertSame(['QUARTER'], $result['enum_value']);
        $this->assertSame('none', $result['filter_agg']);
    }

    /** enabled=false 视为未配置 */
    public function testExtractDisabledReturnsNull(): void
    {
        $json = json_encode(['filter_config' => ['enabled' => false, 'operator' => 'equals']]);
        $this->assertNull(FilterConfig::extract($json));
    }

    /** 无 filter_config 键 / 空入参 / 非法 JSON 均返回 null */
    public function testExtractMissingOrInvalidReturnsNull(): void
    {
        $this->assertNull(FilterConfig::extract(json_encode(['sort_type' => ['type' => 'none']])));
        $this->assertNull(FilterConfig::extract(null));
        $this->assertNull(FilterConfig::extract(''));
        $this->assertNull(FilterConfig::extract('{invalid json'));
    }

    /** 缺省键补默认值：type=required、operator=equals、filter_type=enum、filter_agg=none */
    public function testExtractFillsDefaults(): void
    {
        $result = FilterConfig::extract(json_encode(['filter_config' => ['enabled' => true]]));
        $this->assertSame('required', $result['type']);
        $this->assertSame('equals', $result['operator']);
        $this->assertSame('enum', $result['filter_type']);
        $this->assertSame([], $result['enum_value']);
        $this->assertSame('none', $result['filter_agg']);
    }
}
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/FilterConfigTest.php`
Expected: FAIL —— `Class "Aukey\DataMetrics\Support\FilterConfig" not found`

- [ ] **Step 4: 实现 FilterConfig**

```php
<?php

namespace Aukey\DataMetrics\Support;

/**
 * 字段级默认条件（filter_config）提取与规范化工具。
 *
 * dm_table_columns / dm_sql_metrics 的 field_config 为 JSON 字符串（模型未做 casts），
 * 其中 filter_config 键即该字段在数据集下的默认条件。本类是全包唯一的提取入口，
 * 供元数据下发（DatasetSkillService）与查询注入（SimpleQueryBuilder）复用，
 * 避免出现多套解析口径。
 */
class FilterConfig
{
    /**
     * 从 field_config JSON 中提取已启用的 filter_config 并规范化。
     *
     * @param string|array|null $fieldConfig field_config 原始 JSON 字符串或已解码数组
     * @return array|null 规范化配置；未配置 / enabled=false / 解析失败返回 null
     */
    public static function extract($fieldConfig): ?array
    {
        if (empty($fieldConfig)) {
            return null;
        }
        // 兼容字符串与已解码数组两种入参（不同调用方读取路径不同）
        $config = is_array($fieldConfig) ? $fieldConfig : json_decode((string) $fieldConfig, true);
        if (!is_array($config)) {
            return null;
        }
        $fc = $config['filter_config'] ?? null;
        // enabled=false 或缺失时视为未配置，全链路忽略（需求 2.2 节）
        if (!is_array($fc) || empty($fc['enabled'])) {
            return null;
        }

        return [
            'type'        => $fc['type'] ?? 'required',
            'enabled'     => true,
            'operator'    => $fc['operator'] ?? 'equals',
            'filter_type' => $fc['filter_type'] ?? 'enum',
            'enum_value'  => is_array($fc['enum_value'] ?? null) ? $fc['enum_value'] : [],
            'value'       => $fc['value'] ?? null,
            'filter_agg'  => $fc['filter_agg'] ?? 'none',
        ];
    }
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/FilterConfigTest.php`
Expected: PASS（4 tests）

- [ ] **Step 6: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Support/FilterConfig.php tests/FilterConfigTest.php
git commit -m "feat(filter-config): 新增字段默认条件提取助手 FilterConfig::extract"
```

---

### Task 2: 日期预设解析器 FilterDatePreset

**Files:**
- Create: `src/Support/FilterDatePreset.php`
- Test: `tests/FilterDatePresetTest.php`

**Interfaces:**
- Consumes: Carbon（Laravel 自带）
- Produces: `FilterDatePreset::resolve($value, ?CarbonInterface $now = null): ?array` —— 入参为 filter_config 的 `value`（预设字符串如 `thisQuarter`，或 exact 形态的 `[startDate, endDate]` 数组）；返回 `['YYYY-MM-DD', 'YYYY-MM-DD']`，无法解析返回 `null`。Task 5 依赖。

- [ ] **Step 1: 编写失败测试**

```php
<?php

namespace Aukey\DataMetrics\Tests;

use Aukey\DataMetrics\Support\FilterDatePreset;
use Carbon\Carbon;
use PHPUnit\Framework\TestCase;

class FilterDatePresetTest extends TestCase
{
    /** 固定"当前时刻"保证测试可重复：2026-07-15（周三，Q3） */
    private function now(): Carbon
    {
        return Carbon::create(2026, 7, 15, 10, 0, 0, 'Asia/Shanghai');
    }

    public function testResolvePresets(): void
    {
        $now = $this->now();
        $this->assertSame(['2026-07-15', '2026-07-15'], FilterDatePreset::resolve('today', $now));
        $this->assertSame(['2026-07-14', '2026-07-14'], FilterDatePreset::resolve('yesterday', $now));
        $this->assertSame(['2026-07-01', '2026-07-31'], FilterDatePreset::resolve('thisMonth', $now));
        $this->assertSame(['2026-06-01', '2026-06-30'], FilterDatePreset::resolve('lastMonth', $now));
        $this->assertSame(['2026-07-01', '2026-09-30'], FilterDatePreset::resolve('thisQuarter', $now));
        $this->assertSame(['2026-04-01', '2026-06-30'], FilterDatePreset::resolve('lastQuarter', $now));
        $this->assertSame(['2026-01-01', '2026-12-31'], FilterDatePreset::resolve('thisYear', $now));
        $this->assertSame(['2026-07-01', '2026-07-15'], FilterDatePreset::resolve('monthToDate', $now));
        $this->assertSame(['2026-01-01', '2026-07-15'], FilterDatePreset::resolve('yearToDate', $now));
        $this->assertSame(['2026-07-09', '2026-07-15'], FilterDatePreset::resolve('past7Days', $now));
        $this->assertSame(['2026-06-16', '2026-07-15'], FilterDatePreset::resolve('past30Days', $now));
    }

    /** exact 形态：[start, end] 数组原样规范化返回 */
    public function testResolveExactRange(): void
    {
        $this->assertSame(
            ['2026-01-01', '2026-01-31'],
            FilterDatePreset::resolve(['2026-01-01', '2026-01-31'], $this->now())
        );
    }

    /** 未知预设 / 空值返回 null */
    public function testResolveUnknownReturnsNull(): void
    {
        $this->assertNull(FilterDatePreset::resolve('notAPreset', $this->now()));
        $this->assertNull(FilterDatePreset::resolve(null, $this->now()));
        $this->assertNull(FilterDatePreset::resolve([], $this->now()));
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/FilterDatePresetTest.php`
Expected: FAIL —— Class not found

- [ ] **Step 3: 实现 FilterDatePreset**

```php
<?php

namespace Aukey\DataMetrics\Support;

use Carbon\Carbon;
use Carbon\CarbonInterface;

/**
 * 日期预设解析器：把 filter_config 中的日期预设标识解析为具体日期区间。
 *
 * 预设清单与后台配置表单一致（datasets.blade.php FILTER_DATE_PRESETS，18 个）。
 * 在查询执行时刻解析（评审结论 5），保证同一配置随时间自然滚动，
 * 避免下发静态区间导致缓存过期后口径漂移。时区固定 Asia/Shanghai。
 */
class FilterDatePreset
{
    /**
     * 解析日期值为 [起始日期, 结束日期]。
     *
     * @param string|array|null $value 预设标识（如 thisQuarter）或 exact 形态的 [start, end]
     * @param CarbonInterface|null $now 当前时刻（测试注入用，默认取 Asia/Shanghai 当前时间）
     * @return array|null ['YYYY-MM-DD', 'YYYY-MM-DD']；无法解析返回 null
     */
    public static function resolve($value, ?CarbonInterface $now = null): ?array
    {
        $now = $now ? $now->copy()->setTimezone('Asia/Shanghai') : Carbon::now('Asia/Shanghai');

        // exact 形态：后台保存的 [startDate, endDate] 数组，原样规范化
        if (is_array($value)) {
            if (count($value) === 2 && !empty($value[0]) && !empty($value[1])) {
                return [
                    Carbon::parse($value[0])->format('Y-m-d'),
                    Carbon::parse($value[1])->format('Y-m-d'),
                ];
            }
            return null;
        }
        if (!is_string($value) || $value === '') {
            return null;
        }

        // 预设标识 → 区间计算；周口径按周一为一周起点（ISO），如与前台展示口径不一致以前台为准调整
        [$start, $end] = match ($value) {
            'today'           => [$now->copy(), $now->copy()],
            'yesterday'       => [$now->copy()->subDay(), $now->copy()->subDay()],
            'beforeYesterday' => [$now->copy()->subDays(2), $now->copy()->subDays(2)],
            'thisWeek'        => [$now->copy()->startOfWeek(), $now->copy()->endOfWeek()],
            'lastWeek'        => [$now->copy()->subWeek()->startOfWeek(), $now->copy()->subWeek()->endOfWeek()],
            'thisMonth'       => [$now->copy()->startOfMonth(), $now->copy()->endOfMonth()],
            'lastMonth'       => [$now->copy()->subMonthNoOverflow()->startOfMonth(), $now->copy()->subMonthNoOverflow()->endOfMonth()],
            'thisQuarter'     => [$now->copy()->startOfQuarter(), $now->copy()->endOfQuarter()],
            'lastQuarter'     => [$now->copy()->subQuarter()->startOfQuarter(), $now->copy()->subQuarter()->endOfQuarter()],
            'thisYear'        => [$now->copy()->startOfYear(), $now->copy()->endOfYear()],
            'lastYear'        => [$now->copy()->subYear()->startOfYear(), $now->copy()->subYear()->endOfYear()],
            'monthToDate'     => [$now->copy()->startOfMonth(), $now->copy()],
            'yearToDate'      => [$now->copy()->startOfYear(), $now->copy()],
            'past7Days'       => [$now->copy()->subDays(6), $now->copy()],
            'past30Days'      => [$now->copy()->subDays(29), $now->copy()],
            'past90Days'      => [$now->copy()->subDays(89), $now->copy()],
            'past12Months'    => [$now->copy()->subMonthsNoOverflow(12)->addDay(), $now->copy()],
            default           => [null, null],
        };

        if ($start === null) {
            return null;
        }
        return [$start->format('Y-m-d'), $end->format('Y-m-d')];
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/FilterDatePresetTest.php`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Support/FilterDatePreset.php tests/FilterDatePresetTest.php
git commit -m "feat(filter-config): 新增日期预设解析器（执行时刻解析，Asia/Shanghai）"
```

---

### Task 3: 元数据挂载 —— buildExportPayloadForUser 统一挂 filter_config(s) + query-metadata 下发（R1）

**Files:**
- Modify: `src/Services/DatasetSkillService.php:77-94`（buildExportPayloadForUser）、`:108-170`（buildQueryMetadataForUser 的 `$datasetKeepKeys`）
- Test: `tests/DatasetSkillFilterConfigAttachTest.php`

**Interfaces:**
- Consumes: Task 1 的 `FilterConfig::extract()`
- Produces:
  - 字段行（`$payload['fields']` 每行）新增键 `'filter_config' => ?array`（规范化配置或 null）
  - 数据集行（`$payload['datasets']` 每行）新增键 `'filter_configs' => array`，条目结构 `['column_name','verbose_name','field_type','component_dataset_alias','filter_config']`（自身字段的 component_dataset_alias = 数据集自身 alias）
  - query-metadata 响应数据集对象含 `filter_configs`（Task 4 的 CSV 导出直接消费同一批行数据）

- [ ] **Step 1: 编写失败测试（纯数组/Collection 输入，不依赖 DB）**

新增两个 protected 方法后通过测试子类暴露。测试文件：

```php
<?php

namespace Aukey\DataMetrics\Tests;

use Aukey\DataMetrics\Services\DatasetSkillService;
use PHPUnit\Framework\TestCase;

/** 通过子类暴露 protected 挂载方法，避免依赖数据库 */
class ExposedDatasetSkillService extends DatasetSkillService
{
    public function __construct()
    {
        // 跳过父类依赖注入：挂载方法是纯函数，不触达任何服务属性
    }

    public function callAttachFieldFilterConfigs($fields, $columns, $metrics)
    {
        return $this->attachFieldFilterConfigs($fields, $columns, $metrics);
    }

    public function callAttachDatasetFilterConfigs($datasets, $fields, array $selectColumnsMap)
    {
        return $this->attachDatasetFilterConfigs($datasets, $fields, $selectColumnsMap);
    }
}

class DatasetSkillFilterConfigAttachTest extends TestCase
{
    private function enabledConfigJson(): string
    {
        return json_encode(['filter_config' => [
            'type' => 'required', 'enabled' => true, 'operator' => 'equals',
            'enum_value' => ['QUARTER'], 'value' => null, 'filter_agg' => 'none', 'filter_type' => 'enum',
        ]]);
    }

    /** 字段行按 (table_id, field_name) 回查原始 field_config 并挂载规范化结果 */
    public function testAttachFieldFilterConfigs(): void
    {
        $service = new ExposedDatasetSkillService();
        $fields = collect([
            ['table_id' => 1, 'dataset_alias' => 'ds_a', 'field_name' => 'date_type', 'field_type' => 'dimension'],
            ['table_id' => 1, 'dataset_alias' => 'ds_a', 'field_name' => 'gmv', 'field_type' => 'metric'],
        ]);
        $columns = collect([
            (object) ['table_id' => 1, 'column_name' => 'date_type', 'field_config' => $this->enabledConfigJson()],
        ]);
        $metrics = collect([
            (object) ['table_id' => 1, 'metric_name' => 'gmv', 'field_config' => null],
        ]);

        $result = $service->callAttachFieldFilterConfigs($fields, $columns, $metrics)->values()->all();
        $this->assertSame('required', $result[0]['filter_config']['type']);
        $this->assertNull($result[1]['filter_config']);
    }

    /** 数据集行聚合：自身字段 + select_columns 组件字段中所有启用配置 */
    public function testAttachDatasetFilterConfigs(): void
    {
        $service = new ExposedDatasetSkillService();
        $fc = ['type' => 'required', 'enabled' => true, 'operator' => 'equals',
               'filter_type' => 'enum', 'enum_value' => ['QUARTER'], 'value' => null, 'filter_agg' => 'none'];
        $datasets = collect([
            ['table_id' => 1, 'dataset_alias' => 'ds_a', 'dataset_name' => '主数据集'],
            ['table_id' => 2, 'dataset_alias' => 'ds_comp', 'dataset_name' => '组件数据集'],
        ]);
        $fields = collect([
            // 自身字段带配置
            ['table_id' => 1, 'dataset_alias' => 'ds_a', 'field_name' => 'date_type',
             'verbose_name' => '日期类型', 'field_type' => 'dimension', 'filter_config' => $fc],
            // 组件数据集字段带配置（通过 select_columns 关联到 ds_a）
            ['table_id' => 2, 'dataset_alias' => 'ds_comp', 'field_name' => 'platform_name',
             'verbose_name' => '平台', 'field_type' => 'dimension', 'filter_config' => $fc],
            // 无配置字段不进入聚合
            ['table_id' => 1, 'dataset_alias' => 'ds_a', 'field_name' => 'gmv',
             'verbose_name' => 'GMV', 'field_type' => 'metric', 'filter_config' => null],
        ]);
        $selectColumnsMap = ['ds_a' => [
            ['column_name' => 'platform_name', 'verbose_name' => '平台', 'component_dataset_alias' => 'ds_comp'],
        ]];

        $result = $service->callAttachDatasetFilterConfigs($datasets, $fields, $selectColumnsMap)->values()->all();
        $entries = $result[0]['filter_configs'];
        $this->assertCount(2, $entries);
        $this->assertSame('date_type', $entries[0]['column_name']);
        $this->assertSame('ds_a', $entries[0]['component_dataset_alias']);
        $this->assertSame('dimension', $entries[0]['field_type']);
        $this->assertSame('platform_name', $entries[1]['column_name']);
        $this->assertSame('ds_comp', $entries[1]['component_dataset_alias']);
        // 未配置默认条件的数据集返回空数组，字段结构稳定（需求 R1 规则 4）
        $this->assertSame([], $result[1]['filter_configs']);
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/DatasetSkillFilterConfigAttachTest.php`
Expected: FAIL —— `Call to undefined method ... attachFieldFilterConfigs`
注意：若 `DatasetSkillService` 构造函数为空子类报错（父类构造有必选参数），把 `ExposedDatasetSkillService` 的构造改为不调用 parent（如上），或改用 ReflectionMethod 调用。

- [ ] **Step 3: 在 DatasetSkillService 中实现两个挂载方法**

在类中新增（放在 loadMetrics 之后）：

```php
    /**
     * 为字段行挂载字段级默认条件（filter_config）。
     *
     * 以 (table_id, field_name) 为键回查 loadColumns/loadMetrics 的原始 field_config，
     * 经 FilterConfig::extract 规范化后写入字段行的 filter_config 键（未配置为 null）。
     * 挂载发生在 buildExportPayloadForUser 中，query-metadata 与 CSV 导出统一复用。
     */
    protected function attachFieldFilterConfigs($fields, $columns, $metrics)
    {
        $configMap = [];
        // 维度字段：dm_table_columns.column_name
        foreach ($columns as $column) {
            $extracted = \Aukey\DataMetrics\Support\FilterConfig::extract($column->field_config ?? null);
            if ($extracted !== null) {
                $configMap[$column->table_id . '|' . $column->column_name] = $extracted;
            }
        }
        // 度量字段：dm_sql_metrics.metric_name（评审结论 3：度量纳入本期）
        foreach ($metrics as $metric) {
            $extracted = \Aukey\DataMetrics\Support\FilterConfig::extract($metric->field_config ?? null);
            if ($extracted !== null) {
                $configMap[$metric->table_id . '|' . $metric->metric_name] = $extracted;
            }
        }

        return $fields->map(function (array $row) use ($configMap) {
            $key = ($row['table_id'] ?? '') . '|' . ($row['field_name'] ?? '');
            $row['filter_config'] = $configMap[$key] ?? null;
            return $row;
        });
    }

    /**
     * 为数据集行聚合 filter_configs（需求 R1）。
     *
     * 聚合范围 = 数据集自身字段 + select_columns 关联的组件数据集字段中
     * 所有启用了 filter_config 的字段。未配置的数据集返回空数组（结构稳定）。
     */
    protected function attachDatasetFilterConfigs($datasets, $fields, array $selectColumnsMap)
    {
        // 建 (dataset_alias, field_name) → 字段行索引，组件字段跨数据集查找用
        $fieldIndex = [];
        foreach ($fields as $row) {
            if (!empty($row['filter_config'])) {
                $fieldIndex[($row['dataset_alias'] ?? '') . '|' . ($row['field_name'] ?? '')] = $row;
            }
        }

        $toEntry = function (array $fieldRow, string $componentAlias): array {
            return [
                'column_name'             => $fieldRow['field_name'],
                'verbose_name'            => $fieldRow['verbose_name'] ?? '',
                'field_type'              => $fieldRow['field_type'] ?? 'dimension',
                'component_dataset_alias' => $componentAlias,
                'filter_config'           => $fieldRow['filter_config'],
            ];
        };

        return $datasets->map(function (array $dataset) use ($fields, $fieldIndex, $selectColumnsMap, $toEntry) {
            $alias = (string) ($dataset['dataset_alias'] ?? '');
            $entries = [];
            // 自身字段：component_dataset_alias 取数据集自身 alias（与 select_columns 条目结构对齐）
            foreach ($fields as $row) {
                if (($row['dataset_alias'] ?? '') === $alias && !empty($row['filter_config'])) {
                    $entries[] = $toEntry($row, $alias);
                }
            }
            // 组件关联字段：按 select_columns 的 (component_dataset_alias, column_name) 回查
            foreach ($selectColumnsMap[$alias] ?? [] as $col) {
                $key = ($col['component_dataset_alias'] ?? '') . '|' . ($col['column_name'] ?? '');
                if (isset($fieldIndex[$key])) {
                    $entries[] = $toEntry($fieldIndex[$key], (string) $col['component_dataset_alias']);
                }
            }
            $dataset['filter_configs'] = $entries;
            return $dataset;
        });
    }
```

- [ ] **Step 4: 在 buildExportPayloadForUser 中接线**

修改 `src/Services/DatasetSkillService.php:85-87`，在 `$fields = $this->buildFields(...)` 之后插入：

```php
        $datasets = $this->buildDatasets($tables, $selectColumnsMap);
        $fields   = $this->buildFields($tables, $columns, $metrics);
        // 挂载字段级默认条件与数据集级聚合（需求 R1/R3：query-metadata 与 CSV 导出统一复用）
        $fields   = $this->attachFieldFilterConfigs($fields, $columns, $metrics);
        $datasets = $this->attachDatasetFilterConfigs($datasets, $fields, $selectColumnsMap);
        $this->validateFieldsForExport($fields);
```

注意：`validateFieldsForExport` 若对字段行做严格键校验，先运行 Step 6 观察是否报错，报错则在其允许键清单中加入 `filter_config`。

- [ ] **Step 5: queryMetadata 下发 —— datasetKeepKeys 加 filter_configs**

修改 `src/Services/DatasetSkillService.php:116`：

```php
        $datasetKeepKeys = ['table_id', 'dataset_alias', 'dataset_name', 'dataset_category', 'inner_where_enabled', 'description', 'remarks', 'filter_configs', 'select_columns'];
```

- [ ] **Step 6: 运行单元测试 + 真实服务验证**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/DatasetSkillFilterConfigAttachTest.php`
Expected: PASS

Run（换成 QA 环境一个真实授权用户 ID 与已配置 filter_config 的数据集别名）:
```bash
cd /Applications/MxSrvs/www/auto-scheduler
php artisan tinker --execute="
\$r = app(\Aukey\DataMetrics\Services\DatasetSkillService::class)->buildQueryMetadataForUser(1, 'ds_d35ac6f3910c');
echo json_encode(\$r['datasets'][0]['filter_configs'] ?? 'KEY_MISSING', JSON_UNESCAPED_UNICODE);
"
```
Expected: 输出 filter_configs 数组（含已配置字段），而非 `"KEY_MISSING"`；未配置数据集输出 `[]`

- [ ] **Step 7: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Services/DatasetSkillService.php tests/DatasetSkillFilterConfigAttachTest.php
git commit -m "feat(filter-config): query-metadata 数据集下发 filter_configs（自身+组件字段聚合）"
```

---

### Task 4: CSV 导出列 —— 字段 CSV 加 filter_config、数据集 CSV 加摘要列（R3）

**Files:**
- Modify: `src/Services/DatasetSkillService.php:264-278`（字段 CSV 表头）、`:620-638`（toFieldExportRow）、`:308-318`（数据集 CSV 表头）、`:640-656`（toDatasetExportRow）

**Interfaces:**
- Consumes: Task 3 挂载后的字段行 `filter_config` 键与数据集行 `filter_configs` 键
- Produces: `dataset_fields_{version}.csv` 行尾新列 `filter_config`（JSON 字符串或空）；`datasets_{version}.csv` 行尾新列 `filter_config_count`、`filter_config_names`（`|` 分隔，与既有 `select_column_names` 分隔符约定一致）

- [ ] **Step 1: 修改字段 CSV 表头与行**

`createFieldExportResponseForUser` 表头数组（264-278 行）末尾追加：

```php
                'snapshot_metric',
                'has_formula_config',
                'filter_config',
```

`toFieldExportRow`（620-638 行）末尾追加：

```php
            $row['snapshot_metric'] ?? 0,
            $row['has_formula_config'] ?? 0,
            // 字段级默认条件：规范化 JSON 字符串下发，未配置为空（需求 R3 规则 1）
            !empty($row['filter_config'])
                ? json_encode($row['filter_config'], JSON_UNESCAPED_UNICODE)
                : '',
```

- [ ] **Step 2: 修改数据集 CSV 表头与行**

`createDatasetExportResponseForUser` 表头数组（308-318 行）末尾追加：

```php
                'select_column_count',
                'select_column_names',
                'filter_config_count',
                'filter_config_names',
```

`toDatasetExportRow`（640-656 行）末尾追加：

```php
            count($selectColumns),
            implode('|', array_column($selectColumns, 'column_name')),
            // 默认条件摘要列：规划器选表阶段低成本感知（需求 R3 规则 2）
            count($row['filter_configs'] ?? []),
            implode('|', array_column($row['filter_configs'] ?? [], 'column_name')),
```

- [ ] **Step 3: 验证 CSV 输出**

```bash
cd /Applications/MxSrvs/www/auto-scheduler
php artisan tinker --execute="
\$svc = app(\Aukey\DataMetrics\Services\DatasetSkillService::class);
\$p = \$svc->buildExportPayloadForUser(1);
\$row = \$svc->buildQueryMetadataForUser(1, 'ds_d35ac6f3910c')['datasets'][0];
echo '数据集摘要: count=' . count(\$row['filter_configs']) . PHP_EOL;
"
```
再通过接口下载实测（QA 环境带认证 token）：
```bash
curl -s -H "Authorization: Bearer <QA_JWT>" \
  "https://ops.api.qa.aukeyit.com/api/v1/data-metrics/datasets/skill/export-datasets" | head -2
```
Expected: 表头行尾出现 `filter_config_count,filter_config_names`；已配置数据集行计数 > 0。字段 CSV 同法验证 `filter_config` 列。

- [ ] **Step 4: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Services/DatasetSkillService.php
git commit -m "feat(filter-config): 字段/数据集 CSV 行尾新增 filter_config 下发列（旧客户端兼容）"
```

---

### Task 5: SimpleQueryBuilder 简化查询入口注入默认条件（R2 主路径）

**Files:**
- Modify: `src/Services/SimpleQueryBuilder.php:65-145`（build 接线）、类内新增三个方法
- Test: `tests/SimpleQueryBuilderDefaultFiltersTest.php`

**Interfaces:**
- Consumes: Task 1 `FilterConfig::extract()`、Task 2 `FilterDatePreset::resolve()`；模型 `Table`、`TableColumn`、`SqlMetric`、`SelectColumnRelation`
- Produces:
  - `mergeDefaultFilters(array $userFilters, array $defaults): array`（纯函数，Task 7 复用其合并语义）
  - `loadDefaultFilterConfigs(Table $table): array` —— 默认条件列表，元素 `['field','operator','value','_type','_filter_agg','_field_type']`，operator 已标准化（eq/neq/gt/gte/lt/lte/in），日期预设已解析为 gte/lte 两条
  - build() 生效：简化查询自动携带默认条件

- [ ] **Step 1: 确认 standardizeOperator 对已标准化操作符透传**

Run: `grep -n -A 8 "function standardizeOperator" /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Services/SimpleQueryBuilder.php`
Expected: 形如 `return self::OPERATOR_MAP[$operator] ?? $operator;`（映射不命中时透传）。若不是透传语义（如抛异常），在该方法中补充放行清单 `['eq','neq','gt','gte','lt','lte','in']` 后再继续。

- [ ] **Step 2: 编写合并纯函数的失败测试**

```php
<?php

namespace Aukey\DataMetrics\Tests;

use Aukey\DataMetrics\Services\SimpleQueryBuilder;
use PHPUnit\Framework\TestCase;

class SimpleQueryBuilderDefaultFiltersTest extends TestCase
{
    private function merge(array $userFilters, array $defaults): array
    {
        $builder = new SimpleQueryBuilder();
        $method = new \ReflectionMethod($builder, 'mergeDefaultFilters');
        $method->setAccessible(true);
        return $method->invoke($builder, $userFilters, $defaults);
    }

    private function requiredDefault(): array
    {
        return ['field' => 'date_type', 'operator' => 'eq', 'value' => 'QUARTER',
                '_type' => 'required', '_filter_agg' => 'none', '_field_type' => 'dimension'];
    }

    /** required：用户未提供该字段 → 注入 */
    public function testRequiredInjectedWhenMissing(): void
    {
        $result = $this->merge([['field' => 'gmv', 'operator' => '>', 'value' => 0]], [$this->requiredDefault()]);
        $this->assertCount(2, $result);
        $this->assertSame('date_type', $result[1]['field']);
    }

    /** required + 用户同字段冲突值 → 静默 AND 合并，两条都保留（评审结论 1） */
    public function testRequiredConflictKeepsBoth(): void
    {
        $user = [['field' => 'date_type', 'operator' => 'eq', 'value' => 'MONTH']];
        $result = $this->merge($user, [$this->requiredDefault()]);
        $this->assertCount(2, $result);
    }

    /** required + 用户同值或子集 → 合并去重，只留用户条件（评审结论 2） */
    public function testRequiredDedupeOnSameOrSubsetValue(): void
    {
        $same = $this->merge([['field' => 'date_type', 'operator' => 'eq', 'value' => 'QUARTER']], [$this->requiredDefault()]);
        $this->assertCount(1, $same);

        $default = $this->requiredDefault();
        $default['operator'] = 'in';
        $default['value'] = ['QUARTER', 'MONTH'];
        $subset = $this->merge([['field' => 'date_type', 'operator' => 'eq', 'value' => 'MONTH']], [$default]);
        $this->assertCount(1, $subset);
    }

    /** optional：用户已提供同字段条件 → 不注入；未提供 → 注入 */
    public function testOptionalRespectsUserFilter(): void
    {
        $optional = $this->requiredDefault();
        $optional['_type'] = 'optional';
        $withUser = $this->merge([['field' => 'date_type', 'operator' => 'eq', 'value' => 'MONTH']], [$optional]);
        $this->assertCount(1, $withUser);
        $this->assertSame('MONTH', $withUser[0]['value']);
        $withoutUser = $this->merge([], [$optional]);
        $this->assertCount(1, $withoutUser);
    }

    /** 度量 filter_agg != none 不在 where 层合并（Task 6 走 having） */
    public function testMetricHavingDefaultSkipped(): void
    {
        $having = ['field' => 'gmv', 'operator' => 'gt', 'value' => 100,
                   '_type' => 'required', '_filter_agg' => 'sum', '_field_type' => 'metric'];
        $this->assertCount(0, $this->merge([], [$having]));
    }

    /** 用户 filter 字段带 alias 前缀时同字段判定仍生效 */
    public function testFieldMatchIgnoresAliasPrefix(): void
    {
        $user = [['field' => 'ds_a.date_type', 'operator' => 'eq', 'value' => 'QUARTER']];
        $this->assertCount(1, $this->merge($user, [$this->requiredDefault()]));
    }
}
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/SimpleQueryBuilderDefaultFiltersTest.php`
Expected: FAIL —— 方法不存在

- [ ] **Step 4: 实现 loadDefaultFilterConfigs / toSimpleFilters / mergeDefaultFilters**

在 SimpleQueryBuilder 类内新增（文件头补充 `use Aukey\DataMetrics\Models\TableColumn; use Aukey\DataMetrics\Models\SqlMetric; use Aukey\DataMetrics\Support\FilterConfig; use Aukey\DataMetrics\Support\FilterDatePreset;`）：

```php
    /**
     * 加载数据集的全部默认条件并转换为简化 filter 形态。
     *
     * 覆盖范围（需求 R2）：本表维度字段 + 本表度量字段 + select_columns 关联的
     * 组件数据集字段。返回元素已完成操作符标准化与日期预设解析，
     * 可直接进入 mergeDefaultFilters 与既有 buildFilters 管线。
     */
    protected function loadDefaultFilterConfigs(Table $table): array
    {
        $defaults = [];
        $datasetAlias = (string) ($table->dataset_alias ?? '');

        // 1. 本表维度字段（dm_table_columns，过滤条件与 DatasetSkillService::loadColumns 对齐）
        $columns = TableColumn::query()
            ->where('table_id', $table->id)
            ->where('is_active', 1)
            ->whereNull('deleted_at')
            ->whereNull('chart_id')
            ->whereNotNull('field_config')
            ->get(['column_name', 'field_config']);
        foreach ($columns as $column) {
            $fc = FilterConfig::extract($column->field_config);
            if ($fc !== null) {
                array_push($defaults, ...$this->toSimpleFilters($column->column_name, $fc, 'dimension'));
            }
        }

        // 2. 本表度量字段（dm_sql_metrics，评审结论 3 纳入本期；过滤条件与 loadMetrics 对齐）
        $sqlMetrics = SqlMetric::query()
            ->where('table_id', $table->id)
            ->where('is_custom', 0)
            ->whereNull('deleted_at')
            ->whereNull('chart_id')
            ->whereNotNull('field_config')
            ->get(['metric_name', 'field_config']);
        foreach ($sqlMetrics as $metric) {
            $fc = FilterConfig::extract($metric->field_config);
            if ($fc !== null) {
                array_push($defaults, ...$this->toSimpleFilters($metric->metric_name, $fc, 'metric'));
            }
        }

        // 3. 组件关联字段：select_columns → 组件表 → 该列 filter_config（批量避免 N+1）
        $relations = SelectColumnRelation::query()
            ->where('dataset_alias', $datasetAlias)
            ->where('disable', false)
            ->whereNull('deleted_at')
            ->get(['column_name', 'component_dataset_alias']);
        if ($relations->isNotEmpty()) {
            $componentTables = Table::query()
                ->whereIn('dataset_alias', $relations->pluck('component_dataset_alias')->unique()->all())
                ->get(['id', 'dataset_alias'])
                ->keyBy('dataset_alias');
            $componentColumns = TableColumn::query()
                ->whereIn('table_id', $componentTables->pluck('id')->all())
                ->whereIn('column_name', $relations->pluck('column_name')->unique()->all())
                ->whereNull('deleted_at')
                ->whereNotNull('field_config')
                ->get(['table_id', 'column_name', 'field_config'])
                ->keyBy(fn ($c) => $c->table_id . '|' . $c->column_name);
            foreach ($relations as $relation) {
                $componentTable = $componentTables->get($relation->component_dataset_alias);
                if (!$componentTable) {
                    continue;
                }
                $column = $componentColumns->get($componentTable->id . '|' . $relation->column_name);
                $fc = $column ? FilterConfig::extract($column->field_config) : null;
                if ($fc !== null) {
                    array_push($defaults, ...$this->toSimpleFilters($relation->column_name, $fc, 'dimension'));
                }
            }
        }

        return $defaults;
    }

    /**
     * 单个 filter_config → 简化 filter 条目列表。
     *
     * 规则：多枚举值用 in（评审结论 4）；日期预设/exact 区间解析为 gte+lte 两条
     * （评审结论 5，执行时刻解析）；operator 映射 equals→eq、notEquals→neq。
     * isEmpty/isNotEmpty 暂不支持 → 跳过并保持行为不变（实现阶段确认 where 树能力后再放开）。
     */
    protected function toSimpleFilters(string $fieldName, array $fc, string $fieldType): array
    {
        $meta = ['_type' => $fc['type'], '_filter_agg' => $fc['filter_agg'], '_field_type' => $fieldType];
        $operatorMap = ['equals' => 'eq', 'notEquals' => 'neq', 'gt' => 'gt', 'gte' => 'gte', 'lt' => 'lt', 'lte' => 'lte'];
        $operator = $operatorMap[$fc['operator']] ?? null;
        if ($operator === null) {
            return [];
        }

        // 日期区间形态：value 为预设标识或 [start, end]，展开为主周期两条
        $range = FilterDatePreset::resolve($fc['value']);
        if ($range !== null) {
            return [
                array_merge(['field' => $fieldName, 'operator' => 'gte', 'value' => $range[0]], $meta),
                array_merge(['field' => $fieldName, 'operator' => 'lte', 'value' => $range[1]], $meta),
            ];
        }

        // 枚举/文本值：enum_value 优先，多值转 in
        $values = $fc['filter_type'] === 'enum' ? $fc['enum_value'] : (array) ($fc['value'] ?? []);
        $values = array_values(array_filter($values, fn ($v) => $v !== null && $v !== ''));
        if (empty($values)) {
            return [];
        }
        if (count($values) > 1 && $operator === 'eq') {
            return [array_merge(['field' => $fieldName, 'operator' => 'in', 'value' => $values], $meta)];
        }
        return [array_merge(['field' => $fieldName, 'operator' => $operator, 'value' => $values[0]], $meta)];
    }

    /**
     * 把默认条件合并进用户 filters（需求 R2 合并规则表）。
     *
     * - required：用户缺失时注入；同值/子集去重只留用户条件（评审结论 2）；
     *   冲突时静默 AND 合并两条都保留（评审结论 1）。
     * - optional：用户已提供同字段条件则跳过，否则注入。
     * - 度量 filter_agg != none 不在 where 层处理（having 语义走独立通道）。
     */
    protected function mergeDefaultFilters(array $userFilters, array $defaults): array
    {
        // 用户条件按裸字段名（去掉 alias 前缀）建索引
        $userByField = [];
        foreach ($userFilters as $filter) {
            $bare = ltrim(strrchr('.' . (string) ($filter['field'] ?? ''), '.'), '.');
            $userByField[$bare][] = $filter;
        }

        $merged = $userFilters;
        foreach ($defaults as $default) {
            if (($default['_field_type'] ?? '') === 'metric' && ($default['_filter_agg'] ?? 'none') !== 'none') {
                continue; // having 语义由 Task 6 通道处理
            }
            $field = $default['field'];
            $userConditions = $userByField[$field] ?? [];

            if (($default['_type'] ?? 'required') === 'optional') {
                if (!empty($userConditions)) {
                    continue; // optional：用户条件优先
                }
            } else {
                // required：同值/子集去重（用户条件值 ⊆ 默认值集合时不再注入）
                $defaultValues = is_array($default['value']) ? $default['value'] : [$default['value']];
                $covered = false;
                foreach ($userConditions as $condition) {
                    $userValues = is_array($condition['value'] ?? null) ? $condition['value'] : [$condition['value'] ?? null];
                    if (!array_diff($userValues, $defaultValues)) {
                        $covered = true;
                        break;
                    }
                }
                if ($covered) {
                    continue;
                }
            }
            // 注入（内部 _ 前缀键不下发给 buildFilters 管线）
            $merged[] = ['field' => $field, 'operator' => $default['operator'], 'value' => $default['value']];
        }
        return $merged;
    }
```

- [ ] **Step 5: build() 接线**

修改 `build()` 第 77-81 行：

```php
        // 3. 处理 filters → 标准 where 树；先合并数据集默认条件（需求 R2：查询强制应用）
        $mergedFilters = $this->mergeDefaultFilters(
            $simple['filters'] ?? [],
            $this->loadDefaultFilterConfigs($table)
        );
        $whereConditions = $this->buildFilters(
            $mergedFilters,
            $datasetAlias,
            $fields,
            $table
        );
```

- [ ] **Step 6: 运行测试确认通过 + 回归既有测试**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/`
Expected: 新增 6 tests PASS，既有测试无回归

- [ ] **Step 7: QA 环境真实查询验证**

```bash
curl -s -X POST -H "Authorization: Bearer <QA_JWT>" -H "Content-Type: application/json" \
  "https://ops.api.qa.aukeyit.com/api/v1/data-metrics/cli-query/simple" \
  -d '{"tableId":1,"dimensions":[{"field":"date_id"}],"metrics":[{"field":"gmv","aggregation":"SUM"}],"filters":[{"field":"date_id","operator":">=","value":"2026-07-01"},{"field":"date_id","operator":"<=","value":"2026-07-14"}],"limit":5,"dryRun":true}'
```
Expected: dryRun 返回的 query.where.conditions 中出现默认条件（如 `date_type eq QUARTER`），验收标准 3 达成。若 dryRun 不回显 payload，改为查服务端日志确认。

- [ ] **Step 8: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Services/SimpleQueryBuilder.php tests/SimpleQueryBuilderDefaultFiltersTest.php
git commit -m "feat(filter-config): simple 查询入口强制合并数据集默认条件（AND合并+去重）"
```

---

### Task 6: 度量字段 having 语义（filter_agg != none）

**Files:**
- Modify: `src/Services/SimpleQueryBuilder.php`（build 内追加 having 通道）
- 可能 Modify: `src/Converters/QueryBuilder.php`（视探查结果）
- Test: `tests/SimpleQueryBuilderDefaultFiltersTest.php`（追加用例）

**Interfaces:**
- Consumes: Task 5 的 `loadDefaultFilterConfigs()` 返回值中 `_field_type=metric && _filter_agg != none` 的条目
- Produces: 查询 payload 的 having 表达（结构以探查结果为准）

- [ ] **Step 1: 探查查询引擎 having 能力**

```bash
grep -n -i "having" /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Converters/QueryBuilder.php | head -20
grep -rn -i "having" /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Services/ | head -10
```
Expected 两种结果：
- **分支 A（引擎已支持 having 节点）**：QueryBuilder 中存在 having 解析（类似 where 树处理）→ 继续 Step 2；
- **分支 B（无 having 支持）**：无任何命中 → **停止本任务**，向需求方报告"查询引擎不支持 having，度量默认条件需要引擎侧排期支持"，本任务改为在 `loadDefaultFilterConfigs` 处对 `filter_agg != none` 条目记录 warning 日志后跳过（保持 Task 5 已有的 skip 行为），并在需求文档评审结论 3 处补充备注。不得伪造 having 实现。

- [ ] **Step 2:（仅分支 A）按 QueryBuilder 实际 having 结构，在 build() 中追加 having 通道**

在 build() 的 where 处理之后（第 107 行附近）插入，节点结构对齐 Step 1 探查到的实际格式（下面以 where 树同构为例，若实际结构不同按探查结果调整字段名）：

```php
        // 度量默认条件（filter_agg != none）→ having 语义（评审结论 3）
        $havingConditions = [];
        foreach ($this->loadDefaultFilterConfigs($table) as $default) {
            if (($default['_field_type'] ?? '') !== 'metric' || ($default['_filter_agg'] ?? 'none') === 'none') {
                continue;
            }
            $havingConditions[] = [
                'field'       => "{$datasetAlias}.{$default['field']}",
                'aggregation' => strtoupper($default['_filter_agg'] === 'countDistinct' ? 'DISTINCT_COUNT' : $default['_filter_agg']),
                'operator'    => $default['operator'],
                'value'       => $default['value'],
            ];
        }
        if (!empty($havingConditions)) {
            $query['having'] = ['operator' => 'AND', 'conditions' => $havingConditions];
        }
```

- [ ] **Step 3: 追加测试并运行**

在 `SimpleQueryBuilderDefaultFiltersTest` 中把 `testMetricHavingDefaultSkipped` 的语义确认为"where 层跳过"（已有），另通过 QA dryRun 实测 having 节点透传与生效：

```bash
curl -s -X POST -H "Authorization: Bearer <QA_JWT>" -H "Content-Type: application/json" \
  "https://ops.api.qa.aukeyit.com/api/v1/data-metrics/cli-query/simple" \
  -d '{"tableId":<配置了度量默认条件的表ID>,"dimensions":[{"field":"date_id"}],"metrics":[{"field":"gmv","aggregation":"SUM"}],"limit":5}'
```
Expected: 返回行满足聚合后过滤（比对无 having 时的结果差异），验收标准 13 达成。

- [ ] **Step 4: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Services/SimpleQueryBuilder.php tests/SimpleQueryBuilderDefaultFiltersTest.php
git commit -m "feat(filter-config): 度量默认条件按 having 语义应用（filter_agg 聚合后过滤）"
```

---

### Task 7: CliQueryService 完整查询入口兜底（R2 兜底路径）

**Files:**
- Modify: `src/Services/SimpleQueryBuilder.php`（新增公开方法 appendDefaultConditions）
- Modify: `src/Services/CliQueryService.php:31-92`（executeForUser 接线）
- Test: `tests/SimpleQueryBuilderDefaultFiltersTest.php`（追加用例）

**Interfaces:**
- Consumes: Task 5 的 `loadDefaultFilterConfigs()` / `toSimpleFilters()` 产物；SimpleQueryBuilder 既有 `distributeInnerWhereFromSql()`、`calculateInnerWhereLevels()`
- Produces: `SimpleQueryBuilder::appendDefaultConditions(array $payload, Table $table): array` —— 对完整 payload 的 where 树追加缺失的默认条件（AND），供 CliQueryService 调用

- [ ] **Step 1: 编写失败测试**

在 `SimpleQueryBuilderDefaultFiltersTest` 中追加（通过反射注入 defaults 或 mock loadDefaultFilterConfigs；用匿名子类覆写最简单）：

```php
    /** 完整入口兜底：payload where 树缺失 required 默认条件时自动追加 AND 条件 */
    public function testAppendDefaultConditionsToPayload(): void
    {
        // 匿名子类覆写数据加载，签名（含 array 返回类型）必须与父类完全一致
        $builder = new class extends SimpleQueryBuilder {
            protected function loadDefaultFilterConfigs(\Aukey\DataMetrics\Models\Table $table): array
            {
                return [['field' => 'date_type', 'operator' => 'eq', 'value' => 'QUARTER',
                         '_type' => 'required', '_filter_agg' => 'none', '_field_type' => 'dimension']];
            }
        };
        $table = new \Aukey\DataMetrics\Models\Table();
        $table->dataset_alias = 'ds_a';
        $table->inner_where_enabled = false;

        $payload = ['tableId' => 1, 'query' => [
            'select' => [['field' => 'ds_a.date_id']],
            'where'  => ['operator' => 'AND', 'conditions' => [
                ['field' => 'ds_a.date_id', 'operator' => 'gte', 'value' => '2026-07-01'],
            ]],
        ]];
        $result = $builder->appendDefaultConditions($payload, $table);
        $conditions = $result['query']['where']['conditions'];
        $this->assertCount(2, $conditions);
        $this->assertSame('ds_a.date_type', $conditions[1]['field']);

        // 已含同值条件时去重不重复追加
        $again = $builder->appendDefaultConditions($result, $table);
        $this->assertCount(2, $again['query']['where']['conditions']);

        // 无 where 节点时自动创建
        $bare = $builder->appendDefaultConditions(['tableId' => 1, 'query' => ['select' => []]], $table);
        $this->assertCount(1, $bare['query']['where']['conditions']);
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/SimpleQueryBuilderDefaultFiltersTest.php --filter testAppendDefaultConditionsToPayload`
Expected: FAIL —— 方法不存在

- [ ] **Step 3: 实现 appendDefaultConditions**

```php
    /**
     * 完整查询入口兜底（需求 R2）：对已构建好的 payload where 树追加缺失的默认条件。
     *
     * cli-query 入口的 payload 由客户端直接构造 where 树，不经过 build()/mergeDefaultFilters，
     * 若不兜底则 required 默认条件可被绕过。合并语义与 mergeDefaultFilters 一致：
     * required 缺失即追加（AND）、同值/子集去重；optional 用户已有同字段条件则跳过。
     * innerWhere 数据集：默认条件经 distributeInnerWhereFromSql 分发，与既有管线一致。
     */
    public function appendDefaultConditions(array $payload, Table $table): array
    {
        $defaults = array_filter(
            $this->loadDefaultFilterConfigs($table),
            // having 语义度量条件不在 where 树兜底（Task 6 通道）
            fn ($d) => !(($d['_field_type'] ?? '') === 'metric' && ($d['_filter_agg'] ?? 'none') !== 'none')
        );
        if (empty($defaults)) {
            return $payload;
        }
        $datasetAlias = (string) ($table->dataset_alias ?? '');
        $query = $payload['query'] ?? [];

        // 收集 where/innerWhere 树中已有条件的裸字段名与值（递归扫描 conditions）
        $existing = [];
        $collect = function ($node) use (&$collect, &$existing) {
            foreach (($node['conditions'] ?? []) as $condition) {
                if (isset($condition['conditions'])) {
                    $collect($condition);
                    continue;
                }
                $bare = ltrim(strrchr('.' . (string) ($condition['field'] ?? ''), '.'), '.');
                $existing[$bare][] = $condition;
            }
        };
        foreach (['where', 'innerWhere'] as $key) {
            if (!empty($query[$key])) {
                $collect($query[$key]);
            }
        }

        // 逐条判定注入（语义与 mergeDefaultFilters 对齐）
        $toAppend = [];
        foreach ($defaults as $default) {
            $field = $default['field'];
            $userConditions = $existing[$field] ?? [];
            if (($default['_type'] ?? 'required') === 'optional' && !empty($userConditions)) {
                continue;
            }
            if (($default['_type'] ?? 'required') === 'required' && !empty($userConditions)) {
                $defaultValues = is_array($default['value']) ? $default['value'] : [$default['value']];
                $covered = false;
                foreach ($userConditions as $condition) {
                    $userValues = is_array($condition['value'] ?? null) ? $condition['value'] : [$condition['value'] ?? null];
                    if (!array_diff($userValues, $defaultValues)) {
                        $covered = true;
                        break;
                    }
                }
                if ($covered) {
                    continue;
                }
            }
            $toAppend[] = [
                'field'    => "{$datasetAlias}.{$field}",
                'operator' => $default['operator'],
                'value'    => $default['value'],
            ];
        }
        if (empty($toAppend)) {
            return $payload;
        }

        // 追加：innerWhere 数据集走既有分发逻辑，普通数据集直接并入 where.conditions
        $sqlText = (string) ($table->sql ?? '');
        $useInnerWhere = (bool) ($table->inner_where_enabled ?? false)
            && $this->calculateInnerWhereLevels($sqlText) > 0
            && !empty($query['innerWhere']);
        if ($useInnerWhere) {
            $distributed = $this->distributeInnerWhereFromSql(
                ['operator' => 'AND', 'conditions' => $toAppend],
                $this->calculateInnerWhereLevels($sqlText),
                $datasetAlias,
                $sqlText
            );
            // 与既有 innerWhere 各层合并（结构：数组每层一个 where 树）
            foreach ($distributed as $level => $tree) {
                foreach (($tree['conditions'] ?? []) as $condition) {
                    $query['innerWhere'][$level]['conditions'][] = $condition;
                }
            }
        } else {
            if (empty($query['where'])) {
                $query['where'] = ['operator' => 'AND', 'conditions' => []];
            }
            foreach ($toAppend as $condition) {
                $query['where']['conditions'][] = $condition;
            }
        }
        $payload['query'] = $query;
        return $payload;
    }
```

注意：`distributeInnerWhereFromSql` 的返回结构以实际代码为准（先 `grep -n -A 5 "function distributeInnerWhereFromSql"` 核对层级结构），合并循环按实际结构调整。

- [ ] **Step 4: executeForUser 接线**

修改 `src/Services/CliQueryService.php`，在第 76 行（受限字段检查）之前插入：

```php
        // 强制应用数据集默认条件（需求 R2 兜底）：完整入口的 payload 由客户端自行
        // 构造 where 树，不经过 SimpleQueryBuilder::build()，此处兜底防止绕过
        $payload = $this->simpleQueryBuilder->appendDefaultConditions($payload, $table);
```

确认 CliQueryService 已持有 `$this->simpleQueryBuilder`（executeSimpleForUser 第 138 行已在用；若为局部实例则改为构造注入属性）。

- [ ] **Step 5: 运行全量测试**

Run: `cd /Applications/MxSrvs/www/auto-scheduler && vendor/bin/phpunit vendor/aukey/data-metrics/tests/`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add src/Services/SimpleQueryBuilder.php src/Services/CliQueryService.php tests/SimpleQueryBuilderDefaultFiltersTest.php
git commit -m "feat(filter-config): cli-query 完整入口兜底注入默认条件，防止绕过 required"
```

---

### Task 8: QA 环境手动验收回归

**Files:** 无代码改动；产出验收记录追加到 `/Users/mask/python3/opscli/docs/plans/取数底座一期联调记录.md` 同级新文件或需求文档附录

**Interfaces:**
- Consumes: Task 1-7 全部产物
- Produces: 需求文档验收标准 1-4、8-9、12-14 的服务端侧验证记录

- [ ] **Step 1: 在后台管理为测试数据集配置 filter_config**

用后台管理（datasets.blade.php 页面，账号 `pengjianchao@aukeys.com` / `password`）为一个 QA 数据集的维度字段配置 `required + enum + equals + 单值`、另一字段配置 `optional`、一个度量字段配置 `filter_agg=sum`（若 Task 6 走分支 A）。

- [ ] **Step 2: 逐条执行验收命令**

```bash
# 验收 1/2：query-metadata 含 filter_configs；未配置数据集为空数组
curl -s -H "Authorization: Bearer <QA_JWT>" \
  "https://ops.api.qa.aukeyit.com/api/v1/data-metrics/datasets/query-metadata?dataset_alias=<已配置alias>" | python3 -m json.tool | grep -A 20 filter_configs

# 验收 3：simple 查询不带默认字段条件 → 结果已收敛（比对配置前后行数/内容）
# 验收 4：完整 cli-query 构造绕过 payload → where 树仍含默认条件（查日志或 dryRun）
# 验收 5：optional 字段用户显式传值 → 用户值生效
# 验收 8/9：两个 CSV 下载检查新列与配置一致
# 验收 11：未配置数据集查询结果与上线前一致（回归对比）
# 验收 12：冲突时静默 AND 合并、同值/子集去重
# 验收 13：度量 having 生效（Task 6 分支 A 时）
# 验收 14：多枚举值默认条件按 in 生效（配置双值枚举后 dryRun 检查 where 树）
```

- [ ] **Step 3: 记录验收结果**

每条验收标准记录：命令、输出摘要、通过/不通过。不通过项回到对应 Task 修复后重跑。

- [ ] **Step 4: 最终提交**

```bash
cd /Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics
git add -A && git status   # 确认无遗漏改动
git commit -m "test(filter-config): 补充验收回归记录" --allow-empty
```

---

## 依赖与排期说明

- Task 1、2 无依赖，可并行；Task 3 依赖 1；Task 4 依赖 3；Task 5 依赖 1+2；Task 6、7 依赖 5；Task 8 依赖全部。
- opscli/Skill 侧计划（另一份文档）的端到端验证依赖本计划 Task 3、4 上线到 QA；其余任务可用 fixture 先行并行开发。
