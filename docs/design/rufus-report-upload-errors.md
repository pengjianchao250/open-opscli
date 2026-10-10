# Rufus 报告上传错误契约

CLI `amazon-rufus get-backend` 与 MCP `amazon_rufus_get` 共用发布服务。
上传失败继续返回 `RUFUS_REPORT_UPLOAD_ERROR`，不返回 `report_url`。`report_path` 按调用方能否读取区分：

- CLI 与本地 stdio MCP：保留本地报告并返回 `report_path`（stdio MCP 为本机绝对路径），文案为「已保留本地文件」。
- 远端 HTTP/SSE MCP：报告只在 MCP 服务器上，调用方读不到，错误结构不含 `report_path`，服务端路径只写服务端日志（Bug 12138）。

## 返回示例

CLI / 本地 stdio MCP：

```json
{
  "code": "RUFUS_REPORT_UPLOAD_ERROR",
  "message": "Rufus 报告上传失败，已保留本地文件",
  "report_path": "output/amazon-rufus/report.md",
  "upload_error": {
    "type": "FileUploadHttpError",
    "code": "FILE_UPLOAD_HTTP_ERROR",
    "http_status": 403,
    "business_code": "UPLOAD_DENIED",
    "message": "没有文件上传权限"
  }
}
```

远端 HTTP/SSE MCP（`upload_error` 结构同上）：

```json
{
  "code": "RUFUS_REPORT_UPLOAD_ERROR",
  "message": "Rufus 报告上传失败，报告只保存在远端 MCP 服务器上，调用方无法读取，请稍后重试获取",
  "upload_error": {"type": "FileUploadHttpError", "code": "FILE_UPLOAD_HTTP_ERROR", "http_status": 403, "business_code": "UPLOAD_DENIED", "message": "没有文件上传权限"}
}
```

## 字段与安全边界

- `type`：底层异常类型；网络错误经过重试包装后仍保留其类型。
- `code`：文件上传客户端定义的错误码，没有时为 `null`。
- `http_status`：服务端 HTTP 状态码；无 HTTP 响应时为 `null`，不从自由文本猜测。
- `business_code`：响应的业务码；只接受有限长度的标识符或整数，疑似凭证及其他异常值为 `null`。
- `message`：已知上传错误保留简短原因；疑似凭证、签名 URL、结构化响应或请求转储整体隐藏。
- 超时、网络、鉴权和未知异常使用固定摘要，不公开原始异常文本。
- 不返回响应正文、请求头、Cookie、认证凭证或 Python traceback；原异常链留在进程内。
- 共享上传异常统一过滤消息和业务码，避免其他模块直接序列化异常时泄漏远端敏感信息。
- HTML/非对象错误响应仍保留 HTTP 状态码；重试耗尽时解析最后一次响应。

## 验证

使用 mock 覆盖 CLI、MCP、403、业务失败、非 JSON 响应、重试耗尽、网络异常、认证失败及敏感消息。
本次验证不调用真实接口，不读取真实凭证，不修改数据库。

2026-09-07 定点回归：78 passed；包含两项审查复现（凭证样式业务码、503 重试耗尽后的响应消息泄漏）。
