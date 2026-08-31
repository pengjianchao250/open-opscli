# collect 监控优化调研

> 日期：2026-08-03
> 范围：Collector MCP、SellerSprite 持久队列、Collector Monitor、ops-feedback-query

## 1. 结论摘要

今天的报错可以在本地稳定复现：`SellerSpriteTaskQueueStore` 打开不可用目标时抛出 `sqlite3.OperationalError: unable to open database file`。异常发生在队列仓储初始化或入队事务之前，因此没有任务行、没有 `job_id` 对应状态，也不会进入现有任务级监控。

现有 `collector_monitor` 已经具备较完整的任务队列监督能力，但生产环境尚未运行，而且当前有四个关键盲区：

1. Collector 启动失败会让整个 Collector MCP lifespan 失败，健康工具也随服务一起不可达。
2. 队列数据库不可读只进入 `source.ready=false`，不会形成事故或企业微信告警。
3. Collector MCP 探测失败只进入缓存摘要，不会形成事故或告警。
4. UI 与 API 是纯只读状态页，没有“立即探测”动作，也没有 feedback 相关信号。

建议先做 P0 可用性闭环：统一队列路径合同、Collector 启动预检、独立 Monitor 生产部署、数据源与 Collector 不可用事故、只读“立即探测”。任务重试不应与服务探测混为一谈；首期不增加监控台任务重排按钮。

## 2. 故障复现与证据

### 2.1 可运行反馈环

以下命令直接驱动真实队列仓储构造路径，并能稳定捕获用户描述的错误：

```powershell
@'
import sqlite3
import tempfile
from pathlib import Path
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

with tempfile.TemporaryDirectory() as raw:
    db_path = Path(raw) / "task_queue.sqlite3"
    db_path.mkdir()
    try:
        SellerSpriteTaskQueueStore(db_path=db_path)
    except sqlite3.OperationalError as exc:
        assert "unable to open database file" in str(exc).lower()
        print(f"RED: {type(exc).__name__}: {exc}")
    else:
        raise AssertionError("expected unable-to-open failure")
'@ | .\.venv\Scripts\python.exe -
```

实测输出：

```text
RED: OperationalError: unable to open database file
```

现有监控与运行时健康回归：

```text
74 passed in 6.31s
```

这说明已有分类逻辑没有回归，但现有测试没有覆盖“业务服务无法初始化队列、任务尚未入队”的端到端告警闭环。

### 2.2 代码路径

- `opscli/config.py:22` 将 `CONFIG_DIR` 固定为 `Path.home()/.config/opscli`。
- `opscli/seller_sprite/services/task_queue_store.py:16` 将业务队列固定为 `CONFIG_DIR/seller_sprite/task_queue.sqlite3`。
- `SellerSpriteTaskQueueStore.__init__()` 会先建父目录，再立即执行 schema 初始化。
- `_connect()` 使用普通可写 SQLite 连接，并执行 `PRAGMA journal_mode = WAL`；目录、文件或 WAL sidecar 无法写入时会失败。
- `get_task_scheduler()` 为计算缓存键会先构造一次 Store，随后创建 Scheduler 时还会再构造一次 Store。
- `seller_sprite.mcp_bundle.lifespan()` 捕获异常后记录模块失败，但随后重新抛出。
- `collector_mcp.server._collector_lifespan()` 进入 Bundle lifespan 时没有隔离失败，所以关键 Bundle 初始化失败会阻止整个 Collector MCP 对外服务。

### 2.3 路径合同不一致

Collector 部署方案明确依赖：

```text
HOME=/var/lib/opscli
实际队列=/var/lib/opscli/.config/opscli/seller_sprite/task_queue.sqlite3
```

但《Collector Monitor运维说明》的 systemd 示例使用：

```text
/var/lib/opscli/seller_sprite/task_queue.sqlite3
```

示例少了 `.config/opscli`。如果照文档上线 Monitor，会得到数据源不可用或监控错误文件。今天生产故障也应优先检查 Collector 服务账号、`HOME`、父目录执行权限、目录/文件所有者以及 `.sqlite3-wal/.sqlite3-shm` 创建能力。

目前 SellerSprite 没有 `OPSCLI_SELLER_SPRITE_QUEUE_DB_PATH`；路径稳定性完全依赖服务用户的 Home。这是部署脆弱点。

## 3. 现有监控能力盘点

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 队列任务监控 | 已有 | 读取 queued/running 及有限终态历史 |
| 任务健康分类 | 已有 | `healthy/slow/stalled/orphaned/queue_starved/worker_unavailable` |
| 调度器心跳 | 已有 | 生命周期、worker 存活、可用容量、最近领取/进度 |
| 任务时间线 | 已有 | 基于持久进度事件，不读取请求参数 |
| 事故生命周期 | 已有 | opening、escalation、reminder、recovery、冷却与持久化 |
| 企业微信通知 | 已有 | 受保护文件读取、脱敏、失败重投 |
| Collector MCP 探测 | 已有 | 调用 `collector_modules_health`，至少 60 秒一次 |
| Monitor live/ready | 已有 | `/health/live` 与 `/health/ready` |
| 数据源不可用告警 | 缺失 | 仅 `source.ready=false`，不形成 incident |
| Collector 不可用告警 | 缺失 | 仅缓存 `unavailable`，不形成 incident |
| 启动前队列写能力检查 | 缺失 | 失败发生时 Collector 可能整体起不来 |
| 手工立即探测 | 缺失 | UI/API/CLI 都没有 probe 命令或按钮 |
| 监控服务自身指标 | 缺失 | 无扫描耗时、失败次数、探测延迟、通知抑制计数 |
| feedback 关联 | 缺失 | 无相关反馈数量、错误签名或趋势 |
| 任务重试按钮 | 明确没有 | v1 只读合同禁止 retry/requeue/cancel |

## 4. 外部同类方案启示

### 4.1 Kubernetes 探针分层

官方文档将探针拆分为 startup、liveness、readiness：startup 负责初始化是否完成，liveness 负责不可恢复卡死，readiness 负责是否可接流量。对应到本项目：

- startup：队列目录、数据库、schema、WAL 写能力和调度器启动。
- liveness：Collector 进程/MCP transport 是否仍响应。
- readiness：SellerSprite Bundle 是否可以接受新任务。

当前 Collector 将 Bundle startup 失败等同于整个进程失败，使 health 工具也不可达。更合适的是基础服务保持可诊断，业务工具 fail-closed。

来源：https://kubernetes.io/docs/concepts/workloads/pods/probes/

### 4.2 Prometheus Blackbox 主动探测

Multi-target exporter 模式强调从目标外部测量可达性和延迟，尤其适合目标自身无法暴露完整指标的情况。独立 Collector Monitor 应继续作为外部探测者，避免只依赖 Collector 自报健康。

来源：https://prometheus.io/docs/guides/multi-target-exporter/

### 4.3 Grafana 告警状态

Grafana 将评估间隔、Pending period、Keep firing for 分开，避免瞬时波动产生告警抖动。现有 Monitor 已有 opening/reminder/recovery，但数据源和 Collector 故障尚未进入同一状态机，恢复也只需一轮成功。建议统一纳入连续失败/连续恢复门槛。

来源：https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/

### 4.4 Alertmanager 聚合与抑制

Alertmanager 使用 grouping、inhibition、silence，避免数据库总故障时产生数百个任务级告警。项目应增加根因抑制：当 `queue_database_unavailable` 活动时，抑制派生的 `worker_unavailable` 和大量任务停滞通知，但仍在详情中保留受影响数量。

来源：https://prometheus.io/docs/alerting/latest/alertmanager/

### 4.5 Sentry 指纹聚合

Sentry 以 fingerprint 将相同错误聚合成 issue，并保留聚合依据。Monitor 与 feedback 的关联也应基于稳定错误签名，而不是原始错误全文。推荐签名字段：`service_id + module + check + stable_error_code`。

来源：https://docs.sentry.io/concepts/data-management/event-grouping/

## 5. feedback 是否适合接入

适合，但只能作为辅助信号，不能成为健康判断的唯一数据源。

适合的用途：

- 显示最近 30/60 分钟相同错误签名的反馈数量与趋势。
- 发现“监控显示健康但用户持续报错”的观测缺口。
- 将 incident 与匿名化 feedback group 关联，帮助判断影响面。
- 从失败调用中的 `tool/command_name/mcp_tool_name/error_message` 提取稳定签名。

不适合的用途：

- 用反馈是否出现决定服务是否健康；反馈有延迟且依赖 Agent 提交。
- 在 Monitor 中展示邮箱、请求参数、payload、附件或完整异常。
- 让公开 `collector_monitor` 直接持有 feedback open-query 密钥。

当前 `ops-feedback-query` 是唯一允许直连 open-query API 的内部 Skill。建议由其定时生成脱敏的本地 JSON 快照，Monitor 只读该快照。这样不违反内部 API 访问边界，也不会把密钥带入 Monitor 进程。

当前查询 API 支持时间、类型、严重度、状态、来源、系统和全文搜索，但缺少 `mcp_tool_name/command_name/error_code/feedback_group_key` 的结构化过滤。MVP 可在受限时间窗口内批量详情后本地聚合；长期应补结构化过滤，避免全量扫描。

## 6. 建议优先级

### P0：先让故障可见且可恢复

1. 增加显式 SellerSprite 队列路径配置，并让 Collector 与 Monitor 复用同一解析函数。
2. 修正文档中的生产路径，增加部署前 path identity 校验。
3. Collector 启动时执行同服务账号的队列写能力预检；失败时输出稳定错误码。
4. 独立部署 Monitor，先关闭通知观察 24 小时，再启用企业微信。
5. 将 `queue_source_unavailable`、`monitor_state_unavailable`、`collector_unavailable` 纳入 incident。
6. 增加只读“立即探测”按钮与 CLI，展示耗时、时间、结果和错误类。

### P1：减少告警噪音并帮助定位

1. 连续失败和连续恢复门槛。
2. 根因抑制与维护静默。
3. 扫描耗时、失败次数、最后成功探测、通知抑制数。
4. feedback 脱敏快照与 incident 关联。
5. 生产部署安装脚本、systemd unit 校验和 smoke test。

### P2：受控恢复动作

1. Bundle 重新初始化或服务重启应走独立运维控制面，有权限、审计和冷却。
2. 任务 requeue 仅允许已有 job、可证明幂等且租约已过期的场景。
3. 对“未入队失败”不能提供盲目重试：原请求未持久化，Monitor 也不应读取敏感参数。

## 7. 尚需生产证据

代码证据可以确认错误类别与监控盲区，但不能仅凭仓库确认今天生产环境到底是路径漂移、权限变化、磁盘只读、挂载丢失还是磁盘耗尽。上线前需要由运维在 Collector 服务账号上下文核对：

- 实际 `HOME` 与队列绝对路径；
- 每一级父目录的执行权限与所有者；
- 数据库及 WAL/SHM sidecar 的写权限；
- 文件系统只读、磁盘空间和 inode；
- Collector systemd unit 最近是否修改用户、环境文件或 hardening；
- 相同路径下 SQLite `quick_check` 与最小事务能否成功。
