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

## 参数说明

| 参数 | 说明 |
|---|---|
| `--transport both` | 本地同时启用 SSE 和 Streamable HTTP |
| `--transport http` | 生产只启用 Streamable HTTP |
| `--host` | 服务监听地址；反向代理同机时使用 `127.0.0.1` |
| `--port 8765` | OPS 通用 MCP 端口 |
| `--port 8766` | Collector MCP 端口 |
| `OPSCLI_COLLECTOR_MCP_URL` | 仅供通用 MCP 访问 Collector；CLI 不读取；不得附带共享 `api_key` |

不要在文档、日志或截图中暴露 API Key、Authorization、Cookie、Session、JWT 或账号密码。
