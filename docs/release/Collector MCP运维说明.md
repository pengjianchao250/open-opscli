# Collector MCP 运维说明

本文是 Collector MCP 的生产部署、数据沉淀、日常运维和故障恢复入口。规划文档只提供设计背景；生产操作以本文为准。

当前 Collector 只接入 SellerSprite。Keepa 不使用本节 MySQL 配置，也不会随 SellerSprite 自动沉淀。

## 1. 服务边界

客户端和 MCP Host 只访问 OPS 通用 MCP。通用 MCP 通过内网 `OPSCLI_COLLECTOR_MCP_URL` 静默调用 Collector，客户端不需要知道 Collector 地址。

```text
MCP Host / opscli seller-sprite
  -> OPS 通用 MCP :8765
  -> Collector MCP :8766
  -> SellerSprite 队列和文件
  -> Collector SQLite Outbox
  -> MySQL
```

数据沉淀只在 `opscli-collector-mcp` 进程中运行。通用 MCP 和 Keepa 不得配置 Collector MySQL 账号。

Collector 必须保持单实例、单 Worker。不要增加 Uvicorn Worker、Gunicorn Worker，也不要让多个实例写同一 SellerSprite 状态目录或 Outbox。

## 2. 本地启动（Windows）

终端一启动 Collector MCP：

```powershell
.\.venv\Scripts\python.exe -m opscli.collector_mcp.server `
  --transport both `
  --host 127.0.0.1 `
  --port 8766
```

终端二启动 OPS 通用 MCP：

```powershell
$env:OPSCLI_COLLECTOR_MCP_URL="http://127.0.0.1:8766/mcp"

.\.venv\Scripts\python.exe -m opscli.mcp.server `
  --transport both `
  --host 127.0.0.1 `
  --port 8765
```

关闭 Collector 后，SellerSprite 调用应返回 `COLLECTOR_MCP_UNAVAILABLE`。通用 MCP 不会回退到本地执行 SellerSprite。

本地与生产可以共用 MySQL，通过 `OPSCLI_DATA_ENVIRONMENT=debug` 和 `production` 区分数据。两端必须使用独立 Outbox。

## 3. 生产部署前置条件

部署前确认：

- Linux 已创建专用服务用户 `opscli`；
- `/opt/opscli/venv` 已安装目标版本；
- 目标版本包含当前 MySQL schema；
- SellerSprite 队列、输出目录和浏览器 Profile 对 `opscli` 可写；
- OPS `verify-key`、SellerSprite、MySQL、对象存储和 DNS 可达；
- 服务器时间同步；
- MySQL CA 文件和证书匹配的内网域名已准备；
- 只有一个 Collector 实例和一个 Worker。

生产 MySQL 强制验证 CA 和主机身份。`OPSCLI_COLLECTOR_MYSQL_HOST` 应使用证书匹配的域名，不要在证书不包含 IP 时直接填写 IP。

## 4. 生产目录与权限

创建持久目录：

```bash
sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/.config/opscli/collector

sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/mcp_quota

sudo install -d -m 0750 -o root -g opscli /etc/opscli
```

生产 Outbox 建议固定为：

```text
/var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3
```

Outbox 保存待入库状态、重试租约、`live_cutover_at` 和对账游标。它不保存大型 JSON 或 XLSX 正文，但仍属于必须备份的生产状态。

不要把本地 `debug` Outbox 复制到生产，也不要让 Outbox 与 SellerSprite `task_queue.sqlite3` 指向同一文件。

## 5. MySQL 账号与 TLS

推荐区分迁移账号和运行账号：

| 账号 | 用途 | 权限 |
|---|---|---|
| 迁移账号 | 首次建表或受控 schema 升级 | `SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES` |
| 运行账号 | 日常任务落库 | `SELECT, INSERT, UPDATE, DELETE` |

运行账号不需要 `CREATE`、`ALTER`、`DROP` 或 `GRANT`。账号应限制来源主机；无法立即拆分账号时，应记录临时风险和后续收权计划。

生产连接必须配置：

```text
OPSCLI_COLLECTOR_MYSQL_SSL_CA=/etc/opscli/mysql-ca.pem
```

CA 文件由数据库管理员提供。部署前使用运行账号确认 TLS、认证插件、数据库名和授权身份。

```sql
SELECT DATABASE(), CURRENT_USER(), VERSION(), @@require_secure_transport;
SHOW STATUS LIKE 'Ssl_cipher';
SHOW GRANTS FOR CURRENT_USER;
```

## 6. 生产环境文件

创建 `/etc/opscli/collector.env`。下面是完整最小模板：

```ini
OPSCLI_COLLECTOR_STORAGE_ENABLED=true
OPSCLI_DATA_ENVIRONMENT=production
OPSCLI_MCP_QUOTA_SQLITE_PATH=/var/lib/opscli/mcp_quota/quota.sqlite3

OPSCLI_COLLECTOR_STORAGE_SQLITE_PATH=/var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3

OPSCLI_COLLECTOR_MYSQL_HOST=mysql.internal.example.com
OPSCLI_COLLECTOR_MYSQL_PORT=3306
OPSCLI_COLLECTOR_MYSQL_DATABASE=polaris_ops_mcp
OPSCLI_COLLECTOR_MYSQL_USER=collector_writer
OPSCLI_COLLECTOR_MYSQL_PASSWORD="由部署 Secret 注入"
OPSCLI_COLLECTOR_MYSQL_SSL_CA=/etc/opscli/mysql-ca.pem

OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA=false
OPSCLI_COLLECTOR_STORAGE_BATCH_SIZE=500
OPSCLI_COLLECTOR_STORAGE_POLL_INTERVAL_SECONDS=2
OPSCLI_COLLECTOR_STORAGE_RECONCILE_INTERVAL_SECONDS=60
OPSCLI_COLLECTOR_STORAGE_LEASE_SECONDS=300
```

模板中的主机、账号和密码必须替换。密码应由部署平台或 Secret 管理器在发布时注入，不得提交 Git、写入镜像、命令行或日志。

如果部署平台只能渲染 `EnvironmentFile`，应将文件限制为 root 和服务组可读：

```bash
sudo chown root:opscli /etc/opscli/collector.env
sudo chmod 0640 /etc/opscli/collector.env

sudo chown root:opscli /etc/opscli/mysql-ca.pem
sudo chmod 0640 /etc/opscli/mysql-ca.pem
```

Collector 只读取进程环境变量，不会自动加载项目 `.env` 或 `config.ini` 中的 MySQL 配置。

## 7. systemd 部署

创建 `/etc/systemd/system/opscli-collector-mcp.service`：

```ini
[Unit]
Description=opscli Collector MCP
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opscli
Group=opscli
WorkingDirectory=/var/lib/opscli
Environment=HOME=/var/lib/opscli
EnvironmentFile=/etc/opscli/collector.env
ExecStart=/opt/opscli/venv/bin/opscli-collector-mcp --transport http --host 127.0.0.1 --port 8766 --auth-verify-url https://ops.example.com/api/v1/mcp/verify-key
Restart=on-failure
RestartSec=5
TimeoutStopSec=120
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

将示例 `--auth-verify-url` 替换为实际 OPS 验证地址。反向代理与 Collector 同机时保持监听 `127.0.0.1`。

SellerSprite 会启动浏览器子进程。增加 `ProtectSystem`、`PrivateDevices`、沙箱或进程限制前，必须使用 `opscli` 用户完成真实浏览器任务验证。

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opscli-collector-mcp.service
sudo systemctl status opscli-collector-mcp.service
```

OPS 通用 MCP 配置 Collector 内网地址：

```ini
OPSCLI_COLLECTOR_MCP_URL=https://collector-mcp.internal.example.com/mcp
```

同机且不经过反向代理时可以使用 `http://127.0.0.1:8766/mcp`。URL 不得携带共享 `api_key`。

## 8. MySQL schema 初始化

表结构由 `opscli.collector_mcp.storage.schema` 版本化。当前 schema 版本为 `1`，包含：

```text
collection_schema_versions
collection_runs
collection_artifacts
collection_datasets
collection_records
```

### 8.1 共享数据库已经初始化

本地和生产共用同一个 MySQL 时，只初始化一次。生产必须保持：

```ini
OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA=false
```

生产启动前查询：

```sql
SELECT module_name, schema_version, updated_at
FROM collection_schema_versions
WHERE module_name = 'collector_storage';
```

结果应为 `collector_storage / 1`。不要因为部署到新服务器而再次初始化同一个数据库。

### 8.2 全新空库首次初始化

仅全新空库使用迁移账号，并临时设置：

```ini
OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA=true
```

启动 Collector，确认 MySQL 健康并检查五张表。随后立即停止服务，切换运行账号，并将配置恢复为 `false`。

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name LIKE 'collection_%'
ORDER BY table_name;

SELECT * FROM collection_schema_versions;
```

不要手工插入 schema 版本。版本行只应在全部 DDL 成功并完成校验后由程序写入。

### 8.3 部分 schema 恢复

MySQL DDL 会自动提交。初始化中途失败时，可能出现部分表已存在但版本表为空。

先确认部署版本和错误原因，再使用迁移账号重新执行幂等初始化。不要删除已创建的表，也不要手工补版本行。

如果只有前四张表且缺少 `collection_records`，确认部署代码使用 `source_row_number`，而不是 MySQL 8 保留关键字 `row_number`。

## 9. 首次启动与验收

查看服务日志：

```bash
sudo journalctl -u opscli-collector-mcp.service --since "10 minutes ago"
```

使用已认证 MCP 客户端调用 `collector_modules_health`。存储部分必须为：

```json
{
  "status": "ready",
  "checks": {
    "outbox": "ok",
    "mysql": "ok",
    "worker": "running"
  }
}
```

健康响应不会返回 MySQL 主机、库名、账号、密码或本地文件路径。

检查 MySQL 最近任务：

```sql
SELECT
    id,
    data_environment,
    source_system,
    source_job_id,
    scenario,
    source_row_count,
    persistence_completed_at
FROM collection_runs
ORDER BY id DESC
LIMIT 20;
```

生产任务必须为 `data_environment='production'`。本地调试任务应保持 `debug`，两者通过幂等键中的环境字段隔离。

检查 Outbox：

```bash
sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3 \
  "SELECT status,COUNT(*) FROM collection_outbox GROUP BY status ORDER BY status;"
```

验收任务应从 `pending` 进入 `completed`，且 `last_error_code` 为空。不要为了验证重试机制重复调用 SellerSprite 采集。

## 10. 数据生命周期和历史边界

成功任务先进入独立 SQLite Outbox，再由后台 Worker 写入 MySQL。MySQL 不可用不会改变 SellerSprite 任务成功状态，也不会重新调用第三方。

Worker 只重试解析和落库，使用指数退避。恢复 MySQL 后，Outbox 中的 `pending` 或 `retrying` 会继续处理。

MySQL 幂等键为：

```text
(data_environment, source_system, source_job_id)
```

首次启用生产 Outbox 时会写入 `live_cutover_at`。自动对账只扫描该时间之后的成功事件，不会自动导入更早的生产历史文件。

历史生产数据迁移当前仅保留 TODO。未来 backfill 只处理 `succeeded`，先 dry-run，再以 `ingestion_mode=backfill` 幂等导入。

原始和导出文件不写入 MySQL BLOB。MySQL 只登记文件 URI、文件名、MIME、大小和 SHA-256；格式化 Dataset 按行写入 JSON。

## 11. Outbox 备份与恢复

Outbox 包含未完成任务和对账边界。删除或重新创建会丢失待入库状态，并改变历史扫描边界。

### 11.1 备份

最稳妥的方式是短暂停止 Collector 后备份：

```bash
sudo systemctl stop opscli-collector-mcp.service
sudo install -d -m 0700 -o opscli -g opscli /var/backups/opscli-collector

sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3 \
  ".backup '/var/backups/opscli-collector/collection_storage.sqlite3.bak'"

sudo -u opscli sqlite3 \
  /var/backups/opscli-collector/collection_storage.sqlite3.bak \
  "PRAGMA integrity_check;"

sudo systemctl start opscli-collector-mcp.service
```

完整性结果必须为 `ok`。不要只复制主 SQLite 文件而遗漏活动中的 WAL 状态。

### 11.2 恢复

恢复前停止 Collector，并保留当前损坏文件作为取证副本。恢复后修正属主和权限，再执行完整性检查。

```bash
sudo systemctl stop opscli-collector-mcp.service
sudo cp /var/backups/opscli-collector/collection_storage.sqlite3.bak \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3
sudo chown opscli:opscli \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3
sudo chmod 0600 \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3

sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3 \
  "PRAGMA integrity_check;"

sudo systemctl start opscli-collector-mcp.service
```

MySQL 备份和时间点恢复由数据库平台负责。恢复 MySQL 后保持原幂等数据，并让 Outbox 自动补齐未完成任务。

## 12. 日常启停和升级

常用命令：

```bash
sudo systemctl status opscli-collector-mcp.service
sudo systemctl restart opscli-collector-mcp.service
sudo systemctl stop opscli-collector-mcp.service
sudo systemctl start opscli-collector-mcp.service
sudo journalctl -u opscli-collector-mcp.service --since "30 minutes ago"
```

升级前记录当前版本、schema 版本、Outbox 状态和运行中 SellerSprite 任务。不要在浏览器任务运行中直接强制终止服务。

普通代码升级保持 `AUTO_CREATE_SCHEMA=false`。只有发布说明明确包含 schema 升级时，才使用迁移账号执行受控迁移。

升级后依次检查 systemd、`collector_modules_health`、Outbox 状态和 MySQL 最近任务。保留上一版本安装包和配置备份。

## 13. 常见故障排查

### 13.1 服务已启动但没有 MySQL 数据

先查 `collector_modules_health` 和 Outbox。`pending` 且 `attempt_count=0` 通常表示 MySQL 或 schema 尚未 ready，Worker 还未领取任务。

依次检查：

1. 当前进程是否使用正确密码；
2. MySQL 主机和端口是否可达；
3. TLS CA 与主机名是否匹配；
4. schema 版本是否为 `collector_storage / 1`；
5. 五张表是否完整；
6. 当前账号是否可读取版本表。

数据库客户端连接成功不代表 Collector 使用了相同密码、TLS 参数和账号。应使用 Collector 所在虚拟环境执行同驱动连接探测。

### 13.2 Outbox 为 retrying

`retrying` 表示 Worker 已领取任务，但解析或 MySQL 写入失败。检查 `last_error_code`、服务日志、结果文件是否存在，以及运行账号的 DML 权限。

不要重新采集。修复文件、权限或 MySQL 后，Worker 会按退避时间继续处理。

### 13.3 任务成功但没有进入 Outbox

确认任务成功时间是否晚于生产 Outbox 的 `live_cutover_at`，并检查 `reconcile_cursor:seller_sprite` 是否推进。

cutover 之前的任务属于历史数据，不会自动进入 Outbox。cutover 之后的成功事件由实时提交或对账机制补入。

### 13.4 schema 版本表为空

版本表为空表示初始化没有完整成功。列出 `collection_%` 表，确认缺失位置，再修复 DDL、驱动、权限或凭据问题。

不要手工插入版本号。确认代码版本后重新执行幂等初始化。

### 13.5 生产启动提示缺少 SSL CA

`production` 环境必须设置有效 `OPSCLI_COLLECTOR_MYSQL_SSL_CA`。不要通过改成 `debug` 绕过生产 TLS 要求。

CA、服务端证书或域名不匹配时，应由数据库管理员修复证书链或提供正确连接域名。

## 14. 停用与回滚

只关闭数据沉淀时设置：

```ini
OPSCLI_COLLECTOR_STORAGE_ENABLED=false
```

重启 Collector 后，SellerSprite 采集仍可运行，但不会把新成功任务写入 Outbox。MySQL 数据、导出文件和现有 Outbox 不会被删除。

短期故障优先保持沉淀启用，让 Outbox 自动重试。只有确认存储模块本身造成风险时才关闭。

代码回滚步骤：

1. 停止 Collector；
2. 备份 Outbox 和当前配置；
3. 恢复上一版本安装包；
4. 保留 MySQL 表和 Outbox；
5. 保持 schema 兼容配置；
6. 启动并检查服务与 SellerSprite；
7. 确认是否重新启用沉淀。

不要在应用回滚时删除 MySQL 表。若新旧版本 schema 不兼容，应按对应发布说明执行数据库回滚。

## 15. SellerSprite 额度设置迁移

额度迁移与 MySQL 数据沉淀无关。迁移 SQL 只处理：

- `mcp_quota_policy` 中 SellerSprite 两个计次工具的基础额度；
- `mcp_quota_bonus_daily` 中 SellerSprite 邮箱日加额。

不会迁移 `mcp_quota_daily`，新服务器不会继承当天已用次数。

### 15.1 在原生产服务器导出

```bash
sqlite3 -batch -bail /var/lib/opscli/mcp_quota/quota.sqlite3 \
  < scripts/export_seller_sprite_quota_settings.sql \
  > seller-sprite-quota-settings.sql
```

导出文件包含用户邮箱，必须受控传输和保存，禁止提交 Git。

### 15.2 在新服务器导入

停止 Collector 并备份目标 quota 库：

```bash
cp /var/lib/opscli/mcp_quota/quota.sqlite3 \
  /var/lib/opscli/mcp_quota/quota.sqlite3.bak

sqlite3 -batch -bail /var/lib/opscli/mcp_quota/quota.sqlite3 \
  < seller-sprite-quota-settings.sql
```

导入会覆盖两项 SellerSprite 基础策略，并替换 SellerSprite 邮箱日加额。Keepa 等其他服务设置和每日用量不受影响。

导入后核对：

```bash
sqlite3 /var/lib/opscli/mcp_quota/quota.sqlite3 \
  "SELECT tool_name,daily_limit,enabled FROM mcp_quota_policy WHERE tool_name IN ('seller_sprite_run','seller_sprite_listing_analysis_submit') ORDER BY tool_name;"

sqlite3 /var/lib/opscli/mcp_quota/quota.sqlite3 \
  "SELECT email,bonus_daily_limit FROM mcp_quota_bonus_daily WHERE service='seller_sprite' ORDER BY email;"
```

确认后启动单实例、单 Worker 的 Collector。回滚时停止服务，恢复导入前备份，再启动。

## 16. 参数说明

| 参数 | 说明 |
|---|---|
| `--transport both` | 本地同时启用 SSE 和 Streamable HTTP |
| `--transport http` | 生产只启用 Streamable HTTP |
| `--host` | 反向代理同机时使用 `127.0.0.1` |
| `--port 8765` | OPS 通用 MCP 端口 |
| `--port 8766` | Collector MCP 端口 |
| `OPSCLI_COLLECTOR_MCP_URL` | 仅供通用 MCP 访问 Collector，不得附带共享 `api_key` |
| `OPSCLI_MCP_QUOTA_SQLITE_PATH` | Collector quota SQLite 绝对路径，生产建议显式配置 |
| `OPSCLI_COLLECTOR_STORAGE_ENABLED` | 是否启用数据沉淀，默认 `false` |
| `OPSCLI_DATA_ENVIRONMENT` | 只允许 `production` 或 `debug` |
| `OPSCLI_COLLECTOR_STORAGE_SQLITE_PATH` | Collector 独立 Outbox 路径 |
| `OPSCLI_COLLECTOR_MYSQL_HOST` | MySQL 主机；生产应与证书身份匹配 |
| `OPSCLI_COLLECTOR_MYSQL_PORT` | MySQL 端口，默认 `3306` |
| `OPSCLI_COLLECTOR_MYSQL_DATABASE` | 采集数据库名 |
| `OPSCLI_COLLECTOR_MYSQL_USER` | 迁移或运行账号 |
| `OPSCLI_COLLECTOR_MYSQL_PASSWORD` | 由 Secret 注入的密码 |
| `OPSCLI_COLLECTOR_MYSQL_SSL_CA` | 生产必填的 MySQL CA 文件 |
| `OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA` | 仅首次建表临时启用，日常必须关闭 |
| `OPSCLI_COLLECTOR_STORAGE_BATCH_SIZE` | MySQL 单批写入条数，默认 `500` |
| `OPSCLI_COLLECTOR_STORAGE_POLL_INTERVAL_SECONDS` | Outbox 轮询秒数，默认 `2` |
| `OPSCLI_COLLECTOR_STORAGE_RECONCILE_INTERVAL_SECONDS` | 成功任务对账间隔，默认 `60` 秒 |
| `OPSCLI_COLLECTOR_STORAGE_LEASE_SECONDS` | Outbox 处理租约，默认 `300` 秒 |

## 17. 安全要求

禁止在文档、Git、日志、截图、工单和命令行中暴露 API Key、Authorization、Cookie、Session、JWT、数据库密码或导出的邮箱清单。

健康检查、告警和工单只记录脱敏错误码。不要导出完整进程环境，也不要把 `/etc/opscli/collector.env` 作为普通附件上传。
