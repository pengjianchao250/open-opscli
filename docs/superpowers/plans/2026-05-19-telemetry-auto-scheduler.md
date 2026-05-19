# Telemetry 接收端实施计划（auto-scheduler）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 auto-scheduler 后端新增 `POST /api/v1/cli/telemetry` 公开端点，接收 opscli 上报的使用遥测数据并写入 MySQL。

**Architecture:** 标准 Laravel 四层结构：Migration → Model → Service → Controller，路由注册在现有公开路由组中。Controller 宽松校验（只过滤缺少必填字段的事件），Service 批量 insert，永远返回 200 避免客户端重试。

**Tech Stack:** Laravel PHP、Eloquent ORM、PHPUnit Feature Test、MySQL

**工作目录:** `/Applications/MxSrvs/www/auto-scheduler`

---

## 文件清单

| 操作 | 文件路径 |
|------|---------|
| 新建 | `database/migrations/2026_05_19_000000_create_opscli_telemetry_table.php` |
| 新建 | `app/Models/OpscliTelemetry.php` |
| 新建 | `app/Services/CliTelemetryService.php` |
| 新建 | `app/Http/Controllers/Api/CliTelemetryController.php` |
| 修改 | `routes/api.php`（在公开路由组追加一行） |
| 新建 | `tests/Feature/CliTelemetryTest.php` |

---

### Task 1: 数据库 Migration + Model

**Files:**
- Create: `database/migrations/2026_05_19_000000_create_opscli_telemetry_table.php`
- Create: `app/Models/OpscliTelemetry.php`

- [ ] **Step 1: 创建 Migration 文件**

```php
<?php
// database/migrations/2026_05_19_000000_create_opscli_telemetry_table.php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('opscli_telemetry', function (Blueprint $table) {
            $table->id();
            $table->string('event_type', 50);           // cli_command / mcp_tool
            $table->string('command', 200);              // query run / auth_login_start
            $table->string('module', 50);                // query / auth / amazon
            $table->string('status', 20);                // success / error
            $table->string('error_type', 100)->nullable();
            $table->unsignedInteger('duration_ms')->nullable();
            $table->string('user_email', 200)->nullable();
            $table->string('device_id', 64);
            $table->string('opscli_version', 20)->nullable();
            $table->string('os', 20)->nullable();        // darwin / linux
            $table->string('skill_name', 100)->nullable();
            $table->json('raw_payload')->nullable();     // 完整原始 payload 备查
            $table->timestamp('created_at')->useCurrent();

            $table->index('command', 'idx_command');
            $table->index('module', 'idx_module');
            $table->index('user_email', 'idx_user_email');
            $table->index('device_id', 'idx_device_id');
            $table->index('created_at', 'idx_created_at');
            $table->index(['module', 'status'], 'idx_module_status');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('opscli_telemetry');
    }
};
```

- [ ] **Step 2: 执行 Migration**

```bash
cd /Applications/MxSrvs/www/auto-scheduler
php artisan migrate
```

期望输出：`Migrating: 2026_05_19_000000_create_opscli_telemetry_table` 后 `Migrated`

- [ ] **Step 3: 创建 Model**

```php
<?php
// app/Models/OpscliTelemetry.php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * opscli 遥测事件记录模型
 *
 * 对应 opscli_telemetry 表，记录 CLI 命令和 MCP Tool 的使用情况。
 * 只有 created_at，无 updated_at（遥测数据不可变）。
 */
class OpscliTelemetry extends Model
{
    /** 只有 created_at，无 updated_at */
    public $timestamps = false;

    protected $table = 'opscli_telemetry';

    protected $fillable = [
        'event_type',
        'command',
        'module',
        'status',
        'error_type',
        'duration_ms',
        'user_email',
        'device_id',
        'opscli_version',
        'os',
        'skill_name',
        'raw_payload',
        'created_at',
    ];

    protected $casts = [
        'raw_payload' => 'array',
        'created_at'  => 'datetime',
    ];
}
```

- [ ] **Step 4: 写失败测试，验证表结构**

```php
<?php
// tests/Feature/CliTelemetryTest.php

namespace Tests\Feature;

use App\Models\OpscliTelemetry;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class CliTelemetryTest extends TestCase
{
    use RefreshDatabase;

    public function test_model_can_be_created(): void
    {
        OpscliTelemetry::create([
            'event_type'     => 'cli_command',
            'command'        => 'query run',
            'module'         => 'query',
            'status'         => 'success',
            'device_id'      => 'test-device-uuid',
            'created_at'     => now(),
        ]);

        $this->assertDatabaseHas('opscli_telemetry', [
            'command'   => 'query run',
            'device_id' => 'test-device-uuid',
        ]);
    }
}
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
cd /Applications/MxSrvs/www/auto-scheduler
php artisan test --filter=CliTelemetryTest::test_model_can_be_created
```

期望：`PASS`

- [ ] **Step 6: Commit**

```bash
git add database/migrations/2026_05_19_000000_create_opscli_telemetry_table.php \
        app/Models/OpscliTelemetry.php \
        tests/Feature/CliTelemetryTest.php
git commit -m "feat: add opscli_telemetry table migration and model"
```

---

### Task 2: CliTelemetryService

**Files:**
- Create: `app/Services/CliTelemetryService.php`

- [ ] **Step 1: 为 batchInsert 写失败测试**

在 `tests/Feature/CliTelemetryTest.php` 末尾追加（不删除已有方法）：

```php
public function test_service_batch_insert_writes_rows(): void
{
    $service = new \App\Services\CliTelemetryService();

    $service->batchInsert([
        [
            'event_type'     => 'cli_command',
            'command'        => 'auth login',
            'module'         => 'auth',
            'status'         => 'success',
            'duration_ms'    => 800,
            'user_email'     => 'test@aukeys.com',
            'device_id'      => 'device-abc',
            'opscli_version' => '0.0.74',
            'os'             => 'darwin',
        ],
    ]);

    $this->assertDatabaseHas('opscli_telemetry', [
        'command'    => 'auth login',
        'status'     => 'success',
        'device_id'  => 'device-abc',
        'user_email' => 'test@aukeys.com',
    ]);
}

public function test_service_batch_insert_empty_array_does_nothing(): void
{
    $service = new \App\Services\CliTelemetryService();
    $inserted = $service->batchInsert([]);

    $this->assertEquals(0, $inserted);
    $this->assertDatabaseCount('opscli_telemetry', 0);
}
```

- [ ] **Step 2: 运行测试，确认失败（Service 不存在）**

```bash
php artisan test --filter=CliTelemetryTest::test_service_batch_insert
```

期望：FAIL — `Class "App\Services\CliTelemetryService" not found`

- [ ] **Step 3: 实现 CliTelemetryService**

```php
<?php
// app/Services/CliTelemetryService.php

namespace App\Services;

use App\Models\OpscliTelemetry;

/**
 * opscli 遥测数据写入服务
 *
 * 负责将上报的事件数组批量写入数据库。
 * 字段缺失时存 NULL，不拒绝请求（宽松策略）。
 */
class CliTelemetryService
{
    /**
     * 批量写入遥测事件
     *
     * @param  array  $events  已通过基础校验的事件数组（每项保证有 device_id 和 command）
     * @return int    实际写入的行数
     */
    public function batchInsert(array $events): int
    {
        if (empty($events)) {
            return 0;
        }

        $rows = array_map(fn ($e) => [
            'event_type'     => $e['event_type'] ?? 'cli_command',
            'command'        => $e['command'],
            'module'         => $e['module'] ?? '',
            'status'         => $e['status'] ?? 'unknown',
            'error_type'     => $e['error_type'] ?? null,
            'duration_ms'    => isset($e['duration_ms']) ? (int) $e['duration_ms'] : null,
            'user_email'     => $e['user_email'] ?? null,
            'device_id'      => $e['device_id'],
            'opscli_version' => $e['opscli_version'] ?? null,
            'os'             => $e['os'] ?? null,
            'skill_name'     => $e['skill_name'] ?? null,
            'raw_payload'    => json_encode($e),
            'created_at'     => now(),
        ], $events);

        OpscliTelemetry::insert($rows);

        return count($rows);
    }
}
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
php artisan test --filter=CliTelemetryTest
```

期望：3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/Services/CliTelemetryService.php tests/Feature/CliTelemetryTest.php
git commit -m "feat: add CliTelemetryService with batch insert"
```

---

### Task 3: CliTelemetryController

**Files:**
- Create: `app/Http/Controllers/Api/CliTelemetryController.php`

- [ ] **Step 1: 写 Controller 的失败测试**

在 `tests/Feature/CliTelemetryTest.php` 末尾追加：

```php
public function test_store_accepts_valid_events_and_returns_200(): void
{
    $response = $this->postJson('/api/v1/cli/telemetry', [
        'events' => [
            [
                'event_type'     => 'cli_command',
                'command'        => 'query run',
                'module'         => 'query',
                'status'         => 'success',
                'duration_ms'    => 1250,
                'user_email'     => 'zhang@aukeys.com',
                'device_id'      => '550e8400-e29b-41d4-a716-446655440000',
                'opscli_version' => '0.0.74',
                'os'             => 'darwin',
            ],
        ],
    ]);

    $response->assertStatus(200)
        ->assertJson(['accepted' => 1]);

    $this->assertDatabaseHas('opscli_telemetry', [
        'command'    => 'query run',
        'status'     => 'success',
        'user_email' => 'zhang@aukeys.com',
    ]);
}

public function test_store_filters_events_missing_device_id(): void
{
    $response = $this->postJson('/api/v1/cli/telemetry', [
        'events' => [
            ['command' => 'query run', 'status' => 'success'],  // 缺 device_id
        ],
    ]);

    $response->assertStatus(200)
        ->assertJson(['accepted' => 0]);

    $this->assertDatabaseCount('opscli_telemetry', 0);
}

public function test_store_returns_200_on_empty_events(): void
{
    $response = $this->postJson('/api/v1/cli/telemetry', ['events' => []]);

    $response->assertStatus(200)
        ->assertJson(['accepted' => 0]);
}

public function test_store_returns_200_on_invalid_body(): void
{
    // 非法请求体不应报错，保证高可用
    $response = $this->postJson('/api/v1/cli/telemetry', []);

    $response->assertStatus(200)
        ->assertJson(['accepted' => 0]);
}
```

- [ ] **Step 2: 运行测试，确认失败（路由不存在）**

```bash
php artisan test --filter="test_store_accepts_valid_events"
```

期望：FAIL — 404

- [ ] **Step 3: 实现 Controller**

```php
<?php
// app/Http/Controllers/Api/CliTelemetryController.php

namespace App\Http\Controllers\Api;

use App\Services\CliTelemetryService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/**
 * opscli 遥测数据接收 Controller
 *
 * 接收 opscli 客户端上报的命令执行遥测事件，写入数据库。
 * 使用宽松策略：字段缺失存 NULL，只过滤缺少必填字段（device_id/command）的事件。
 * 永远返回 200，避免客户端重试。
 */
class CliTelemetryController
{
    public function __construct(private CliTelemetryService $telemetryService)
    {
    }

    /**
     * 接收并写入遥测事件
     *
     * @param  Request  $request  包含 events 数组的 JSON 请求
     * @return JsonResponse  { "accepted": N }
     */
    public function store(Request $request): JsonResponse
    {
        $events = $request->input('events', []);

        // 非数组请求体静默丢弃，避免异常
        if (! is_array($events)) {
            return response()->json(['accepted' => 0]);
        }

        // 宽松校验：只过滤缺少必填字段的事件，不拒绝整批请求
        $valid = array_filter(
            $events,
            fn ($e) => is_array($e)
                && ! empty($e['device_id'])
                && ! empty($e['command'])
        );

        $accepted = $this->telemetryService->batchInsert(array_values($valid));

        return response()->json(['accepted' => $accepted]);
    }
}
```

- [ ] **Step 4: 注册路由**

打开 `routes/api.php`，在公开路由组（`Route::prefix('v1')->group`，约第 33 行）的 `cli` prefix 块之后添加：

```php
// opscli 遥测上报（无需认证，客户端可能未登录）
Route::post('cli/telemetry', [\App\Http\Controllers\Api\CliTelemetryController::class, 'store'])
    ->middleware('throttle:120,1');
```

位置参考（插在第 113 行 `});` 前后，`cli` 路由组之后）：

```php
    // CLI Device Flow - 公开接口
    Route::prefix('cli')->group(function () {
        Route::post('device/code', [CliDeviceController::class, 'requestCode']);
        Route::get('device/poll', [CliDeviceController::class, 'poll']);
        Route::post('device/confirm', [CliDeviceController::class, 'confirm']);
        Route::post('device/deny', [CliDeviceController::class, 'deny']);
    });

    // ↓ 追加此行 ↓
    // opscli 遥测上报（无需认证，客户端可能未登录）
    Route::post('cli/telemetry', [\App\Http\Controllers\Api\CliTelemetryController::class, 'store'])
        ->middleware('throttle:120,1');
```

- [ ] **Step 5: 运行全部测试，确认通过**

```bash
php artisan test --filter=CliTelemetryTest
```

期望：7 tests PASS

- [ ] **Step 6: 验证路由已注册**

```bash
php artisan route:list | grep telemetry
```

期望输出：`POST  api/v1/cli/telemetry`

- [ ] **Step 7: Commit**

```bash
git add app/Http/Controllers/Api/CliTelemetryController.php \
        app/Services/CliTelemetryService.php \
        routes/api.php \
        tests/Feature/CliTelemetryTest.php
git commit -m "feat: add CLI telemetry endpoint POST /api/v1/cli/telemetry"
```
