# Amazon Rufus Artifact Upload Proposal

## 背景

`opscli amazon-rufus get-backend` 和 MCP `amazon_rufus_get` 当前只把 Rufus Markdown 报告写入本地，并返回 `report_path`。用户需要报告生成后自动上传到现有文件服务，并返回报告地址。

现有 `/v1/rufus/upload` 上传的是 Rufus 业务 JSON，不是文件。新流程必须复用 `opscli.shared.file_uploads.FileUploadClient` 对接 `/v1/file/upload`。

## 目标

- CLI `get-backend` 生成报告后自动上传，并输出 `report_path` 和 `report_url`。
- MCP `amazon_rufus_get` 返回 `report_path` 和 `report_url`。
- Skill 继续读取 `report_path` 做质量判断，最终返回最新 `report_url`。
- `--no-upload-payload` 只关闭旧 Rufus payload，不影响报告上传。
- 上传失败时保留本地报告，但调用返回失败，不使用历史 URL。

## 非目标

- 不修改 `/v1/rufus/upload` 和 `--submit-upload` 语义。
- 不修改 Markdown 报告正文格式；文件名只追加 UUID，修复同秒并发覆盖。
- 不给 `batch-get-backend` 或 `asin-data` 增加自动上传。
- 不增加 OSS SDK、上传开关、历史补传或重传命令。
- 不执行真实远程上传测试。

## 设计

新增 `AnswerReportPublisher`，统一执行：

```text
AnswerReportWriter.write(data)
  -> FileUploadClient.upload(report_path)
  -> PublishedAnswerReport(path, url)
```

上传参数：

```text
purpose=amazon_rufus_report
folder=amazon-rufus/reports
filename=<report_path.name>
metadata=asin,country,question_count,answer_count,format
```

不显式传 `public`，沿用 `FileUploadClient` 配置。metadata 不包含问题、回答、登录态、请求种子、payload 或认证材料。

CLI 保留原路径输出并增加：

```text
Rufus 答案报告地址：<report_url>
```

MCP 成功数据增加 `report_url`，`next_action` 指示调用方读取 `report_path` 做质量判断，最终返回 `report_url`。

## 错误处理

新增 `RufusReportUploadError`，错误码为 `RUFUS_REPORT_UPLOAD_ERROR`。它保留本地 `report_path`，不暴露文件接口原始响应和认证信息。

文件上传失败后不重新执行 Rufus 获取。CLI 退出码非零；MCP 返回标准错误结构。

## 安全边界

- MCP 上传客户端复用当前请求的 `AuthClient`，保持凭证隔离。
- MCP 继续强制 `include_upload_payload=False`。
- 不返回 `FileUploadResult.raw`。
- 只上传本次 writer 返回的路径，不扫描历史目录。
- `report_path` 与 `report_url` 在重试时成对替换。
- 文件名使用 `<ASIN>-YYYYMMDD-HHMMSS-<UUID>.md`，避免同一 ASIN 并发请求写入同一路径。

## 验收

- CLI 带 `--no-upload-payload` 仍上传 Markdown。
- CLI 成功输出路径和 URL。
- MCP 成功返回路径和 URL。
- Skill 最终输出最新 URL。
- 上传失败时本地文件存在，CLI/MCP 返回失败。
- 同一 ASIN 同一秒并发发布时，路径和上传内容互相隔离。
- Rufus、MCP、Skill 相关目标测试全部通过。
