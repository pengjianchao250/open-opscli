# amazon-rufus-answer-report-format Tasks

## 实现任务

- [x] 增加 `AnswerReportFormatter` 的失败测试。
- [x] 增加 CLI `get` 输出格式化报告的失败测试。
- [x] 实现 `opscli/amazon_rufus/services/answer_report_formatter.py`。
- [x] 将 `commands/cli.py` 成功输出接入 formatter。
- [x] 更新旧 CLI 输出测试断言。
- [x] 运行 `tests/amazon_rufus/test_core.py`。

## 质量约束

- 先写失败测试，再写实现。
- formatter 只做展示投影，不修改 manager/parser/replay 的数据结构。
- 不新增 `--output`、分页器或交互式分段输出。
- 不输出内部 JSON、seed request、upload payload、headers 或 cookie。
- 代码注释使用中文且保持简洁。
