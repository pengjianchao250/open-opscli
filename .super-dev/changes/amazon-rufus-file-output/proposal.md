# amazon-rufus-file-output Proposal

## 背景

`amazon-rufus get` 现在能生成前端风格的完整答案报告，但直接写 stdout 时仍可能被 PowerShell、IDE 终端、Agent 工具返回长度或宿主输出窗口截断。单纯扩大 `RawUI.BufferSize` 不能覆盖所有运行宿主。

## 目标

- 成功时将完整答案报告写入运行目录下的 `output/amazon-rufus`。
- 文件名使用 `<ASIN>-YYYYMMDD-HHMMSS.md`，时间精确到秒。
- stdout 只输出报告保存路径，便于用户或 Agent 后续读取。
- 保留现有 `AnswerReportFormatter`，不改变 Rufus replay、parser、题库或上传 payload。

## 范围

- 调整 `amazon-rufus get` 成功输出路径。
- 新增 CLI 文件落地回归测试。
- 更新 `ops-amazon-rufus` Skill 使用说明。

## 非目标

- 不新增可配置 `--output` 参数。
- 不实现分页器、剪贴板中转或交互式查看器。
- 不改变错误路径 JSON 输出。
- 不输出 `seed_request`、`upload_payload`、headers、cookie 或完整原始 JSON。

## 验收

- 成功执行后生成 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。
- 文件内容为 formatter 生成的完整报告。
- stdout 不包含完整报告正文，只包含保存路径提示。
- 相关单元测试通过。
