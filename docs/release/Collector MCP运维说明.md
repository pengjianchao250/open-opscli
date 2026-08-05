# Collector MCP 运维说明

本文是 Collector MCP 的生产部署和日常运维入口。当前只接入 SellerSprite；Keepa 不使用本文的 MySQL 配置。

## 1. 服务边界与本地启动

客户端只访问 OPS 通用 MCP。通用 MCP 通过内网 `OPSCLI_COLLECTOR_MCP_URL` 调用 Collector。

```text
MCP Host / opscli seller-sprite
  -> OPS 通用 MCP :8765
  -> Collector MCP :8766
  -> SellerSprite -> Outbox -> MySQL
```

Collector 必须保持单实例、单 Worker。不要让多个实例写同一 SellerSprite 状态目录或 Outbox。

Windows 本地启动 Collector：

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

本地与生产可以共用 MySQL，通过 `debug` 和 `production` 区分数据，但必须使用独立 Outbox。

## 2. 生产准备

部署前确认：

- `/opt/opscli/venv` 已安装目标版本；
- 已创建服务用户 `opscli`；
- SellerSprite 状态目录和浏览器 Profile 可写；
- OPS、SellerSprite、MySQL、对象存储和 DNS 可达；
- 如需验证 MySQL TLS，已取得 CA 和证书匹配的内网域名；
- 只部署一个 Collector 实例。

创建目录：

```bash
sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/.config/opscli/collector
sudo install -d -m 0700 -o opscli -g opscli \
  /var/lib/opscli/mcp_quota
sudo install -d -m 0750 -o root -g opscli /etc/opscli
```

生产 Outbox 路径：

```text
/var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3
```

Outbox 保存待入库状态、重试租约和对账游标。不要删除，也不要与 SellerSprite `task_queue.sqlite3` 共用文件。

MySQL 推荐使用两个账号：迁移账号负责建表，运行账号只授予 `SELECT, INSERT, UPDATE, DELETE`。

## 3. 生产环境配置

创建 `/etc/opscli/collector.env`：

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
# OPSCLI_COLLECTOR_MYSQL_SSL_CA=/etc/opscli/mysql-ca.pem

OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA=false
```

主机、账号和密码必须替换。`OPSCLI_COLLECTOR_MYSQL_SSL_CA` 可选；配置后会验证 MySQL 服务端证书和主机身份，并应使用证书匹配的域名。未配置时不启用 TLS 验证，仅适用于受控内网数据库。

密码由部署平台或 Secret 管理器注入，不得提交 Git、写入镜像、命令行或日志。

```bash
sudo chown root:opscli /etc/opscli/collector.env
sudo chmod 0640 /etc/opscli/collector.env
```

配置 CA 时，再将证书设为 `root:opscli`、权限设为 `0640`。

Collector 只读取进程环境变量，不会自动加载项目 `.env` 或 `config.ini` 中的 MySQL 配置。

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

通用 MCP 配置 Collector 地址：

```ini
OPSCLI_COLLECTOR_MCP_URL=https://collector-mcp.internal.example.com/mcp
```

同机时可使用 `http://127.0.0.1:8766/mcp`。URL 不得携带共享 `api_key`。

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

本地和生产共用同一个 MySQL 时，只初始化一次。生产保持：

```ini
OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA=false
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
OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA=true
```

启动 Collector，确认五张表和版本行存在。随后停止服务，切换运行账号，并将配置恢复为 `false`。

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

检查 Outbox：

```bash
sudo -u opscli sqlite3 \
  /var/lib/opscli/.config/opscli/collector/collection_storage.sqlite3 \
  "SELECT status,COUNT(*) FROM collection_outbox GROUP BY status;"
```

MySQL 故障不会重新采集。恢复后，`pending` 和 `retrying` 会自动继续处理。

生产 Outbox 首次启用时记录 `live_cutover_at`。自动对账只覆盖该时间之后的成功任务，更早的历史生产数据暂不自动迁移。

原始文件不写入 MySQL BLOB。MySQL 只登记 URI、文件属性和 SHA-256；格式化 Dataset 按行写入 JSON。

## 7. 备份与日常操作

Outbox 包含未完成任务和对账边界，必须纳入备份。最稳妥的方式是停止服务后使用 SQLite `.backup`：

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

数据库客户端连接成功不代表 Collector 使用了相同密码、TLS 和账号。必要时使用 Collector 虚拟环境执行同驱动连接测试。

不要为了排障重新采集；修复 MySQL、文件或权限后让 Outbox 自动重试。

只关闭数据沉淀：

```ini
OPSCLI_COLLECTOR_STORAGE_ENABLED=false
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
| `OPSCLI_COLLECTOR_STORAGE_BATCH_SIZE` | `500` |
| `OPSCLI_COLLECTOR_STORAGE_POLL_INTERVAL_SECONDS` | `2` 秒 |
| `OPSCLI_COLLECTOR_STORAGE_RECONCILE_INTERVAL_SECONDS` | `60` 秒 |
| `OPSCLI_COLLECTOR_STORAGE_LEASE_SECONDS` | `300` 秒 |

禁止在文档、Git、日志、截图和工单中暴露 API Key、Cookie、Session、JWT、数据库密码或导出的邮箱清单。
