# amazon-rufus-file-output Tasks

## 实现任务

- [x] 增加 CLI `get` 报告文件落地的失败测试。
- [x] 实现报告文件命名、目录创建和 UTF-8 写入。
- [x] 调整旧 CLI stdout 断言，确保 stdout 只输出保存路径。
- [x] 更新 `ops-amazon-rufus` Skill 文档与 README。
- [x] 运行 `tests/amazon_rufus/test_core.py` 验证。

## 质量约束

- 先写失败测试，再写实现。
- 输出目录固定为运行目录下的 `output/amazon-rufus`。
- 文件名只使用 ASIN 与运行时间，时间精确到秒。
- 不新增 `--output` 参数。
- 错误路径不写报告文件，继续输出稳定 JSON。
