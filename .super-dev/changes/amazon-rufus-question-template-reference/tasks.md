# amazon-rufus-question-template-reference Tasks

## 1. 文档落点

- [x] 1.1 创建 `.super-dev/changes/amazon-rufus-question-template-reference/proposal.md`。
- [x] 1.2 创建 `.super-dev/changes/amazon-rufus-question-template-reference/tasks.md`。
- [x] 1.3 新增 `opscli/skills/templates/ops-amazon-rufus/references/question-templates.md`。

## 2. 主文档收敛

- [x] 2.1 更新 `opscli/skills/templates/ops-amazon-rufus/README.md`，把问题模板细节收敛到新 reference。
- [x] 2.2 更新 `opscli/skills/templates/ops-amazon-rufus/SKILL.md`，在数据文件章节指向新 reference。
- [x] 2.3 保留 `opscli skills upgrade ops-amazon-rufus` 和本地题库路径说明。

## 3. 验证

- [x] 3.1 回读新 reference，确认只包含问题模板相关内容。
- [x] 3.2 使用 `rg` 检查关键接口路径已覆盖。
- [x] 3.3 检查 diff，确认没有 Python 运行时代码变更。
