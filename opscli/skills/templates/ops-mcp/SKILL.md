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

## 登录与 Session 互通

MCP 的授权流程与 CLI **共用同一套 CredentialStore**，登录后 CLI 立即可用：

```
auth_login_start() → 返回 {verification_url, user_code, device_code}
  → 用户在浏览器打开 URL 并输入 user_code
  → auth_login_poll(device_code) → 返回 {status: "authorized", session_id}
  → session_id 自动保存到 CredentialStore（与 CLI 共用）
  → 后续 Tool 调用可直接读取，无需重复登录
```

**与 CLI 的区别**：
- CLI：`opscli auth login` 阻塞式单命令完成全流程
- MCP：`auth_login_start` + `auth_login_poll` 分步非阻塞调用
- 两者底层存储统一，登录态完全互通

## 故障排查

- `opscli mcp user list --pretty`：确认用户是否存在。
- `opscli-mcp --transport sse --port 8765`：先用单用户模式验证服务是否能启动。
- `lsof -i :8765`：检查端口占用。
- `auth_is_authenticated()`：确认当前 API Key 对应用户是否已登录。
