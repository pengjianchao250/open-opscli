---
name: ops-mcp
description: 管理 opscli MCP Server 启动、用户和接入配置
version: v0.0.1
---

# ops-mcp

管理 opscli MCP Server 的启动方式、多用户 API Key 和 AI 工具接入配置。所有管理动作通过 `opscli mcp` 与 `opscli-mcp` 命令完成。

## 启动服务

```bash
# stdio 单用户模式
opscli-mcp

# SSE 单用户模式
opscli-mcp --transport sse --host 127.0.0.1 --port 8765

# stdio 多用户模式
OPSCLI_MCP_API_KEY=<api_key> opscli-mcp --multi-user

# SSE 多用户模式
opscli-mcp --transport sse --host 127.0.0.1 --port 8765 --multi-user --require-auth
```

## 用户管理

```bash
# 查看 MCP 用户
opscli mcp user list --pretty

# 创建 MCP 用户，API Key 只显示一次
opscli mcp user add --desc "张三的工作站" --pretty

# 轮换 API Key
opscli mcp user rotate --id <user_id> --pretty

# 删除用户及其凭证目录
opscli mcp user remove --id <user_id>

# 删除用户但保留凭证目录
opscli mcp user remove --id <user_id> --keep-credentials
```

## Claude Desktop stdio 配置

```json
{
  "mcpServers": {
    "opscli": {
      "command": "opscli-mcp",
      "args": ["--multi-user"],
      "env": {
        "OPSCLI_MCP_API_KEY": "opscli-mcp-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

## SSE 接入

SSE 地址：

```text
http://127.0.0.1:8765/sse
```

多用户 SSE 模式必须携带请求头：

```http
Authorization: Bearer opscli-mcp-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 故障排查

- `opscli mcp user list --pretty`：确认用户是否存在。
- `opscli-mcp --transport sse --port 8765`：先用单用户模式验证服务是否能启动。
- `lsof -i :8765`：检查端口占用。
- `auth_is_authenticated()`：确认当前 API Key 对应用户是否已登录。
