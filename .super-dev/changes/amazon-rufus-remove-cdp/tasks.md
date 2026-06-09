# Amazon Rufus 删除 CDP 与 remote 链路任务

- [x] 补充 RED 测试：MCP 只暴露 `amazon_rufus_get`，且 `amazon_rufus_init` / `amazon_rufus_get_remote` 不存在。
- [x] 补充 RED 测试：`amazon_rufus_get` 不再接受或透传 CDP 参数。
- [x] 补充 RED 测试：CLI help 不包含 `init` 和 CDP/remote 参数。
- [x] 补充 RED 测试：后端链路空 `answers` 正常返回 0 答案报告。
- [x] 删除 MCP `amazon_rufus_init`、`amazon_rufus_get_remote` 和 CDP 参数。
- [x] 收敛 CLI `amazon-rufus get` 到后端/headless 链路，删除 `init` 子命令和 CDP/remote 参数。
- [x] 删除或移除 Service 层 CDP/remote 引用，清理无引用异常和导入。
- [x] 更新 `ops-amazon-rufus` 模板与 `.agents` 副本文档。
- [x] 更新 `docs/change-log-pending.md`。
- [x] 运行定向测试和 `git diff --check`。
