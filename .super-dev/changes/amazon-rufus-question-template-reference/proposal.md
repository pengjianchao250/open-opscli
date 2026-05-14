# amazon-rufus-question-template-reference Proposal

## 背景

`ops-amazon-rufus` 当前把问题模板同步说明放在主使用文档中，容易和 `amazon-rufus get` 的回答获取流程混在一起。现在问题模板不仅需要说明如何获取默认题库，还需要说明管理端如何保存模板和问题列表。

前端 `opencalw-management/index.vue` 只是页面入口，实际接口调用落在 `QuestionTemplatesTab`、`QuestionTemplateDescriptionDialog`、`QuestionTemplateQuestionsDialog` 以及 `project/tools/api/modules/opencalw.ts`。这些接口应沉淀为独立 reference，避免主流程文档承担管理接口说明。

## 目标

1. 新增独立 reference：`opscli/skills/templates/ops-amazon-rufus/references/question-templates.md`。
2. reference 只描述问题模板的数据结构、获取接口、保存接口和保存工作流。
3. `README.md` 与 `SKILL.md` 只保留题库升级入口，并链接到新 reference。
4. 不改变 `amazon-rufus get`、题库读取、Rufus replay、报告格式化或 Skill 安装逻辑。

## 非目标

1. 不新增 CLI 子命令。
2. 不接入管理端模板保存 API 到运行时代码。
3. 不让 Skill 脚本直接调用后端接口。
4. 不修改 `QuestionBankService` 或 `SkillsUpdater`。
5. 不调整报告格式化 reference。

## 技术方案

### 新增 reference

新增 `references/question-templates.md`，覆盖：

- 适用范围和边界。
- 认证与基础路径说明。
- 模板、问题、本地题库文件数据模型。
- `GET /opencalw/default-question-templates` 默认题库获取接口。
- `/admin/opencalw/question-templates` 管理端模板接口。
- `/admin/opencalw/question-templates/{templateId}/questions` 问题列表保存接口。
- 新增模板、追加问题、整体覆盖、单题修改、删除的调用顺序。

### 主文档收敛

`README.md` 与 `SKILL.md` 保留：

- `opscli skills upgrade ops-amazon-rufus` 示例。
- 本地题库文件路径。
- 指向 `references/question-templates.md` 的说明。

移除或收敛主流程中对题库细节的展开，避免与回答获取流程混杂。

## 验收标准

1. `references/question-templates.md` 存在，且只包含问题模板相关内容。
2. 新 reference 覆盖获取默认题库和保存模板/问题的接口。
3. `README.md` 与 `SKILL.md` 能跳转到新 reference。
4. 主文档仍保留题库升级命令和本地文件路径。
5. `rg` 能在新 reference 中找到 `default-question-templates`、`questions/append` 等关键接口路径。
6. 本次 diff 不包含 Python 运行时代码变更。
