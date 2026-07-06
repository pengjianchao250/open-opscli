# ops-new-product-calculator Skill 渐进式拆分提案

## 背景

当前 `ops-new-product-calculator/SKILL.md` 共 318 行，同时承载入口路由、完整字段参考、JSON 示例和结果模板。Agent 每次触发都会加载所有内容，且文档没有覆盖 CLI 已存在的 `show`、`copy` 命令。

## 目标

- 主文件聚焦触发、任务路由和全局门禁。
- 草稿细节与结果细节按需加载。
- 补齐新建草稿、继续草稿、查询/复用任务三类入口。
- 通过失败优先的契约测试验证结构和行为。
- 补充线上创建页、列表页和结果详情页路由。

## 方案

新增：

- `references/draft-workflow.md`
- `references/result-workflow.md`

修改：

- `SKILL.md`
- `tests/skills/test_ops_new_product_calculator_skill.py`
- `docs/change-log-pending.md`

主文件必须明确参考文件的加载条件；完整 JSON 仅保留在草稿参考中，完整费用表模板仅保留在结果参考中。

## 约束

- 不修改 `opscli/calculator/` 实现。
- 不修改 `data/VERSION.json`，继续保持 `v0.0.1`。
- 不执行真实 `opscli calculator submit`。
- 不直接调用 Polaris 后端 API。
- 保留认证、失败自动反馈、提交确认和敏感信息保护规则。
- Web 详情页参数继续使用 `<TASK_CODE>` / `<SUDO>` 占位，不写入真实敏感值。

## 验收

- 新增测试在参考文件创建前按预期失败。
- 主文件显著少于当前 318 行，目标不超过 220 行。
- `show`、`copy`、三类入口和条件加载均有契约覆盖。
- 草稿参考中的 JSON 继续通过 `validate_draft_data()`。
- 三个 Web 路由在主 Skill 和所属参考文件中均可检索。
- 聚焦 Skill 测试全部通过。
