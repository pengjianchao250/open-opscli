# amazon-rufus answers text proposal

## 背景

`ops-amazon-rufus` 在 Agent 使用场景中只需要 Rufus 回答文本。用户明确要求去掉额外参数，命令执行完成后不输出完整 JSON，只输出 `answers[].text`。

## 目标

1. PowerShell 使用示例统一在当前命令会话启用 UTF-8。
2. `opscli amazon-rufus get` 成功后默认只输出 `answers[].text`。
3. 移除 `--answers-text` 参数，不增加用户心智负担。

## 方案

- `amazon-rufus get` 成功路径直接调用答案文本投影输出。
- 多条答案按题库顺序用空行分隔。
- 单题失败且无文本时输出题目失败摘要。
- 错误路径保留既有稳定 JSON 错误结构，便于排障。

## 非目标

- 不修改 Rufus replay、parser、browser 捕获链路。
- 不引入新上传能力或远端 API。
