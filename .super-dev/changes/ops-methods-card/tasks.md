# ops-methods-card Tasks

## 1. 文档与契约

- [x] 1.1 读取 `operation-frontend - 1` 的 aiMethodCard 页面、类型和接口文档。
- [x] 1.2 更新 proposal，明确列表/详情接口、Excel 和 HTML 输出范围。

## 2. 测试先行

- [x] 2.1 新增 `MethodsCardClient.list_cards()` 请求契约测试。
- [x] 2.2 新增 `MethodsCardClient.detail_card()` 请求契约测试。
- [x] 2.3 新增 CLI list/detail 输出测试。
- [x] 2.4 新增 Excel 预览脚本测试。
- [x] 2.5 运行新增测试，确认 methods-card 模块缺失导致 RED。

## 3. 实现

- [x] 3.1 新增 `opscli/methods_card` 模块。
- [x] 3.2 注册 `opscli methods-card` 顶级命令。
- [x] 3.3 新增 `scripts/xlsx_preview.py`。
- [x] 3.4 更新 `ops-methods-card/SKILL.md` 完整工作流。
- [x] 3.5 新增 `references/执行流程.md` 和 `references/方法卡接口.md`。
- [x] 3.6 安装模板时过滤 Python 缓存文件。
- [x] 3.7 将 `ops-methods-card` 安装到项目 `.agents/skills/ops-methods-card`。

## 4. 验证

- [x] 4.1 运行 methods-card CLI 测试。
- [x] 4.2 运行 Excel 预览脚本测试。
- [x] 4.3 运行 Skill 校验。
- [x] 4.4 运行 install-path 测试。
- [x] 4.5 运行 `git diff --check`。
- [x] 4.6 运行 `skills list --skills-dir ".agents/skills"` 验证项目安装可发现。
- [x] 4.7 检查 `.agents/skills/ops-methods-card` 不包含 `__pycache__` / `*.pyc` / `*.pyo`。
