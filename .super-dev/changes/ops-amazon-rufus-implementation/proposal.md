# Proposal: ops-amazon-rufus implementation

## 背景

根据已确认的 `output/ops-amazon-rufus-*.md`，新增 `opscli amazon-rufus get <asin> <country>` 运行链路，并接入 `ops-amazon-rufus` Skill 题库升级。

## 范围

- 新增 `opscli.amazon_rufus` 模块与 CLI 注册。
- 新增国家站点映射，固定在代码中，不再请求 marketplaces 接口。
- 新增本地 `question_templates.json` 读取与校验，模板和题目合并。
- 新增 `ops-amazon-rufus` Skill 模板与远端升级分发。
- 新增 Rufus seed request 捕获、页面上下文 replay、SSE parser 与 upload payload 构造的可测试边界。

## 非范围

- 不调用真实上传接口。
- 不新增 manifest / runner_config / questions/<template_id> 接口。
- 不在测试中依赖真实 Amazon、真实 Chrome 或真实后端。
