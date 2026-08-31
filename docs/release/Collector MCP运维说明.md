# Collector MCP 运维说明

本文是 Collector MCP 的生产部署和采集数据沉淀运维入口。Collector MCP 与通用 MCP 部署在不同服务器。SellerSprite 与 Keepa 复用相同的存储实现和 MySQL 表合同，但不共享进程 Runtime、SQLite 文件、本地目录或环境文件。

## 1. 服务边界与本地启动

客户端只访问 OPS 通用 MCP。SellerSprite 由通用 MCP 通过 `OPSCLI_COLLECTOR_MCP_URL` 转发到 Collector；Keepa 仍在通用 MCP 本地执行。

```text
客户端
  -> 通用 MCP 服务器 :8765
       -> Keepa -> 本机 mcp.sqlite3 Outbox -> 统一 MySQL
       -> SellerSprite Proxy
            -> Collector MCP 服务器 :8766
                 -> SellerSprite -> 本机 collector.sqlite3 Outbox -> 统一 MySQL
```

两个 MCP 宿主各自维护一个 Worker 和 Outbox。通用 MCP 服务器不挂载 Collector 的本地目录，Collector 服务器也不挂载 Keepa 输出目录。不要通过 NFS、SMB、文件同步或定时复制共享运行中的 SQLite；`mcp.sqlite3` 与 `collector.sqlite3` 不得互换或合并。

以下 Windows 双终端示例仅用于单机开发，不代表生产部署拓扑。先启动 Collector：

```powershell
.\.venv\Scripts\python.exe -m opscli.collector_mcp.server `
  --transport both `
  --host 127.0.0.1 `
  --port 8766
```

另一个终端启动通用 MCP：

```powershell
$env:OPSCLI_COLLECTOR_MCP_URL="http://127.0.0.1:8766/mcp"

.\.venv\Scripts\python.exe -m opscli.mcp.server `
  --transport both `
  --host 127.0.0.1 `
  --port 8765
```

当前内网测试库只用于 `debug` 联调。两台服务器分别设置 MySQL 环境变量并指向同一个测试 schema；只有两台服务器都具备该内网数据库的路由和 DNS 能力时才能联调。未来统一数据库上线时，分别替换两台服务器的连接、Secret 和 CA 配置。

## 2. 生产准备

两台服务器都需确认 `/opt/opscli/venv` 已安装目标版本、服务用户 `opscli` 已创建，并且各自能够访问 OPS、统一 MySQL、对象存储和 DNS。除此之外：

- 通用 MCP 服务器：Keepa 输出目录和 `mcp.sqlite3` 目录可写，能够访问 Keepa 和 Collector MCP 地址；
- Collector 服务器：SellerSprite 状态目录、浏览器 Profile、额度库和 `collector.sqlite3` 目录可写，能够访问 SellerSprite；
- 两台服务器分别取得所需 CA，并使用证书匹配的数据库域名；
- 每台服务器只部署一个对应 MCP 实例，除非先将其本地队列与文件状态改造成多实例安全存储。

在两台服务器上分别创建各自需要的目录。通用 MCP 服务器创建：

```bash
sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/.config/opscli/collection_storage
sudo install -d -m 0750 -o root -g opscli /etc/opscli
```

Collector 服务器创建：

```bash
sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/.config/opscli/collection_storage
sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/mcp_quota
sudo install -d -m 0750 -o root -g opscli /etc/opscli
```

生产 Outbox 路径分别为：

```text
通用 MCP 服务器：/var/lib/opscli/.config/opscli/collection_storage/mcp.sqlite3
Collector 服务器：/var/lib/opscli/.config/opscli/collection_storage/collector.sqlite3
```

Outbox 保存待入库状态、重试租约和对账游标。不要删除，也不要与 SellerSprite `task_queue.sqlite3` 共用文件。

MySQL 推荐使用一个迁移账号负责建表，并为通用 MCP、Collector MCP 分别创建可审计的运行账号；两个运行账号都只授予 `SELECT, INSERT, UPDATE, DELETE`。

## 3. 生产环境配置

当前内网测试库联调必须使用 `debug`。以下变量需要分别写入两台服务器各自的环境文件，数据库地址和 schema 相同，账号可以不同；`SQLITE_DIR` 始终指向当前服务器本地磁盘：

```ini
OPSCLI_COLLECTION_STORAGE_ENABLED=true
OPSCLI_DATA_ENVIRONMENT=debug
OPSCLI_COLLECTION_STORAGE_SQLITE_DIR=C:\opscli-test\collection_storage
OPSCLI_COLLECTION_MYSQL_HOST=<内网测试库主机>
OPSCLI_COLLECTION_MYSQL_PORT=3306
OPSCLI_COLLECTION_MYSQL_DATABASE=<测试库名>
OPSCLI_COLLECTION_MYSQL_USER=<测试运行账号>
OPSCLI_COLLECTION_MYSQL_PASSWORD=<由 Secret 注入>
OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA=false
```

测试库未配置 CA 仅适用于受控内网。后续统一数据库可被内外网访问时，必须使用证书域名并配置 `OPSCLI_COLLECTION_MYSQL_SSL_CA`，同时把环境切换为 `production`。

### 3.1 Collector 服务器

创建 `/etc/opscli/collector.env`：

```ini
OPSCLI_COLLECTION_STORAGE_ENABLED=true
OPSCLI_DATA_ENVIRONMENT=production
OPSCLI_MCP_QUOTA_SQLITE_PATH=/var/lib/opscli/mcp_quota/quota.sqlite3
OPSCLI_COLLECTION_STORAGE_SQLITE_DIR=/var/lib/opscli/.config/opscli/collection_storage

OPSCLI_COLLECTION_MYSQL_HOST=mysql.internal.example.com
OPSCLI_COLLECTION_MYSQL_PORT=3306
OPSCLI_COLLECTION_MYSQL_DATABASE=polaris_ops_mcp
OPSCLI_COLLECTION_MYSQL_USER=collector_writer
OPSCLI_COLLECTION_MYSQL_PASSWORD="由部署 Secret 注入"
# OPSCLI_COLLECTION_MYSQL_SSL_CA=/etc/opscli/mysql-ca.pem

OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA=false
```

### 3.2 通用 MCP 服务器

在通用 MCP 服务器创建 `/etc/opscli/mcp.env`。数据环境、MySQL 地址、端口、schema、CA 和自动建表设置与 Collector 一致，但使用通用 MCP 自己的 Secret 和本地目录：

```ini
OPSCLI_COLLECTION_STORAGE_ENABLED=true
OPSCLI_DATA_ENVIRONMENT=production
OPSCLI_COLLECTION_STORAGE_SQLITE_DIR=/var/lib/opscli/.config/opscli/collection_storage

OPSCLI_COLLECTION_MYSQL_HOST=mysql.internal.example.com
OPSCLI_COLLECTION_MYSQL_PORT=3306
OPSCLI_COLLECTION_MYSQL_DATABASE=polaris_ops_mcp
OPSCLI_COLLECTION_MYSQL_USER=mcp_writer
OPSCLI_COLLECTION_MYSQL_PASSWORD="由部署 Secret 注入"
# OPSCLI_COLLECTION_MYSQL_SSL_CA=/etc/opscli/mysql-ca.pem

OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA=false
OPSCLI_COLLECTOR_MCP_URL=https://collector-mcp.internal.example.com/mcp
```

两台服务器上的主机、账号和密码必须分别替换。`OPSCLI_COLLECTION_MYSQL_SSL_CA` 可选；配置后会验证 MySQL 服务端证书和主机身份，并应使用证书匹配的域名。未配置时不启用 TLS 验证，仅适用于受控内网数据库。

密码由部署平台或 Secret 管理器注入，不得提交 Git、写入镜像、命令行或日志。

在 Collector 服务器执行：

```bash
sudo chown root:opscli /etc/opscli/collector.env
sudo chmod 0640 /etc/opscli/collector.env
```

在通用 MCP 服务器执行：

```bash
sudo chown root:opscli /etc/opscli/mcp.env
sudo chmod 0640 /etc/opscli/mcp.env
```

配置 CA 时，再将证书设为 `root:opscli`、权限设为 `0640`。

Collector MCP 与通用 MCP 都只读取各自进程的环境变量，不会自动加载项目 `.env` 或 `config.ini` 中的 MySQL 配置。两个环境文件必须保持 `OPSCLI_DATA_ENVIRONMENT`、MySQL endpoint、database 和 schema 版本一致，但文件与 Secret 彼此独立。

## 4. systemd 部署

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

替换示例 OPS 验证地址。增加 systemd 沙箱限制前，应使用 `opscli` 用户完成真实 SellerSprite 浏览器任务验证。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opscli-collector-mcp.service
sudo systemctl status opscli-collector-mcp.service
```

通用 MCP 的既有 systemd unit 必须加载本机 `/etc/opscli/mcp.env`，不得加载 Collector 服务器的环境文件：

```ini
[Service]
EnvironmentFile=/etc/opscli/mcp.env
```

生产环境的 `OPSCLI_COLLECTOR_MCP_URL` 必须使用通用 MCP 服务器能够访问的 Collector 内网域名；`http://127.0.0.1:8766/mcp` 只允许单机开发。URL 不得携带共享 `api_key`。

## 5. MySQL schema 初始化

当前 schema 版本为 `1`，包含：

```text
collection_schema_versions
collection_runs
collection_artifacts
collection_datasets
collection_records
```

### 5.1 共享数据库已经初始化

两台 MCP 服务器指向同一个 MySQL schema 时，只初始化一次。两边生产配置都保持：

```ini
OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA=false
```

```sql
SELECT module_name, schema_version, updated_at
FROM collection_schema_versions
WHERE module_name = 'collector_storage';
```

结果应为 `collector_storage / 1`。部署到新服务器不等于需要重新初始化数据库。

### 5.2 全新空库

仅全新空库使用迁移账号，并临时设置：

```ini
OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA=true
```

选择一台受控服务器使用迁移账号启动一次 Collector，确认五张表和版本行存在。随后停止服务，切换运行账号，并将配置恢复为 `false`；不要让两台服务器同时执行初始化。

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name LIKE 'collection_%'
ORDER BY table_name;

SELECT * FROM collection_schema_versions;
```

MySQL DDL 会自动提交。若只创建部分表，不要删除表或手工插入版本号；修复原因后重新执行幂等初始化。

若缺少 `collection_records`，确认部署代码使用 `source_row_number`，而不是 MySQL 8 保留字 `row_number`。

## 6. 验收与数据边界

使用已认证 MCP 客户端调用 `collector_modules_health`：

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

查看最近入库任务：

```sql
SELECT
    id, data_environment, source_system, source_job_id,
    scenario, source_row_count, persistence_completed_at
FROM collection_runs
ORDER BY id DESC
LIMIT 20;
```

生产任务必须为 `production`，本地任务为 `debug`。幂等键为：

```text
(data_environment, source_system, source_job_id)
```

在 Collector 服务器检查 SellerSprite Outbox：

```bash
sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collection_storage/collector.sqlite3 \
  "SELECT status,COUNT(*) FROM collection_outbox GROUP BY status;"
```

在通用 MCP 服务器检查 Keepa Outbox：

```bash
sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collection_storage/mcp.sqlite3 \
  "SELECT status,COUNT(*) FROM collection_outbox GROUP BY status;"
```

MySQL 故障不会重新采集。恢复后，`pending` 和 `retrying` 会自动继续处理。

生产 Outbox 首次启用时记录 `live_cutover_at`。自动对账只覆盖该时间之后的成功任务，更早的历史生产数据暂不自动迁移。

原始文件不写入 MySQL BLOB。MySQL 只登记 URI、文件属性和 SHA-256；格式化 Dataset 按行写入 JSON。`file://` URI 只表示 `producer_service` 对应服务器上的本地诊断路径，另一台 MCP 服务器和数据库消费者不得把它当作可访问的共享文件地址；跨服务器交付使用对象存储 HTTPS URL。

## 7. 备份与日常操作

Outbox 包含未完成任务和对账边界，必须纳入备份。最稳妥的方式是停止服务后使用 SQLite `.backup`：

```bash
sudo systemctl stop opscli-collector-mcp.service
sudo install -d -m 0700 -o opscli -g opscli /var/backups/opscli-collector
sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collection_storage/collector.sqlite3 \
  ".backup '/var/backups/opscli-collector/collector.sqlite3.bak'"
sudo -u opscli sqlite3 \
  /var/backups/opscli-collector/collector.sqlite3.bak \
  "PRAGMA integrity_check;"
sudo systemctl start opscli-collector-mcp.service
```

通用 MCP 的 `mcp.sqlite3` 必须登录通用 MCP 服务器、停止通用 MCP 后，以相同方式单独备份。备份文件按服务器分别保管，不能用任一文件覆盖另一个宿主的 Outbox。

完整性结果必须为 `ok`。恢复时停止服务、替换数据库文件、修正 `opscli:opscli` 属主和 `0600` 权限，再执行完整性检查。

常用命令：

```bash
sudo systemctl status opscli-collector-mcp.service
sudo systemctl restart opscli-collector-mcp.service
sudo journalctl -u opscli-collector-mcp.service --since "30 minutes ago"
```

升级前记录服务版本、schema 版本、Outbox 状态和运行中任务。普通升级保持 `AUTO_CREATE_SCHEMA=false`。

## 8. 故障排查与回滚

| 现象 | 判断与处理 |
|---|---|
| `pending` 且 `attempt_count=0` | MySQL 或 schema 未 ready；检查密码、TLS、版本行和五张表 |
| `retrying` | Worker 已领取但解析或写库失败；检查 `last_error_code`、文件和 DML 权限 |
| 任务成功但无 Outbox | 检查成功时间是否晚于 `live_cutover_at`，以及对账游标是否推进 |
| 版本表为空 | 初始化不完整；列出已有表，修复原因后重新初始化 |
| 配置 CA 后连接失败 | 检查 CA 路径、读取权限和证书域名；当前内网不使用 CA 时不要配置无效路径 |

一台服务器上的数据库客户端连接成功不代表另一台服务器也具备相同路由、DNS、CA 或账号权限。必须分别使用两台服务器上的 opscli 虚拟环境执行同驱动连接测试。

不要为了排障重新采集；修复 MySQL、文件或权限后让 Outbox 自动重试。

只关闭数据沉淀：

```ini
OPSCLI_COLLECTION_STORAGE_ENABLED=false
```

关闭不会删除 MySQL、文件或 Outbox。代码回滚时先停止服务并备份 Outbox，恢复上一版本后保留现有表，不要直接删除 MySQL schema。

## 9. SellerSprite 额度迁移

额度迁移与 MySQL 沉淀无关，只迁移 SellerSprite 基础额度和邮箱日加额，不迁移当天已用次数。

原服务器导出：

```bash
sqlite3 -batch -bail /var/lib/opscli/mcp_quota/quota.sqlite3 \
  < scripts/export_seller_sprite_quota_settings.sql \
  > seller-sprite-quota-settings.sql
```

停止新 Collector，备份目标 quota 库后导入：

```bash
cp /var/lib/opscli/mcp_quota/quota.sqlite3 \
  /var/lib/opscli/mcp_quota/quota.sqlite3.bak
sqlite3 -batch -bail /var/lib/opscli/mcp_quota/quota.sqlite3 \
  < seller-sprite-quota-settings.sql
```

导出文件包含用户邮箱，必须受控传输，禁止提交 Git。回滚时停止服务并恢复导入前备份。

## 10. 可选调优参数

| 参数 | 默认值 |
|---|---:|
| `OPSCLI_COLLECTION_STORAGE_BATCH_SIZE` | `500` |
| `OPSCLI_COLLECTION_STORAGE_POLL_INTERVAL_SECONDS` | `2` 秒 |
| `OPSCLI_COLLECTION_STORAGE_RECONCILE_INTERVAL_SECONDS` | `60` 秒 |
| `OPSCLI_COLLECTION_STORAGE_LEASE_SECONDS` | `300` 秒 |

禁止在文档、Git、日志、截图和工单中暴露 API Key、Cookie、Session、JWT、数据库密码或导出的邮箱清单。
