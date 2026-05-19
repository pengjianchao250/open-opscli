# opscli 遥测监控模块设计文档

**日期**：2026-05-19
**状态**：已确认，待实现
**范围**：opscli CLI 工具 + auto-scheduler 后端

---

## 一、背景与目标

opscli 作为 Aukeys 内网运营 CLI 工具，目前缺乏对使用情况的可观测性。无法回答以下问题：

- 哪些命令被高频使用？哪些功能没人用？
- 用户遇到了哪些错误？错误率多高？
- 哪些命令耗时过长，影响用户体验？
- 不同用户、不同机器的使用分布如何？

本模块目标：以**零侵入、不阻塞**的方式，自动采集 opscli 的命令执行遥测数据，上报到 auto-scheduler 后端，存入 MySQL，供后续统计分析。

---

## 二、核心决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 用户采集同意 | 静默上报（默认开启） | 内网工具，公司内部使用，无需额外授权 |
| 传输时机 | 异步 fire-and-forget | 不阻塞用户，网络失败静默丢弃 |
| 后端存储 | MySQL，先简单存 | 够用再扩展，不过度设计 |
| 用户身份 | JWT email + 机器 device_id | 双维度，既能按人查又能按机器查 |
| 拦截方式 | 中间件层自动拦截 | 零侵入业务代码，自动覆盖所有模块 |

---

## 三、整体架构与数据流

```
┌──────────────────────────────────────────────────────────┐
│                    opscli (用户本地)                      │
│                                                          │
│  CLI 命令                MCP Tool                        │
│  ┌──────────┐            ┌──────────┐                   │
│  │Typer     │            │FastMCP   │                   │
│  │callback  │            │middleware│                   │
│  └────┬─────┘            └────┬─────┘                   │
│       │  自动拦截              │  自动拦截                │
│       └──────────┬────────────┘                         │
│                  ▼                                       │
│         ┌─────────────────┐                             │
│         │ TelemetryEvent  │  构建事件（命令/耗时/状态）  │
│         │  + device_id    │  本地文件持久化              │
│         │  + user_email   │  JWT 静默读取，无则匿名      │
│         └────────┬────────┘                             │
│                  │  异步后台线程（fire-and-forget）       │
│                  ▼                                       │
│         ┌─────────────────┐                             │
│         │TelemetryReporter│  HTTP POST，失败静默丢弃    │
│         └────────┬────────┘                             │
└──────────────────┼───────────────────────────────────────┘
                   │  POST /v1/cli/telemetry（公开端点）
                   ▼
┌──────────────────────────────────────────────────────────┐
│                 auto-scheduler (后端)                     │
│                                                          │
│  CliTelemetryController → CliTelemetryService            │
│                                │                         │
│                                ▼                         │
│                    MySQL: opscli_telemetry 表            │
└──────────────────────────────────────────────────────────┘
```

---

## 四、opscli 侧实现

### 4.1 模块结构

新增 `opscli/telemetry/` 模块，纯内部基础设施，**不注册为 CLI 子命令**：

```
opscli/telemetry/
├── __init__.py       # 对外导出 track_cli / track_mcp 便捷函数
├── collector.py      # TelemetryCollector — 构建事件 dict，管理 error 状态
├── reporter.py       # TelemetryReporter — 后台线程池上报
└── device_id.py      # 管理 ~/.config/opscli/device_id 文件（UUID，首次生成）
```

### 4.2 事件字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `event_type` | string | 事件类型 | `cli_command` / `mcp_tool` |
| `command` | string | 命令路径（不含参数值） | `query run` / `auth_login_start` |
| `module` | string | 所属模块 | `query` / `auth` |
| `status` | string | 执行结果 | `success` / `error` |
| `error_type` | string? | 异常类名 | `NetworkError` |
| `duration_ms` | int? | 耗时毫秒 | `1250` |
| `user_email` | string? | JWT 用户邮箱，静默读取 | `zhang@aukeys.com` |
| `device_id` | string | 机器唯一 ID | UUID v4 |
| `opscli_version` | string | 版本号 | `0.0.74` |
| `os` | string | 操作系统 | `darwin` / `linux` |
| `skill_name` | string? | Skill 名（MCP 环境变量传入） | `ops-dataset-query` |
| `timestamp` | string | ISO 8601 UTC | `2026-05-19T10:00:00Z` |

**采集原则**：只采集命令路径（`sys.argv[1:3]`），**不采集任何参数值**，避免泄露业务数据。

### 4.3 CLI 拦截

在 `opscli/cli.py` 的 `main()` callback 中注入：

```python
@app.callback()
def main(ctx: typer.Context, ...):
    check_and_notify()
    start_ms = time.monotonic()

    def _report():
        TelemetryReporter.fire(
            event_type="cli_command",
            command=" ".join(sys.argv[1:3]),     # 如 "query run"
            module=sys.argv[1] if len(sys.argv) > 1 else "",
            duration_ms=int((time.monotonic() - start_ms) * 1000),
            status=TelemetryCollector.pop_status(),   # 正常 success，异常 error
            error_type=TelemetryCollector.pop_error_type(),
        )

    ctx.call_on_close(_report)
```

异常捕获：在 `cli.py` 的 `app()` 调用外包 try/except，异常时调用 `TelemetryCollector.set_error(exc)`，`_report()` 读取后上报 `status=error`。

### 4.4 MCP 拦截

在 `opscli/mcp/server.py` 中，对所有 tool 函数包装装饰器：

```python
def _telemetry_wrap(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        start = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            TelemetryReporter.fire(
                event_type="mcp_tool",
                command=fn.__name__,
                module=fn.__name__.split("_")[0],
                duration_ms=int((time.monotonic() - start) * 1000),
                status="success",
            )
            return result
        except Exception as exc:
            TelemetryReporter.fire(
                event_type="mcp_tool",
                command=fn.__name__,
                module=fn.__name__.split("_")[0],
                duration_ms=int((time.monotonic() - start) * 1000),
                status="error",
                error_type=type(exc).__name__,
            )
            raise
    return wrapper
```

### 4.5 后台上报

```python
# reporter.py
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opscli-telemetry")

class TelemetryReporter:
    @staticmethod
    def fire(**kwargs):
        _executor.submit(_do_send, kwargs)  # 立即返回

def _do_send(payload: dict) -> None:
    try:
        httpx.post(TELEMETRY_URL, json={"events": [payload]}, timeout=5)
    except Exception:
        pass  # 静默丢弃，绝不影响主流程
```

`max_workers=1`：单后台线程，避免连接浪费。

### 4.6 device_id 管理

- 路径：`~/.config/opscli/device_id`
- 首次运行时生成 UUID v4 并写入文件
- 后续读取缓存，不重复生成

---

## 五、auto-scheduler 侧实现

### 5.1 数据库表

```sql
CREATE TABLE opscli_telemetry (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_type     VARCHAR(50)  NOT NULL,
    command        VARCHAR(200) NOT NULL,
    module         VARCHAR(50)  NOT NULL,
    status         VARCHAR(20)  NOT NULL,          -- success / error
    error_type     VARCHAR(100) DEFAULT NULL,
    duration_ms    INT UNSIGNED DEFAULT NULL,
    user_email     VARCHAR(200) DEFAULT NULL,
    device_id      VARCHAR(64)  NOT NULL,
    opscli_version VARCHAR(20)  DEFAULT NULL,
    os             VARCHAR(20)  DEFAULT NULL,
    skill_name     VARCHAR(100) DEFAULT NULL,
    raw_payload    JSON         DEFAULT NULL,       -- 完整原始 payload 备查
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_command     (command),
    INDEX idx_module      (module),
    INDEX idx_user_email  (user_email),
    INDEX idx_device_id   (device_id),
    INDEX idx_created_at  (created_at),
    INDEX idx_module_status (module, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 5.2 API 接口

**`POST /v1/cli/telemetry`**

- 认证：**无需 JWT**（公开端点，用户可能未登录）
- 限流：`throttle:120,1`（每分钟 120 条/IP，超出 429，客户端静默丢弃）
- 请求：

```json
{
  "events": [
    {
      "event_type": "cli_command",
      "command": "query run",
      "module": "query",
      "status": "success",
      "duration_ms": 1250,
      "user_email": "zhang@aukeys.com",
      "device_id": "550e8400-e29b-41d4-a716-446655440000",
      "opscli_version": "0.0.74",
      "os": "darwin",
      "timestamp": "2026-05-19T10:00:00Z"
    }
  ]
}
```

- 响应：`{ "accepted": 1 }`（永远 200，不让客户端重试）

### 5.3 后端代码结构

```
app/
├── Http/Controllers/Api/
│   └── CliTelemetryController.php   # 接收、基础校验、调用 Service
├── Services/
│   └── CliTelemetryService.php      # 批量 insert 逻辑
├── Models/
│   └── OpscliTelemetry.php          # Eloquent 模型
└── database/migrations/
    └── xxxx_create_opscli_telemetry_table.php
```

**Controller 核心逻辑**：

```php
public function store(Request $request): JsonResponse
{
    $events = $request->input('events', []);
    // 宽松校验：只过滤缺少必填字段的，不拒绝整批请求
    $valid = array_filter($events, fn($e) =>
        !empty($e['device_id']) && !empty($e['command'])
    );
    $this->telemetryService->batchInsert(array_values($valid));
    return response()->json(['accepted' => count($valid)]);
}
```

**Service 核心逻辑**：

```php
public function batchInsert(array $events): void
{
    if (empty($events)) return;

    $rows = array_map(fn($e) => [
        'event_type'     => $e['event_type'] ?? 'cli_command',
        'command'        => $e['command'],
        'module'         => $e['module'] ?? '',
        'status'         => $e['status'] ?? 'unknown',
        'error_type'     => $e['error_type'] ?? null,
        'duration_ms'    => $e['duration_ms'] ?? null,
        'user_email'     => $e['user_email'] ?? null,
        'device_id'      => $e['device_id'],
        'opscli_version' => $e['opscli_version'] ?? null,
        'os'             => $e['os'] ?? null,
        'skill_name'     => $e['skill_name'] ?? null,
        'raw_payload'    => json_encode($e),
        'created_at'     => now(),
    ], $events);

    OpscliTelemetry::insert($rows);
}
```

---

## 六、边界与约束

| 约束 | 说明 |
|------|------|
| 不采集参数值 | `sys.argv[1:3]` 只取命令路径，ASIN、数据集名等业务参数不上报 |
| 网络失败静默丢弃 | 上报失败不重试、不缓存、不影响主流程 |
| 未登录用户 | `user_email` 为 NULL，仅凭 `device_id` 追踪 |
| MCP 长进程 | 每次 tool 调用独立上报，不依赖进程退出 |
| 后端宽松校验 | 字段缺失存 NULL，不拒绝请求，保证高可用 |

---

## 七、未来扩展（超出本期范围）

- 数据看板：按模块/用户/时间段的使用热图
- 告警：错误率超阈值发企业微信通知
- 批量上报：本地队列 + 定时批量，减少 HTTP 次数
- Skill 调用溯源：从环境变量传入 skill_name，关联 Skill 使用率
