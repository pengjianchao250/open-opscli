# listing-rufus-trigger Tasks

## 1. TDD 覆盖

- [x] 在 `tests/skills/test_manager.py` 新增 listing 触发词断言。
- [x] 运行新增测试，确认修改前失败且失败原因是缺少 listing 触发内容。

## 2. Skill 文档实现

- [x] 更新 `opscli/skills/templates/ops-amazon-rufus/SKILL.md` 的 frontmatter `description`。
- [x] 在模板 `SKILL.md` 新增“触发范围”章节。
- [x] 同步更新 `.agents/skills/ops-amazon-rufus/SKILL.md`。

## 3. 变更记录

- [x] 按项目规范追加 `docs/change-log-pending.md`。

## 4. 验证

- [x] 运行 `rg` 检查两份 `SKILL.md` 的 listing 触发词与边界说明。
- [x] 运行 `pytest tests/skills/test_manager.py tests/skills/test_cli.py -v`。
- [x] 运行 `git diff --check`。
- [x] 回读最小 diff，确认没有触碰 Rufus CLI 运行链路。
