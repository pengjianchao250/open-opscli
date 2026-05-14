# Amazon Rufus 问题参数与拒答重试 Tasks

## 任务 1：更新项目级 Skill 文档

- [x] 修改 `.agents/skills/ops-amazon-rufus/SKILL.md`
- [x] 增加 `--question` 单题模式说明
- [x] 增加题库模式与单题模式选择规则
- [x] 增加拒答检测、180 字内改写、最多 3 次重试说明
- [x] 增加拒答后改写问题必须使用中文的规则
- [x] 保留 UTF-8、登录、报告路径和敏感字段隐藏要求
- [x] 同步 `.agents/skills/ops-amazon-rufus/references/question-templates.md`

## 任务 2：实现 CLI 单题模式

- [x] 为 `opscli amazon-rufus get` 增加 `--question`
- [x] 在 manager 层区分题库模式与单题模式
- [x] 空白 `--question` 返回稳定错误
- [x] 单题模式不读取题库

## 任务 3：实现拒答检测与问题改写

- [ ] 新增拒答检测与改写服务
- [ ] 改写问题限制在 180 字以内
- [ ] 每题最多 3 次改写重试
- [ ] 结构化答案输出拒答和改写审计字段

## 任务 4：更新报告展示与测试

- [ ] 报告中展示改写说明和改写后问题
- [ ] 覆盖单题模式、题库模式、拒答检测、3 次重试上限测试
- [x] 运行 Amazon Rufus 相关测试
