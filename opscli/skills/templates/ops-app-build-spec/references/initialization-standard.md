# 模板先行初始化规范

本规范适用于用户通过自然语言表达新建站点、新建看板或从零开发运营数据应用，并要求
使用 `opscli app` 创建独立 AppHub 站点的场景。

本 Skill 是自然语言建站的统一入口，但全新项目不由它自行生成脚手架。阶段 0 只编排应用
创建和模板拉取；AppHub 当前环境配置的标准模板是唯一基线，模板成功后同一个 Skill 才进入
项目盘点、业务开发和发布检查。

## 1. 新建意图

以下表达进入全新项目流程：

- 帮我用 `opscli app` 创建销售看板；
- 新建一个库存站点；
- 从零开发一个运营数据应用；
- 搭建一个需要真实业务数据的独立看板站点。

如果用户是在修改当前 Dashboard、执行一次性数据分析或接入已有源码项目，不使用全新模板
流程。存在歧义时只确认是否创建独立 AppHub 站点、站点显示名称和目标目录。

## 2. 目录前置

全新项目目标目录必须不存在、为空，或只包含 `.git` 与 `.opscli`。在模板完成前：

- 不得提前写入 `assessment.md`、README、需求文档、前端、后端、配置或部署文件；
- 需求内容保留在 Codex 会话或目标目录之外；
- 不运行 `pnpm create vue`、`create-vue` 或其他脚手架；
- 不复制 Skill assets 形成替代项目。

目录中已经存在业务源码时进入“已有项目边界”，不得为了拉模板删除或覆盖用户文件。

## 3. 固定命令顺序

由 Codex 依次执行：

```text
opscli app create "<站点显示名称>" --path <项目根目录>
opscli app init <项目根目录>
```

`app create` 负责调用 AppHub 创建应用、`apps/{slug}` 独立仓库和 `main`，并把
非敏感 binding 写入 `.opscli/app.json`。该阶段不生成业务项目文件。

`app init` 负责获取最新 `git-config`、配置本地凭据和 `origin/main`，再从
`OPSCLI_APP_TEMPLATE_REPO` 的 `OPSCLI_APP_TEMPLATE_BRANCH` 匿名拉取模板。模板 fetch
必须禁用 Git credential helper，不能把站点仓库 Token 发送到模板仓库。

首次初始化必须确认返回 `template_applied=true`。如果失败或返回未应用模板，停止项目文件
写入并处理目录、模板仓库、分支或 Git 错误，不自行生成替代脚手架。

## 4. 模板是唯一基线

模板应提供可继续开发的前端、后端、测试、SQLite、应用配置和发布基线。模板拉取成功后，
本 Skill 重新执行只读盘点，再决定需要补齐或修改的内容。

全新项目不得运行 `pnpm create vue`。不得使用初始化前的空目录结论生成第二套
`frontend/`、`backend/`、`app.yaml` 或部署结构。

模板缺少 `ops-app.config`、应用入口或其他必需结构时，记录模板问题并停止全新项目自动
初始化；不得静默复制 Skill assets 掩盖模板缺陷。

## 5. 项目身份同步

模板完成后读取：

- `.opscli/app.json.app_id`；
- `.opscli/app.json.slug`。

分别写入或校验：

- `ops-app.config.appId`；
- `ops-app.config.appName`。

站点仓库完整 `repo_url` 继续以 AppHub 返回值为事实源。应用代码不得自行派生平台身份、
公开 URL 或 `apps/{slug}` 仓库地址，也不在首次发布阶段重新注册应用。

## 6. 模板后开发

模板和身份校验完成后：

1. 重新盘点前端、后端、数据库、测试和部署文件；
2. 生成 `docs/ops-app/assessment.md` 和其他项目规范；
3. 需要真实数据时调用 `$ops-app-data-builder`；
4. Codex 在模板上完成业务开发和验证；
5. 本 Skill 执行发布检查；
6. 用户授权后执行 `opscli app push <root> --message <summary>`。

## 7. 已有项目边界

已有源码项目不套用全新模板流程：

1. 先盘点并按支持范围规范化现有项目；
2. 未绑定 AppHub 时执行 `opscli app create`；
3. 执行 `opscli app init` 配置 binding、凭据、`origin` 和 `main`；
4. `app init` 必须跳过模板并保留用户代码；
5. 发布检查通过后执行 `opscli app push`。

不得为了复用模板删除、移动或覆盖已有项目文件。

## 8. 验收

- 全新项目先完成 `create → init`，再写入项目文件；
- 首次模板初始化返回 `template_applied=true`；
- 模板是唯一基线，没有运行第二套脚手架；
- binding 与 `ops-app.config` 的应用身份一致；
- 已有源码项目不会被模板覆盖；
- 最终发布仍通过 `opscli app push` 完成。
