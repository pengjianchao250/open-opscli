# Amazon Rufus Artifact Upload Tasks

## Tasks

- [x] 新增 `AnswerReportPublisher`、`PublishedAnswerReport` 和上传失败领域错误。
- [x] 为发布服务补写入、上传参数、成功结果和失败保留文件测试。
- [x] CLI `get-backend` 接入发布服务，输出 `report_path` 与 `report_url`。
- [x] 增加 `--no-upload-payload` 仍上传报告及上传失败测试。
- [x] MCP Manager 注入请求级上传客户端并返回 `report_url`。
- [x] MCP Tool 文档和返回契约同步 `report_url`。
- [x] 更新 MCP Manager、MCP Tool 与凭证隔离测试。
- [x] 更新模板 Skill、安装副本、README 和 Rufus 工作流引用。
- [x] 更新 Skill 新鲜度测试，要求路径和 URL 成对更新。
- [x] 为发布流程启用 UUID 文件名，并验证同一 ASIN 同一秒并发内容隔离。
- [x] 运行目标 pytest、`compileall`、Skill 哈希和最终 Diff 检查。
- [x] 保持现有脏工作区文件不变，不提交、不推送、不执行真实远程上传。
- [x] 删除并发测试误生成的 4 个 `B0TEST1234-...-UUID.md` 文件，真实 Rufus 产物保持不变。
