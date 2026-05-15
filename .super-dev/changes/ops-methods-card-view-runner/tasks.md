# ops-methods-card-view-runner Tasks

## 1. 契约测试

- [x] 1.1 新增 `tests/skills/test_ops_methods_card_skill_contract.py`，锁定 `SKILL.md` 使用 `ops-cli-view-runner`。
- [x] 1.2 在同一测试中断言 `SKILL.md` 不再把 `交叉表-1778233062511.xlsx` 作为默认业务入口。
- [x] 1.3 在同一测试中断言 `SKILL.md` 不引用当前不存在的 `references/执行流程.md`、`references/卡片.md`、`references/卡片输出示例.html`。
- [x] 1.4 运行新增测试，确认 RED。

## 2. runner 输出测试

- [x] 2.1 新增 `tests/skills/test_ops_cli_view_runner.py`，直接调用 runner 内部纯函数验证缺参输出所需数据。
- [x] 2.2 新增成功摘要测试，确认 `view_config` 包含 `input_schema`、`output_schema`、`metric_definitions`、`chart_contract`、`quality_rules`。
- [x] 2.3 运行新增测试，确认 RED。

## 3. 实现

- [x] 3.1 更新 `opscli/skills/templates/ops-methods-card/SKILL.md`，改为视图驱动流程。
- [x] 3.2 更新 `.agents/skills/ops-methods-card/SKILL.md`，保持项目已安装 Skill 与模板一致。
- [x] 3.3 保留 `xlsx_preview.py`，但在文档中明确其输入来自 runner 导出文件。
- [x] 3.4 在 `ops-cli-view-runner/scripts/run_view.py` 中新增 `view_config` 摘要纯函数，并接入成功输出。
- [x] 3.5 同步更新 `opscli/skills/templates/ops-cli-view-runner/SKILL.md`，说明成功输出新增摘要。

## 4. 验证

- [x] 4.1 运行 `python -m pytest tests/skills/test_ops_methods_card_skill_contract.py tests/skills/test_ops_cli_view_runner.py -q`。
- [x] 4.2 运行 `python -m pytest tests/skills/test_manager.py::test_install_ops_methods_card_template -q`。
- [x] 4.3 运行 `python -m pytest tests/skills/test_ops_methods_card_xlsx_preview.py -q`。
- [x] 4.4 运行 `git diff --check`。
- [x] 4.5 做最小 diff review，确认没有改动无关文件。
