# Collector Monitor 运维说明

> 内部文档，仅供 Collector Monitor 部署、巡检和故障排查使用。Monitor v1 是严格只读的监督服务，不是任务控制台。

## 1. 文档状态与使用前提示

本文对应 2026-07-29 批准的一期范围。当前 worktree 已落盘配置、分类器、严格只读仓储、轮询服务、事故状态库、企业微信通知器、CLI、Starlette API/UI 和独立 Uvicorn 入口。本文第 4、8、9 节名称均已按实现确认；第 16 节仅保留尚未参数化或与批准设计存在差异的行为，部署时不得自行假设隐藏配置。

详细架构、健康模型和安全边界参见[采集任务监控服务设计](../design/采集任务监控服务设计.md)。

## 2. 一期能力边界

Collector Monitor v1 只提供：

- SellerSprite 任务进度、运行时和队列健康监督；
- `healthy`、`slow`、`stalled`、`orphaned` 任务分类；
- `queue_starved`、`worker_unavailable` 队列事件；
- Starlette 只读网页和 JSON API；
- 本地只读 CLI；
- 企业微信 Webhook 告警、去重、冷却和恢复通知。

Collector Monitor v1 **不提供**：

- 取消、失败、重试、重新入队或调整任务顺序；
- 启动、停止或重启 Collector/Worker；
- 浏览器启动、登录、验证码处理或任何浏览器控制；
- 自动修复业务 SQLite；
- 飞书通知；
- 可直接暴露公网的内置认证能力。

看到异常后应先取证，再按现有 Collector/SellerSprite 运维流程处置。不要因为监控页面显示 `stalled` 或 `orphaned` 就直接修改 SQLite 或重复提交任务。

## 3. 部署前检查

### 3.1 版本与命令

使用将要部署的 Python 环境执行：

```bash
opscli --version
opscli collector-monitor --help
opscli collector-monitor serve --help
opscli collector-monitor status --help
opscli collector-monitor tasks --help
opscli collector-monitor show --help
opscli collector-monitor incidents --help
opscli-collector-monitor --help
command -v opscli-collector-monitor   # Linux
# Windows PowerShell 使用：Get-Command opscli-collector-monitor
```

应看到五个子命令：`serve`、`status`、`tasks`、`show`、`incidents`。独立入口使用 `argparse` 支持 `--host`、`--port` 和 `--help`，不提供查询子命令。如果导入时报 `No module named 'opscli.collector_monitor'`，说明安装产物不完整或当前环境不是预期版本，不要仅凭 `pyproject.toml` 已声明入口就继续部署。

### 3.2 业务监督字段

SellerSprite 业务库默认位置已确认：

```text
~/.config/opscli/seller_sprite/task_queue.sqlite3
```

Monitor 一期至少依赖任务进度字段：

```text
progress_stage
progress_at
progress_sequence
```

还依赖任务租约字段：

```text
execution_owner
heartbeat_at
lease_expires_at
```

调度器运行时通过 `seller_sprite_runtime_heartbeats` 持久化，SellerSprite 队列 schema 当前为 v6。已确认字段为：`execution_owner`、`lifecycle_state`、`heartbeat_at`、`generic_workers_alive`、`listing_worker_alive`、`generic_available_capacity`、`listing_available_capacity`、兼容展示用 `available_capacity`、`standby_capacity`、`last_claim_at`、`last_progress_at`。只有生命周期为 `running`、`ready` 或 `healthy`，且心跳年龄严格小于运行时陈旧阈值，才算新鲜运行时；达到阈值即失联。队列判断必须按 `task_kind` 使用精确容量；容量从同一队列范围的 SQLite 全局 `running` 账号占用与本实例活跃尝试并集计算，已扣除 Generic、Listing、专属任务及其他调度器共享账号产生的互斥占用，不能仅凭本进程任务、任务租约、Worker 存活数或聚合容量宣称可消费。

普通任务认证故障接替时，备用账号改绑使用当前任务代际 CAS。候选若已被其他调度器或任务占用，应按接口顺序归还健康备用池并继续尝试下一候选；当前代际已失效时旧 worker 会立即停止，不再耗尽账号池、关闭可能被新代际复用的会话或删除新代际续租跟踪；全部候选冲突时，当前代际任务会安全结束为失败，不会因工作槽退出而永久留在 `running`。

### 3.3 服务账号与目录权限

生产建议为 Monitor 使用独立系统账号。该账号应具有：

| 资源 | 权限 |
|---|---|
| SellerSprite `task_queue.sqlite3` 及现有 `-wal`、`-shm` 文件 | 只读 |
| SellerSprite 业务库父目录 | 只允许必要的遍历/读取，不允许创建或删除文件 |
| Monitor 私有状态目录 | 读写 |
| 企业微信 Webhook 文件 | 只读，仅服务账号可读 |
| 账号绑定库、密钥、浏览器 Profile | 无权限 |

Monitor 应以 SQLite URI `mode=ro` 并启用 `PRAGMA query_only=ON`。业务库和 Monitor 私有状态库必须是不同物理文件，也不能通过符号链接或硬链接指向同一文件；配置加载和每次状态库写连接都会复核，写连接还会读取 SQLite `main` 实际打开路径后再次比较。业务库不存在时，Monitor 必须报未就绪，不能创建空库。

### 3.4 时间同步

健康判定依赖任务进度、租约和运行时心跳时间。部署前确认 Collector 主机和 Monitor 主机使用 NTP/chrony 等方式同步时钟。跨主机时钟偏差应显著小于最小健康阈值。

## 4. 配置变量

下表名称和默认值已按 `opscli.collector_monitor.config.MonitorSettings`、`load_settings()` 与完整设置校验器确认。Monitor 只读取进程环境，不自动加载 `.env` 或 `config.ini`；请由 Shell、systemd 或部署工具导入。数值无效、`NaN` 或 `Infinity` 会在启动前报错，不会静默回退；手工构造设置也执行相同校验。

| 环境变量 | 已确认默认值 | 生产建议 | 说明 |
|---|---:|---:|---|
| `OPSCLI_COLLECTOR_MONITOR_HOST` | `127.0.0.1` | `127.0.0.1` | HTTP 监听地址 |
| `OPSCLI_COLLECTOR_MONITOR_PORT` | `8767` | 按端口规划 | HTTP 端口，合法范围 1～65535 |
| `OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH` | `~/.config/opscli/seller_sprite/task_queue.sqlite3` | 使用绝对路径 | 严格只读业务库；不得与状态库为同一物理文件 |
| `OPSCLI_COLLECTOR_MONITOR_STATE_DB_PATH` | `~/.config/opscli/collector_monitor/state.sqlite3` | 独立持久卷 | 不得通过路径、符号链接或硬链接指向业务库 |
| `OPSCLI_COLLECTOR_MONITOR_URL` | `http://<HOST>:<PORT>` | 可选内网 HTTPS 地址 | Monitor 基址；加载时去除尾部 `/`，不得包含凭证 |
| `OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_URL` | 空 | 按需启用 | 配置 API Key 文件时必须使用 HTTPS，仅明确回环地址允许 HTTP |
| `OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_API_KEY_FILE` | 空 | 受保护绝对路径 | 可选 Collector MCP API Key 文件；禁止直接配置 Key 原文；携带 Key 时禁止自动跟随重定向 |
| `OPSCLI_COLLECTOR_MONITOR_COLLECTOR_PROBE_TIMEOUT` | `5` | `5` 起步 | Collector MCP 探测总超时秒数，覆盖受保护文件读取和远端调用，必须大于 0 |
| `OPSCLI_COLLECTOR_MONITOR_POLL_INTERVAL` | `10` | `10` 起步 | 扫描周期秒数，必须大于 0 |
| `OPSCLI_COLLECTOR_MONITOR_STALLED_THRESHOLD` | `300` | 依据最长正常进度间隔调整 | 无真实进度停滞阈值；`slow` 从一半即 `150` 秒开始 |
| `OPSCLI_COLLECTOR_MONITOR_QUEUE_THRESHOLD` | `300` | 依据正常排队时间调整 | 触发 `queue_starved` / `worker_unavailable` 的排队年龄 |
| `OPSCLI_COLLECTOR_MONITOR_RUNTIME_STALE_THRESHOLD` | `300` | 覆盖正常心跳抖动 | Worker/调度器心跳陈旧阈值 |
| `OPSCLI_COLLECTOR_MONITOR_ORPHAN_REQUIRED_SCANS` | `2` | `2` 起步 | owner 或租约失效后确认 `orphaned` 的连续扫描次数，必须至少为 1 |
| `OPSCLI_COLLECTOR_MONITOR_ALERT_COOLDOWN` | `1800` | `1800` 起步 | 同一事件重复提醒冷却秒数 |
| `OPSCLI_COLLECTOR_MONITOR_WEBHOOK_FILE` | 空 | 受保护绝对路径 | 企业微信 Webhook 文件；空表示禁用通知 |

SellerSprite 已确认的相关变量：

| 环境变量 | 当前默认值 | 说明 |
|---|---:|---|
| `OPSCLI_SELLER_SPRITE_TASK_TIMEOUT_SECONDS` | `600` | 单任务执行上限 |
| `OPSCLI_SELLER_SPRITE_TASK_LEASE_SECONDS` | `60` | 执行租约长度 |
| `OPSCLI_SELLER_SPRITE_TASK_HEARTBEAT_SECONDS` | `20` | 租约续期周期，实际调度器会限制为租约的一半以内 |
| `OPSCLI_SELLER_SPRITE_ACCOUNT_CACHE_TTL_SECONDS` | `600` | 账号池刷新周期 |

配置文件中不要保存 Webhook URL；只能保存 Webhook 文件路径。

## 5. 企业微信 Webhook 文件

### 5.1 Linux

创建仅服务账号可访问的目录和文件：

```bash
sudo install -d -m 0700 -o opscli-monitor -g opscli-monitor /etc/opscli/collector-monitor
sudo -u opscli-monitor sh -c 'umask 077; : > /etc/opscli/collector-monitor/wecom-webhook'
sudoedit /etc/opscli/collector-monitor/wecom-webhook
sudo chown opscli-monitor:opscli-monitor /etc/opscli/collector-monitor/wecom-webhook
sudo chmod 0600 /etc/opscli/collector-monitor/wecom-webhook
```

使用编辑器写入单行完整企业微信群机器人 Webhook 纯文本；不接受 JSON 对象或多行内容。通知器每次发送前重新读取文件，不缓存内容。不要用带真实 URL 的命令行参数或 `echo` 命令，避免进入 Shell 历史、进程列表或自动化日志。POSIX 上代码还会拒绝 group/other 具有任意权限的文件；Windows 下仍须由管理员正确设置 ACL。

校验元数据时不要输出内容：

```bash
sudo stat -c '%U %G %a %n' /etc/opscli/collector-monitor/wecom-webhook
```

期望所有者为 `opscli-monitor`，权限为 `600`。

### 5.2 Windows 本地验证

```powershell
$secretDir = Join-Path $env:USERPROFILE ".config\opscli\collector_monitor"
New-Item -ItemType Directory -Force $secretDir | Out-Null
$webhookFile = Join-Path $secretDir "wecom-webhook"
New-Item -ItemType File -Force $webhookFile | Out-Null
notepad.exe $webhookFile
icacls $webhookFile /inheritance:r
icacls $webhookFile /grant:r "$($env:USERNAME):(R)"
```

不要执行 `Get-Content $webhookFile` 后截屏或粘贴终端输出。若 ACL 命令因域策略不同失败，应由 Windows 管理员按“仅当前服务账号读取”原则设置权限。

### 5.3 轮换

1. 在企业微信创建或轮换机器人 Webhook。
2. 使用受控编辑器原地替换文件内容，不改变所有者和权限。
3. 无需重启：当前通知器在每次发送前重新读取文件；若后续实现改为缓存，再按同版本说明重载服务。
4. 通过下一次真实事故/提醒或受控测试验证新 Webhook；当前 API/CLI 不提供 `configured` 摘要字段。
5. 在企业微信侧撤销旧 Webhook。
6. 检查事故 `delivery_error_class` 和应用日志，确认没有旧、新 Webhook 原文。

通知正文中的规则、对象、严重度和消息会先移除控制字符、折叠换行并转义 Markdown 控制字符，避免动态标识改变消息结构；普通任务 ID 的连字符保持可读。Webhook 未配置时投递状态记为 `disabled` 终态，不作为失败重试。

## 6. 本地启动示例

服务读取第 4 节已确认的环境变量。`serve` 和独立入口都可用 `--host`、`--port` 覆盖监听配置；省略时读取环境配置。两种入口的监听覆盖都不会同步改写查询 CLI 使用的 `OPSCLI_COLLECTOR_MONITOR_URL`。

### 6.1 Windows PowerShell

不启用通知的本地只读验证：

```powershell
$env:OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH = `
  (Join-Path $env:USERPROFILE ".config\opscli\seller_sprite\task_queue.sqlite3")
$env:OPSCLI_COLLECTOR_MONITOR_STATE_DB_PATH = `
  (Join-Path $env:TEMP "opscli-collector-monitor\state.sqlite3")
$env:OPSCLI_COLLECTOR_MONITOR_HOST = "127.0.0.1"
$env:OPSCLI_COLLECTOR_MONITOR_PORT = "8767"

.\.venv\Scripts\opscli.exe collector-monitor serve
```

启用企业微信：

```powershell
$env:OPSCLI_COLLECTOR_MONITOR_WEBHOOK_FILE = `
  (Join-Path $env:USERPROFILE ".config\opscli\collector_monitor\wecom-webhook")

.\.venv\Scripts\opscli-collector-monitor.exe
```

浏览器访问默认地址：

```text
http://127.0.0.1:8767/
```

不要用开发临时状态库进行正式告警，否则重启或临时目录清理会破坏去重和恢复闭环。

### 6.2 Linux 前台验证

```bash
export OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH=/var/lib/opscli/seller_sprite/task_queue.sqlite3
export OPSCLI_COLLECTOR_MONITOR_STATE_DB_PATH=/var/lib/opscli-collector-monitor/state.sqlite3
export OPSCLI_COLLECTOR_MONITOR_WEBHOOK_FILE=/etc/opscli/collector-monitor/wecom-webhook
export OPSCLI_COLLECTOR_MONITOR_HOST=127.0.0.1
export OPSCLI_COLLECTOR_MONITOR_PORT=8767

/opt/opscli/venv/bin/opscli collector-monitor serve
```

也可使用独立入口：

```bash
/opt/opscli/venv/bin/opscli-collector-monitor
```

启动后先保持 Webhook 未配置，观察一段时间的分类是否符合真实任务耗时，再启用通知。

## 7. systemd 示例

以下示例假设：

- opscli 安装在 `/opt/opscli/venv`；
- SellerSprite 业务库在 `/var/lib/opscli/seller_sprite/task_queue.sqlite3`；
- Monitor 私有状态在 `/var/lib/opscli-collector-monitor`；
- Webhook 文件在 `/etc/opscli/collector-monitor/wecom-webhook`；
- 已创建 `opscli-monitor` 服务账号，并通过文件 ACL/组权限获得业务库只读访问。

创建 `/etc/systemd/system/opscli-collector-monitor.service`：

```ini
[Unit]
Description=opscli Collector Monitor只读采集任务监控服务
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opscli-monitor
Group=opscli-monitor
WorkingDirectory=/var/lib/opscli-collector-monitor
Environment=PYTHONUNBUFFERED=1
Environment=OPSCLI_COLLECTOR_MONITOR_HOST=127.0.0.1
Environment=OPSCLI_COLLECTOR_MONITOR_PORT=8767
Environment=OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH=/var/lib/opscli/seller_sprite/task_queue.sqlite3
Environment=OPSCLI_COLLECTOR_MONITOR_STATE_DB_PATH=/var/lib/opscli-collector-monitor/state.sqlite3
Environment=OPSCLI_COLLECTOR_MONITOR_WEBHOOK_FILE=/etc/opscli/collector-monitor/wecom-webhook
EnvironmentFile=-/etc/opscli/collector-monitor.env
ExecStart=/opt/opscli/venv/bin/opscli-collector-monitor
Restart=on-failure
RestartSec=5s
TimeoutStopSec=30s
UMask=0077

NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths=/var/lib/opscli/seller_sprite
ReadOnlyPaths=/etc/opscli/collector-monitor/wecom-webhook
ReadWritePaths=/var/lib/opscli-collector-monitor

[Install]
WantedBy=multi-user.target
```

如果打包产物因本机平台需要可执行内存，`MemoryDenyWriteExecute=true` 可能与运行时不兼容；只能在验证后移除该单项，不要整体取消其他隔离。若实际业务库位于用户 Home，需重新设计显式只读路径，不能简单关闭 `ProtectHome` 后给整个 Home 访问权。

加载和启动：

```bash
sudo install -d -m 0700 -o opscli-monitor -g opscli-monitor /var/lib/opscli-collector-monitor
sudo systemctl daemon-reload
sudo systemctl enable --now opscli-collector-monitor.service
sudo systemctl status opscli-collector-monitor.service
```

查看脱敏日志：

```bash
sudo journalctl -u opscli-collector-monitor.service --since "30 minutes ago"
```

不要使用会输出完整环境变量或进程环境的诊断命令保存工单附件。systemd unit 只保存 Webhook **文件路径**，不能保存 Webhook URL。

## 8. CLI 速查

当前 CLI 已确认始终输出 JSON，查询命令通过 `OPSCLI_COLLECTOR_MONITOR_URL` 访问 Monitor；没有额外 `--json` 开关。

| 目的 | 命令 | 关键行为 | 是否写业务库 |
|---|---|---|---|
| 启动监控服务 | `opscli collector-monitor serve [--host HOST] [--port PORT]` | 选项覆盖监听地址和端口；省略时读取环境配置 | 否 |
| 查看监控状态 | `opscli collector-monitor status` | 数据源未就绪或有活动事故时仍输出 JSON，但退出码为 `2` | 否 |
| 查看任务 | `opscli collector-monitor tasks [--health HEALTH]` | 仅支持按健康分类过滤 | 否 |
| 查看单任务 | `opscli collector-monitor show JOB_ID` | 返回脱敏任务和进度时间线 | 否 |
| 查看全部事故 | `opscli collector-monitor incidents` | 同时返回活动和已恢复事故 | 否 |
| 使用独立入口启动 | `opscli-collector-monitor [--host HOST] [--port PORT]` | `argparse` 入口；支持 `--help`，无查询子命令 | 否 |

常用查询：

```bash
opscli collector-monitor status
opscli collector-monitor tasks --health orphaned
opscli collector-monitor tasks --health worker_unavailable
opscli collector-monitor show JOB_ID
opscli collector-monitor incidents
```

`tasks --health` 只接受 `healthy`、`slow`、`stalled`、`orphaned`、`queue_starved`、`worker_unavailable`。CLI HTTP 超时固定为 10 秒；不可达时退出码为 `1`，并输出稳定 JSON 错误。CLI 不提供 `cancel`、`retry`、`requeue`、`fail`、`browser` 或 `recover`。

## 9. UI、API 与探针速查

以下路径已按 Starlette 路由确认。所有响应都设置 `Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。

### 9.1 网页

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | 单页嵌入式只读仪表盘；无外部 CDN，以 7 秒间隔刷新缓存状态 |

一期没有独立 `/tasks` 或 `/incidents` HTML 路由；任务、Generic/Listing 分类容量、Collector MCP 状态、活动和已恢复事故历史、进度时间线都在首页展示。

### 9.2 探针与 JSON API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health/live` | Monitor 进程存活，固定返回 `{"status":"live"}` |
| `GET` | `/health/ready` | 首次本地队列扫描成功时返回 `200`；未就绪返回 `503` 和脱敏数据源错误 |
| `GET` | `/api/v1/status` | 完整脱敏缓存快照：数据源、Collector 探测、摘要、任务、运行时和事故 |
| `GET` | `/api/v1/tasks?health=<值>&status=<值>&task_kind=<值>&limit=<1..500>` | 任务列表；过滤均可选，默认 100 条，拒绝未知参数 |
| `GET` | `/api/v1/tasks/{job_id}` | 单任务脱敏监督详情和进度时间线；不存在时返回 `404` |
| `GET` | `/api/v1/incidents?status=<值>&rule=<值>&limit=<1..500>` | 事故列表；过滤均可选，默认 100 条 |

本机检查：

```bash
curl --fail --silent --show-error http://127.0.0.1:8767/health/live
curl --fail --silent --show-error http://127.0.0.1:8767/health/ready
curl --fail --silent --show-error http://127.0.0.1:8767/api/v1/status
```

`/health/live` 成功只表示 Monitor 自身可响应；`/health/ready` 失败通常表示业务库不可读、schema 不匹配或尚未完成首次成功扫描。配置或私有状态库初始化失败通常会让进程直接启动失败。业务任务存在 `stalled` 不会让存活或就绪探针失败，但会让 CLI `status` 返回退出码 `2`。

API v1 只允许读取。任务过滤允许 `health` 六种健康值、`status=queued|running|succeeded|failed`、`task_kind=generic|listing_analysis`；事故过滤允许 `status=active|resolved` 与四种 `rule`。两个列表的 `limit` 默认为 100、最大 500，但 API 只过滤轮询缓存：当前快照最多 1000 条任务和最近 500 条事故。任何 `POST`、`PUT`、`PATCH`、`DELETE` 业务端点都不属于一期。

## 10. 日常巡检

### 10.1 服务状态

```bash
systemctl is-active opscli-collector-monitor.service
curl --fail http://127.0.0.1:8767/health/live
curl --fail http://127.0.0.1:8767/health/ready
opscli collector-monitor status
```

重点检查：

- `generated_at` 和 `source.last_scan_at` 是否持续更新，并结合 `source.ready`、`source.last_success_at` 与稳定 `source.error_code` 判断后台扫描是否持续成功；首次扫描不阻塞 ASGI 启动，因此刚启动时 `/health/live` 可用而 `/health/ready` 仍可能为 503；
- 业务数据源是否为只读可用；
- Monitor 私有状态库是否可写；
- `healthy`、`slow`、`stalled`、`orphaned` 数量变化；
- `queue_starved`、`worker_unavailable` 是否活动；
- 事故的 `alert_status`、`recovery_status`、最近投递时间和 `delivery_error_class`；当前没有通知是否配置或抑制计数摘要，任何输出都不应显示 URL。

### 10.2 任务异常

```bash
opscli collector-monitor tasks --health stalled
opscli collector-monitor tasks --health orphaned
```

取证字段应至少包括：

- `job_id`；
- 业务 `lifecycle` 与监督 `health`；
- `progress_stage`；
- 最近进度年龄或时间；
- 租约与 Worker 运行时是否新鲜；
- 稳定、脱敏的判定原因。

不要要求 Monitor 输出 `request_json`、用户邮箱、账号、绝对路径或错误原文来“方便排查”。确需业务细节时，应在受控服务主机按 SellerSprite 运维手册使用授权工具查询。

### 10.3 事件闭环

```bash
opscli collector-monitor incidents
```

核对：

1. `opened_at` 与 `last_seen_at`。
2. `last_alert_at` 和按 `ALERT_COOLDOWN` 推算的冷却截止时间。
3. 同一 `(rule, subject)` 是否只有一条活动事故。
4. `recovery_status` / `last_recovery_at` 是否表明恢复通知成功发送一次；恢复投递失败时，当前实现会在 `ALERT_COOLDOWN` 到期后重新产生 recovery 动作。
5. Monitor 重启后冷却状态是否延续。

## 11. 健康状态处置

### 11.1 `slow`

含义：运行任务的进度年龄已达到 `STALLED_THRESHOLD / 2` 但尚未停滞，或 owner、运行时、租约已不可信但尚未达到 `ORPHAN_REQUIRED_SCANS`；也可能是排队年龄已达到 `QUEUE_THRESHOLD / 2`，或达到完整阈值但匹配 Worker 仍有近期领取/进度活动。

处理：

1. 对照相同场景近期耗时分布。
2. 检查 `progress_sequence` 是否继续增长。
3. 检查第三方延迟、网络和任务规模。
4. 继续观察，不要重复提交任务。
5. 如果大量正常任务频繁进入 `slow`，按第 13 节调阈值。

### 11.2 `stalled`

含义：任务仍为 `running`，Worker/租约看似存在，但真实业务进度超过阈值未变化。

处理：

1. 记录 `job_id`、阶段、最近进度时间和持续时长。
2. 检查 Collector/SellerSprite 日志中的稳定错误码和阶段。
3. 确认是否处于允许长轮询的阶段，如已确认阶段 `remote_poll` 或 `browser_wait`。
4. 检查第三方接口、验证码、页面阻塞或网络。
5. 不通过 Monitor 取消、重试或操作浏览器。
6. 如需人工队列处置，回到《卖家精灵服务运维手册》的写操作审批流程。

### 11.3 `orphaned`

含义：运行任务没有可信执行 owner、关联调度器运行时不存在或心跳过期，或租约为空/过期，且已连续满足 `ORPHAN_REQUIRED_SCANS` 轮。

处理：

1. 检查 Collector MCP/SellerSprite 调度器进程是否重启或崩溃。
2. 检查主机时钟和 SQLite 最新提交是否正常。
3. 确认原浏览器或第三方任务是否仍有副作用。
4. 优先等待 SellerSprite 自身的租约恢复机制。
5. 不直接修改 SQLite，不在原执行仍可能存活时人工重排。

### 11.4 `queue_starved`

含义：任务排队年龄达到 `QUEUE_THRESHOLD`，存在心跳新鲜且对应 `task_kind` 精确可用容量大于 0 的运行时，但这些运行时在完整观察窗口内没有 `last_claim_at` 或 `last_progress_at` 新活动。`listing_analysis` 使用 `listing_available_capacity`，其他任务使用 `generic_available_capacity`；两类容量均已扣除 Generic、Listing 与专属任务共享账号产生的互斥占用。

处理：

1. 检查队列健康计数、最老任务年龄，以及匹配运行时的 `last_claim_at` / `last_progress_at`。
2. 检查调度循环是否异常但心跳循环仍存活。
3. 检查账号槽是否被长期运行任务占用。
4. 核对 `generic` 与 `listing_analysis` 的对应 Worker 槽位是否真实可消费，而不只是计数非零。
5. 服务恢复后观察原任务自行消费，不要批量重复提交。

### 11.5 `worker_unavailable`

含义：任务排队年龄达到 `QUEUE_THRESHOLD`，但 scheduler 已失联，或没有心跳新鲜且对应 `task_kind` 真实可领取容量大于 0 的运行时。真实容量按类型选择，并扣除共享账号互斥占用；聚合 `available_capacity` 不能代替类型容量。

处理：

1. 检查 Collector MCP/SellerSprite 调度器进程状态。
2. 检查账号接口、公共账号池、专属账号绑定和工作槽初始化日志。
3. 检查运行时监督记录是否由正确实例持续更新。
4. 恢复 Worker 后观察队列；Monitor 不执行服务重启或任务重排。

## 12. 故障排查

### 12.1 命令导入失败

现象：

```text
No module named 'opscli.collector_monitor'
```

检查：

1. `opscli --version` 与部署预期是否一致。
2. 当前终端和 systemd 是否使用同一虚拟环境。
3. 当前 wheel 是否真的包含 `opscli/collector_monitor`。
4. `opscli-collector-monitor` 入口是否来自旧环境残留。

不要通过手工创建空模块或只补入口脚本绕过，应重新安装包含完整 Monitor 包的同一版本。

### 12.2 `/health/ready` 失败：业务库不存在

检查配置的绝对路径、服务账号、`HOME` 和部署持久卷。Monitor 必须拒绝创建空库。确认路径前不要启动 SellerSprite 队列写命令，以免在错误目录生成新数据库。

### 12.3 `/health/ready` 失败：业务库不可读

检查：

```bash
namei -l /var/lib/opscli/seller_sprite/task_queue.sqlite3
ls -l /var/lib/opscli/seller_sprite/task_queue.sqlite3*
```

只记录文件所有者、权限和文件名，不读取内容。WAL 模式下还需确保已有 `-wal`、`-shm` 可由服务账号读取，并且目录可遍历。不要为了排查把业务目录改成全局可写。

### 12.4 `/health/ready` 失败：schema 不兼容

核对缺失的是任务进度字段还是调度器运行时表。正确处理是发布兼容版本的 SellerSprite 监督写入，再启动 Monitor。Monitor 不执行 `ALTER TABLE`、`PRAGMA user_version` 更新或任何业务迁移。

### 12.5 Monitor 私有状态库不可写

检查 `OPSCLI_COLLECTOR_MONITOR_STATE_DB_PATH` 的父目录、所有者、剩余空间和只读挂载。私有库不可写时，服务不应继续发送无法持久去重的告警，以免重启后轰炸。

修复权限后确认：

- 最近扫描时间恢复更新；
- 原活动事件未被重复首发；
- 恢复通知仍能闭环。

### 12.6 页面可打开但数据不更新

1. 检查 `generated_at` 是否推进，并确认同一快照的 `source.ready`。
2. 检查业务库路径是否指向真实 Collector 实例。
3. 检查业务 WAL 是否持续提交。
4. 检查系统时间。
5. 检查日志中的 SQLite busy、schema 或时间解析错误。
6. 不要通过刷新页面触发业务写入；页面查询应始终只读。

### 12.7 企业微信未收到通知

检查：

1. `OPSCLI_COLLECTOR_MONITOR_WEBHOOK_FILE` 是否指向正确的受保护文件。
2. 文件是否为非空单行纯文本 URL；POSIX 上必须是普通文件且 group/other 无任何权限，Windows 上检查服务账号 ACL。
3. 通知是否因同一 `(rule, subject)` 事件处于冷却期而被正常抑制。
4. Webhook 是否满足固定安全合同：HTTPS、主机 `qyapi.weixin.qq.com`、路径 `/cgi-bin/webhook/send`，且只有非空 `key` 查询参数。
5. 出站 HTTPS、DNS、代理和防火墙，以及企业微信机器人是否已撤销。
6. 事故公开字段中的 `delivery_error_class`；不要要求输出响应原文。

禁止把 Webhook、完整企业微信响应或请求体贴到日志和工单。

### 12.8 企业微信重复提醒

1. 检查 Monitor 是否有多个实例共用业务库但使用不同私有状态库。
2. 检查私有状态目录是否是临时目录或每次重启被清空。
3. 检查事故去重键 `(rule, subject)` 是否因上游标识不稳定而变化；当前实现不计算独立哈希指纹。
4. 检查 `OPSCLI_COLLECTOR_MONITOR_ALERT_COOLDOWN` 是否小于扫描周期。
5. 检查系统时钟回拨。

一期建议同一部署只运行一个通知实例。只读查询实例可以扩展，但必须明确单一通知领导者或共享一致的事件状态，不能靠多个独立状态库同时发消息。

### 12.9 一批任务突然全部 `orphaned`

优先检查数据源和时钟，不要立即对所有任务做业务处置：

1. 调度器运行时心跳表是否停止更新。
2. Monitor 是否读到了旧快照。
3. Collector 与 Monitor 主机时间是否偏移。
4. 业务库是否短暂不可读。
5. Collector/SellerSprite 调度器是否刚重启并生成了新的 `execution_owner`。

数据源不可用时，快照 `source.ready=false` 并携带安全错误；当前不会创建独立数据源事故，也不会执行事故对账，因此不会把既有任务事故误判为恢复或孤儿。

## 13. 阈值调优

### 13.1 调优原则

1. 先记录 3～7 天正常数据，再按场景和阶段统计进度间隔与总耗时。
2. `slow` 没有独立阈值：运行任务从 `STALLED_THRESHOLD / 2` 开始，排队任务从 `QUEUE_THRESHOLD / 2` 开始；调整完整阈值时必须同时评估 `slow`。
3. `STALLED_THRESHOLD` 参考最长正常阶段间隔 p99，并识别合法长轮询阶段。
4. `RUNTIME_STALE_THRESHOLD` 应覆盖正常 SellerSprite 心跳及短时调度抖动。
5. `ORPHAN_REQUIRED_SCANS × POLL_INTERVAL` 应覆盖短暂租约/owner 异常；它是连续观测次数，不是孤儿秒数。
6. `QUEUE_THRESHOLD` 应明显大于一次正常领取周期；老排队任务存在匹配类型的存活 Worker、正容量，但 `last_claim_at` / `last_progress_at` 在完整窗口内无活动时才是 `queue_starved`；没有匹配容量时是 `worker_unavailable`。
7. 每次只调整一类阈值，观察至少一个完整高峰周期。
8. 调阈值不是修复数据缺失的替代方案；`progress_at`、`last_claim_at` 或 `last_progress_at` 不更新时应先修监督写入。

### 13.2 推荐关系

当前 SellerSprite 默认：任务超时 600 秒、租约 60 秒、心跳 20 秒。已确认 Monitor 默认值及派生关系为：

```text
POLL_INTERVAL=10
RUNTIME_STALE_THRESHOLD=300
ORPHAN_REQUIRED_SCANS=2
slow 起点 = STALLED_THRESHOLD / 2 = 150
STALLED_THRESHOLD=300 <= task_timeout(600)
QUEUE_THRESHOLD=300
ALERT_COOLDOWN=1800 >> POLL_INTERVAL(10)
```

默认设置下，孤儿前置条件连续两轮扫描即可确认；实际耗时通常约为一个扫描间隔至两个扫描间隔，取决于异常出现在扫描周期中的位置。当前没有独立恢复宽限或事件保留期配置。

对于 Listing Analysis 等合法长轮询任务，优先让执行方按 `remote_poll` 等真实远端状态持续写低敏进度检查点；不要仅把 `STALLED_THRESHOLD` 全局值无限调大。

### 13.3 常见误调

| 现象 | 错误做法 | 正确方向 |
|---|---|---|
| 正常长任务频繁 `stalled` | 直接把全局阈值改成数小时 | 补充阶段进度；结合 `slow = stalled / 2` 调整全局阈值 |
| Worker 短抖动频繁报警 | 把所有任务阈值调大 | 调整 `RUNTIME_STALE_THRESHOLD` 或 `ORPHAN_REQUIRED_SCANS` |
| 告警太多 | 禁用所有通知 | 检查 `(rule, subject)` 去重键、冷却和重复实例 |
| 队列积压没报警 | 只调整任务停滞阈值 | 检查运行时心跳、可用容量和 `QUEUE_THRESHOLD` |
| 重启后重复首发 | 延长冷却 | 修复私有状态持久化和实例部署方式 |

## 14. 安全与脱敏红线

1. 禁止在环境变量、命令参数、systemd unit 或普通配置文件中直接保存企业微信 Webhook。
2. 禁止输出 Webhook、Authorization、API Key、JWT、Session、Cookie、卖家精灵密码或浏览器登录态。
3. 禁止让 Monitor 读取账号绑定密钥或浏览器 Profile。
4. 禁止向外部群聊、公开工单或截图发送完整任务 JSON、用户邮箱、账号、内部路径或错误堆栈。
5. 禁止直接修改 SellerSprite SQLite；Monitor 的业务连接必须是 `mode=ro` 和 `query_only`。
6. 禁止把 UI/API 直接暴露公网。监听非回环地址时必须有内网防火墙、TLS 和反向代理认证。
7. 禁止用查询接口代理现有 `queue fail`、`requeue-running` 或浏览器控制。
8. 禁止因通知发送失败而绕过去重状态无限重试。
9. 禁止清空私有状态库来“重发告警”，这会破坏冷却和恢复审计。
10. 禁止把飞书配置加入一期部署；一期唯一通知渠道是企业微信。

## 15. 升级、回滚与备份

### 15.1 升级

1. 记录当前 opscli 版本、Monitor 配置摘要和活动事件数。
2. 备份 Monitor 私有状态库；备份中不得包含 Webhook。
3. 先验证 SellerSprite 监督字段与目标 Monitor 版本兼容。
4. 停止 Monitor；不要停止或修改业务队列，除非另有维护计划。
5. 升级 opscli。
6. 执行 `opscli collector-monitor` 各子命令、`opscli-collector-monitor --help` 与 `/health/ready` 检查。
7. 启动后确认冷却状态延续，没有重复首发。

### 15.2 回滚

1. 停止 `opscli-collector-monitor` 独立服务。
2. 保留业务 SQLite 原样，不执行迁移或字段删除。
3. 恢复与旧 Monitor 版本兼容的私有状态库备份。
4. 回滚 opscli Monitor 版本并验证只读连接。
5. 若直接禁用 Monitor，Collector/SellerSprite 任务应继续执行，只是失去监控和企业微信提醒。

Monitor 私有状态库需要纳入备份以保留去重、冷却和恢复闭环；Webhook 文件应由密钥管理流程单独保护，不应打入普通状态库备份。

## 16. 已知实现差异与后续对齐项

配置、CLI、API、只读仓储、分类、事故状态和通知器均已落盘。正式部署前仍需对以下批准设计与当前实现差异作出明确决定；运维侧不能虚构配置绕过：

1. 当前没有独立恢复宽限：事故候选在一次可信扫描中消失即标记 `resolved` 并尝试恢复通知；若要防恢复抖动，需新增实现和配置。
2. 当前没有事件保留/归档策略：已恢复事故会持续保存在私有 SQLite 中。
3. Webhook 已配置但 opening/escalation/reminder 通知失败时，下一次扫描会立即重试原动作；没有退避或独立重试预算。Webhook 未配置记为 `disabled` 终态且不重试。recovery 失败按 `ALERT_COOLDOWN` 冷却后重投。
4. 企业微信 HTTP 超时由通用通知客户端固定为 5 秒，没有 Monitor 专用配置；当前没有网络级自动重试。同步发送已卸载到工作线程，单轮最多并发 4 条；业务扫描、Monitor 状态事务和通知结果写回也通过工作线程执行，不阻塞 Monitor 事件循环。
5. 当前阈值只支持全局值，不支持按场景或进度阶段覆盖；运行任务与排队任务的 `slow` 均从各自完整阈值的一半开始。
6. 事故主键是 `(rule, subject)`，没有单独 `fingerprint` 字段或单事故详情 API；事故列表已支持 `status`、`rule` 和有界 `limit`。
7. `OPSCLI_COLLECTOR_MONITOR_URL` 仅供 CLI 访问服务；当前企业微信消息不包含 Monitor 页面链接。两个启动入口的 `--host/--port` 都不会同步更新该 URL。
8. 每轮必须完整读取全部活动任务以免漏判事故；实现已使用 500 条游标批次、显式读事务、1000 条公开上限和批量时间线查询，但极端积压时仍应监控扫描耗时与 SQLite 读取压力。
9. Collector MCP 探测以不低于 60 秒的独立周期运行；远端响应进入缓存前只保留 module、queue、scheduler 与固定 runtime 白名单。Collector 探测失败和业务 SQLite 扫描失败当前均不创建事故或企业微信告警，只分别体现在 `collector` 或 `source` 摘要中。
10. 生产 sdist 支持由业务 `.c` 二次注册 Cython 扩展，并保留 Typer/FastMCP 反射所需纯 Python 模块。Windows 构建正式 Cython wheel 仍要求 MSVC；无编译器时 `SKIP_CYTHON=1` 只用于非生产安装验证。

已经确认、不应无理由改名的合同：

- `opscli collector-monitor` 及 `serve`、`status`、`tasks`、`show`、`incidents`；
- `opscli-collector-monitor` 与 `opscli.collector_monitor.server:run`；
- 第 4 节全部 `OPSCLI_COLLECTOR_MONITOR_*` 配置；
- `/health/live`、`/health/ready`、`/api/v1/status`、`/api/v1/tasks`、`/api/v1/tasks/{job_id}`、`/api/v1/incidents`；
- `progress_stage`、`progress_at`、`progress_sequence` 和 `seller_sprite_task_progress_events`；
- `seller_sprite_runtime_heartbeats` 及第 3.2 节列出的运行时字段；
- SellerSprite 默认业务库 `~/.config/opscli/seller_sprite/task_queue.sqlite3`。
