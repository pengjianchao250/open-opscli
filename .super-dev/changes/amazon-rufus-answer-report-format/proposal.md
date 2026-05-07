# amazon-rufus-answer-report-format Proposal

## 背景

`opscli amazon-rufus get` 当前成功时直接拼接 `answers[].text`。长回答中的标题、列表、表格、相关产品、推荐 ASIN 和总结没有按前端 `asinRufusView` 的展示模型投影，导致终端输出可读性差。

## 目标

新增 CLI 展示层 formatter，参考 operation-frontend 的 `asinRufusView` 渲染方式，基于 `RufusManager.get()` 返回的完整 `data` 输出格式化答案报告。

## 范围

- 新增 `AnswerReportFormatter`。
- CLI `get` 成功路径改为输出格式化报告。
- formatter 优先消费 `answer.blocks`，缺失时回退解析 `answer.text`。
- 输出相关产品、答案正文、推荐 ASIN、总结。
- 补充 formatter 与 CLI 回归测试。

## 非目标

- 不新增文件输出参数。
- 不处理终端截断。
- 不修改 Rufus replay、parser、题库、上传 payload。
- 不输出 `seed_request`、`upload_payload`、headers、cookie 或完整 JSON。

## 验收

- 结构化 blocks 优先于 fallback text。
- heading、paragraph、list、table 输出与前端模型一致。
- `productLinks`、`recommendedAsins`、`summaryText` 按前端顺序输出。
- CLI stdout 不泄露内部字段。
- `tests/amazon_rufus/test_core.py` 通过。
