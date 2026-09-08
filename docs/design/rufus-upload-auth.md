# Rufus 报告上传鉴权

## MCP

与 ASIN Data 的上传方式统一：

```text
amazon_rufus_get
  -> 工作线程内 _get_auth_pair("ops")
  -> RufusMcpManager.for_current_request(credential_dir, jwt, session_id)
  -> FileUploadClient(auth_client=当前请求客户端, jwt=jwt, session_id=session_id)
  -> POST /v1/file/upload
```

- 凭证来自现有 API Key/客户端隔离目录；不新增凭证存储或登录机制。
- session 与 JWT 同时存在：显式携带 Bearer 和 session Cookie。
- 只有 session：公共上传客户端用 session 换取 OPS JWT。
- 只有 JWT：携带 Bearer；都没有时继续使用公共客户端的 API Key 或 AuthClient 分支。
- 公开 MCP 参数不增加 jwt/session_id，不把凭证放入业务参数、返回值或反馈摘要。
- 仅获取并上传报告时解析凭证；本地授权偏好等操作不读取上传 JWT。

## CLI

保持与 ASIN Data CLI 相同的 `FileUploadClient()` 用法，由公共客户端的
`AuthClient.build_request_auth("ops")` 读取当前登录态或显式凭证上下文。
不新增 JWT 参数，不改变共享上传客户端的鉴权优先级。

## 验证

mock 覆盖工厂参数、工作线程执行、请求头与 Cookie、session 换取 JWT、API Key 回退、
本地偏好操作及 CLI 原有流程；不调用真实网络或真实凭证存储。
