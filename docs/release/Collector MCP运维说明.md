# Collector MCP 运维说明

## 本地启动（Windows）

终端一，启动 Collector MCP：

```powershell
.\.venv\Scripts\python.exe -m opscli.collector_mcp.server `
  --transport both `
  --host 127.0.0.1 `
  --port 8766
```

终端二，启动 OPS 通用 MCP：

```powershell
$env:OPSCLI_COLLECTOR_MCP_URL="http://127.0.0.1:8766/mcp"

.\.venv\Scripts\python.exe -m opscli.mcp.server `
  --transport both `
  --host 127.0.0.1 `
  --port 8765
```

MCP Host 只配置 OPS 通用 MCP 的 `8765` 端口，由通用 MCP 静默访问 Collector 的 `8766` 端口。`opscli seller-sprite` 也从 OPS 配置接口获取通用 MCP 地址，不需要知道 Collector 地址。关闭 Collector 后，卖家精灵调用应返回 `COLLECTOR_MCP_UNAVAILABLE`，不会回退到通用 MCP 本地执行。

## 生产启动（Linux）

生产环境将 Windows 虚拟环境路径替换为实际 Linux 安装路径，并将 Collector URL 改为内网域名或内网 IP：

```bash
/opt/opscli/venv/bin/opscli-collector-mcp \
  --transport http \
  --host 127.0.0.1 \
  --port 8766
```

```bash
export OPSCLI_COLLECTOR_MCP_URL="https://collector-mcp.internal.example.com/mcp"

/opt/opscli/venv/bin/opscli-mcp \
  --transport http \
  --host 127.0.0.1 \
  --port 8765
```

生产建议使用 systemd 管理进程；Collector 保持单实例、单 Worker，不允许多个实例写同一 SellerSprite 状态目录。

## SellerSprite 额度设置迁移

迁移 SQL 只处理以下设置：

- `mcp_quota_policy` 中 `seller_sprite_run` 和 `seller_sprite_listing_analysis_submit` 的基础额度；
- `mcp_quota_bonus_daily` 中 SellerSprite 邮箱日加额。

不会迁移 `mcp_quota_daily`，因此新服务器不会继承生产服务器当天已用次数。

### 1. 在生产服务器导出 SQL

```bash
sqlite3 -batch -bail /var/lib/opscli/mcp_quota/quota.sqlite3 \
  < scripts/export_seller_sprite_quota_settings.sql \
  > seller-sprite-quota-settings.sql
```

生成的 `seller-sprite-quota-settings.sql` 包含用户邮箱，必须通过受控方式传输和保存，禁止提交 Git。

### 2. 在新服务器导入 SQL

先停止 Collector MCP 并备份目标库，然后直接导入：

```bash
cp /var/lib/opscli/mcp_quota/quota.sqlite3 \
  /var/lib/opscli/mcp_quota/quota.sqlite3.bak

sqlite3 -batch -bail /var/lib/opscli/mcp_quota/quota.sqlite3 \
  < seller-sprite-quota-settings.sql
```

导入会覆盖两项 SellerSprite 基础策略，并完整替换 SellerSprite 邮箱日加额；Keepa 等其他服务设置和每日用量不受影响。

导入后核对：

```bash
sqlite3 /var/lib/opscli/mcp_quota/quota.sqlite3 \
  "SELECT tool_name,daily_limit,enabled FROM mcp_quota_policy WHERE tool_name IN ('seller_sprite_run','seller_sprite_listing_analysis_submit') ORDER BY tool_name;"

sqlite3 /var/lib/opscli/mcp_quota/quota.sqlite3 \
  "SELECT email,bonus_daily_limit FROM mcp_quota_bonus_daily WHERE service='seller_sprite' ORDER BY email;"
```

确认结果后再启动单实例、单 Worker 的 Collector MCP。若需回滚，停止 Collector，将导入前备份恢复为 `quota.sqlite3` 后再启动。

## 参数说明

| 参数 | 说明 |
|---|---|
| `--transport both` | 本地同时启用 SSE 和 Streamable HTTP |
| `--transport http` | 生产只启用 Streamable HTTP |
| `--host` | 服务监听地址；反向代理同机时使用 `127.0.0.1` |
| `--port 8765` | OPS 通用 MCP 端口 |
| `--port 8766` | Collector MCP 端口 |
| `OPSCLI_COLLECTOR_MCP_URL` | 仅供通用 MCP 访问 Collector；CLI 不读取；不得附带共享 `api_key` |
| `OPSCLI_MCP_QUOTA_SQLITE_PATH` | Collector 使用的 quota SQLite 绝对路径；生产环境建议显式配置 |

不要在文档、日志或截图中暴露 API Key、Authorization、Cookie、Session、JWT、账号密码或导出的邮箱清单。
