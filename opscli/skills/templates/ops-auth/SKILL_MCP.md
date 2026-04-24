---
name: ops-auth
description: 通过 opscli MCP Tools 管理 OAuth2 登录授权与 JWT Token
version: v0.0.1
---

# ops-auth（MCP 版）

通过 opscli MCP Server 的 `auth_*` Tools 完成登录、Token 管理、系统管理和认证排查。MCP 版不需要通过 subprocess 调用 `opscli auth` 命令。

## 登录工作流

1. 调用 `auth_is_authenticated()` 检查是否已登录。
2. 未登录时调用 `auth_login_start()`，向用户展示 `verification_url` 和 `user_code`。
3. 用户在浏览器完成授权后，按返回的 `interval` 调用 `auth_login_poll(device_code)`。
4. 当 `auth_login_poll` 返回 `status=authorized` 后，再次调用 `auth_is_authenticated()` 确认状态。

## Token 管理

- `auth_get_token(system="ops")`：获取指定系统 JWT，过期时自动刷新。
- `auth_check_token(system="ops")`：检查 Token 是否有效及剩余秒数。
- `auth_token_refresh(system="ops")`：强制刷新单个系统 JWT。
- `auth_token_refresh(system="__all__")`：刷新所有已注册系统 JWT。
- `auth_build_request_auth(system="ops")`：返回 `headers` 与 `cookies`，用于业务 HTTP 请求。

## 系统管理

- `auth_system_list()`：列出 builtin、local、ops_sync 系统。
- `auth_system_add(alias, url, key=None)`：添加或更新本地系统。
- `auth_system_remove(alias)`：移除本地系统，内置系统不可删除。
- `auth_system_sync()`：从 ops 后端同步系统列表。

## 认证排查

- `auth_doctor()`：返回登录状态与各系统连通性。
- `auth_logout()`：清除当前用户凭证。

## 错误处理

所有 Tool 返回统一结构：

```json
{"success": true, "data": {}, "error": null}
```

失败时先检查 `success=false`，再读取 `error.code` 与 `error.message`。不要解析 stderr，也不要直接调用后端认证接口。
