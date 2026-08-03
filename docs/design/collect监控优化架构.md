# collect 监控优化架构

> 状态：方案草案
> 原则：独立监控、业务 fail-closed、诊断可用、默认脱敏

## 1. 目标架构

```text
业务调用
  -> Collector MCP transport
     -> Bundle readiness gate
        -> SellerSprite scheduler
           -> QueueStore (write path)

独立 Collector Monitor
  -> Queue repository (SQLite mode=ro)
  -> Collector health probe (collector_modules_health)
  -> Monitor state store
  -> Incident engine
  -> WeCom notifier
  -> Starlette API/UI

ops-feedback-query companion
  -> feedback open-query API
  -> sanitized feedback snapshot file
  -> Collector Monitor read-only provider
```

## 2. 核心架构决策

### ADR-1 队列路径单一解析

新增共享的 `SellerSpriteStorageSettings` 或等价深模块，负责：

- 显式 `queue_db_path`；
- 默认仍兼容 `CONFIG_DIR/seller_sprite/task_queue.sqlite3`；
- 绝对路径规范化；
- Collector 和 Monitor 配置一致性检查；
- 对外只提供路径指纹，不在远端响应暴露绝对路径。

建议环境变量：

```text
OPSCLI_SELLER_SPRITE_QUEUE_DB_PATH
```

Monitor 的 `OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH` 可保留兼容，但未显式配置时应解析为 SellerSprite 的同一设置；两者同时配置且不一致时启动失败。

### ADR-2 基础服务与 Bundle readiness 分离

当前 Bundle lifespan 失败会中止整个 Collector。调整为：

- Collector transport 与公共健康工具先启动。
- 每个 Bundle 维护 `starting/ready/degraded/failed/recovering` 状态。
- SellerSprite 初始化失败时保存稳定错误码和安全错误类，不保存路径或原始异常。
- SellerSprite 业务工具统一经过 readiness gate；非 ready 返回结构化 `COLLECTOR_MODULE_NOT_READY`。
- 后台按有界指数退避重新初始化，或由受控运维动作触发；同一时间只允许一个初始化尝试。

这不是让业务 fail-open。服务诊断面可用，业务写面继续 fail-closed。

### ADR-3 Monitor 继续保持业务库只读

Monitor 不获得业务库写权限。写能力由 Collector 自己在同服务账号上下文自检并通过健康合同上报：

```json
{
  "checks": {
    "queue_read": "ok",
    "queue_write": "error",
    "schema": "ok",
    "scheduler": "not_started"
  },
  "error_code": "QUEUE_DATABASE_UNAVAILABLE"
}
```

Monitor 的直接 SQLite 检查只证明外部观察者可以只读访问；Collector 自报检查证明真实写端可接单。两者必须同时展示，不能互相替代。

### ADR-4 feedback 使用脱敏快照适配器

根据项目铁律，只有内部 `ops-feedback-query` Skill 可直连 open-query API。Monitor 不新增远端 feedback 客户端。

companion 输出建议：

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-03T09:10:00+08:00",
  "window_seconds": 3600,
  "groups": [
    {
      "fingerprint": "collector:seller_sprite:queue:QUEUE_DATABASE_UNAVAILABLE",
      "tool": "seller_sprite_run",
      "error_code": "QUEUE_DATABASE_UNAVAILABLE",
      "count": 8,
      "failed_call_count": 8,
      "max_severity": "critical",
      "first_seen_at": "...",
      "last_seen_at": "..."
    }
  ]
}
```

禁止字段：邮箱、用户 ID、content、payload、context、附件、call_params、error_message 原文、凭据。

## 3. 健康模型

### 3.1 分层状态

| 层 | 检查 | 来源 |
|---|---|---|
| Monitor | live、state_store、poll_loop | Monitor 自身 |
| Queue source | file、schema、read transaction | Monitor 只读仓储 |
| Collector | transport reachability、latency | 外部主动探测 |
| Bundle | queue_read、queue_write、scheduler | Collector 自报 |
| Runtime | heartbeat、capacity、last_claim/progress | 队列运行时表 |
| Task | lifecycle、progress age、lease | 队列任务表 |
| User signal | feedback fingerprint count | 脱敏快照 |

### 3.2 稳定错误码

- `QUEUE_DATABASE_UNAVAILABLE`
- `QUEUE_SCHEMA_INVALID`
- `QUEUE_WRITE_UNAVAILABLE`
- `COLLECTOR_UNREACHABLE`
- `COLLECTOR_MODULE_NOT_READY`
- `SCHEDULER_HEARTBEAT_STALE`
- `MONITOR_STATE_UNAVAILABLE`
- `FEEDBACK_SNAPSHOT_STALE`

原始 `OperationalError` 只进入本机受控日志；API、UI、通知使用稳定码和白名单说明。

## 4. Incident 模型

将 `IncidentCandidate` 从仅任务规则扩展到 `scope`：

```text
scope = service | module | queue | task | signal
fingerprint = scope + rule + subject
```

新增字段建议：

- `fingerprint`
- `scope`
- `first_seen_at/last_seen_at`
- `failure_observations/recovery_observations`
- `affected_task_count`
- `suppressed_incident_count`
- `related_feedback_count`
- `silenced_until/silence_reason`

抑制规则示例：

```text
queue_database_unavailable
  inhibits collector_not_ready for seller_sprite
  inhibits worker_unavailable for seller_sprite queues
  inhibits derived stalled notifications
```

被抑制事故仍保存在状态库并可查询，只是不单独通知。

## 5. 主动探测 API

### 5.1 API 合同

```text
POST /api/v1/probes/collector
POST /api/v1/probes/queue-source
```

请求不接收 URL、路径、自定义 Header 或任意命令，目标来自冻结配置，避免 SSRF 与命令注入。Collector 端点可选接收最长 512 字符的 `api_key` JSON 字段，仅用于该次服务端请求的 `X-MCP-API-Key`；队列源端点拒绝此字段。

响应：

```json
{
  "target": "collector",
  "probed_at": "...",
  "status": "ready",
  "error_code": null,
  "error_class": null
}
```

### 5.2 安全约束

- 默认仅 loopback；经反向代理暴露时必须有运维认证。
- 同源请求、严格 Content-Type、拒绝跨域。
- 临时 Key 只驻留于当前请求与探测协程，优先于文件 Key；不进入响应、缓存、状态库或日志字段，前端发起请求后立即清空输入。
- 每目标单并发，10 秒冷却，5 秒总超时。
- Collector 结果只更新 Monitor 内存缓存；队列源结果不覆盖任务快照，也不修改业务队列。
- 首期为同步探测，不持久化探测历史、响应正文或凭据。

## 6. API 扩展

保留现有 GET 合同，新增：

```text
GET  /api/v1/status
GET  /api/v1/services
GET  /api/v1/queues
GET  /api/v1/tasks
GET  /api/v1/incidents
GET  /api/v1/incidents/{fingerprint}
GET  /api/v1/feedback-signals
POST /api/v1/probes/{target}
```

P1 静默接口属于运维写面，应单独鉴权：

```text
POST   /api/v1/silences
DELETE /api/v1/silences/{id}
```

不增加 task retry/requeue API。

## 7. 数据存储

Monitor 私有库 schema 增量：

- `incidents`：增加 fingerprint/scope/抑制/反馈摘要字段。
- 首期不新增 `probe_runs`；如 P1 需要趋势，再单独评审有界探测元数据。
- `metric_rollups`：15 分钟或 24 小时有界聚合点。
- `silences`：P1 运维静默。

保留策略：

- probe runs：最近 100 次或 7 天。
- minute rollups：7 天；hour rollups：30 天。
- 已恢复 incidents：90 天后归档/清理。
- feedback snapshot 不复制入库，只缓存聚合字段。

## 8. 生产部署

### 8.1 服务拓扑

- Collector：单实例、单 worker、业务队列写权限。
- Monitor：独立服务账号、业务队列只读、私有状态库读写。
- feedback companion：内部账号、feedback 凭据只读、仅写脱敏快照目录。

### 8.2 上线门禁

部署检查脚本必须在失败时非零退出：

1. Collector 解析出的队列路径等于预期绝对路径。
2. Collector 账号可完成 schema/WAL 安全预检。
3. Monitor 账号可 `mode=ro` 打开同一物理文件。
4. Monitor 状态目录可写且不是业务库别名。
5. Collector health 可达且错误响应不泄露路径。
6. Monitor ready、probe、事故开关和通知 dry-run 通过。

## 9. 测试策略

### 单元

- 路径解析与冲突配置。
- 错误码映射与脱敏。
- 连续失败/恢复、抑制、静默、反馈关联。
- probe 并发、冷却和超时。

### 集成

- 数据库目标为目录，复现 unable-to-open。
- 父目录不可写、数据库只读、WAL sidecar 不可写。
- Collector Bundle 初始化失败但健康面仍可用。
- Monitor 发现 Collector 下线与恢复。
- feedback snapshot 正常、过期、损坏和缺失。

### 端到端

- 生产同构 systemd 用户/HOME/挂载测试。
- 修复权限后手工 probe 转绿并发送一次 recovery。
- 数据库根因活动时派生告警被抑制。
- UI 不出现 retry/requeue 业务按钮，敏感词扫描通过。

## 10. 迁移顺序

1. 修复共享路径合同和部署文档。
2. 增加 Collector 启动/ready 分层及稳定错误码。
3. 扩展 Monitor 服务级 incident。
4. 上线 Monitor 无通知观察模式。
5. 增加立即探测 UI/CLI。
6. 启用通知与根因抑制。
7. 接入 feedback 脱敏快照。
