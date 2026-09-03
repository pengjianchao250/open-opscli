# 模板先行初始化规范

本规范适用于全新 opscli app 项目。全新项目的代码基线必须来自当前环境配置的模板仓库，Skill 不得在模板拉取前生成本地脚手架。

## 新项目判定

在写入任何项目文件前，只读检查目标目录：

- 除 `.git`、`.opscli` 外没有其他文件，视为全新或仍为空的项目；
- 已存在前端、后端、README、需求文档、测试、配置或部署文件，视为已有项目；
- 已有项目进入盘点和迁移流程，不允许用模板覆盖。

全新项目即使已经在会话中完成需求讨论，也不得提前写入 `assessment.md`、README 或任何代码，否则 `opscli app init` 会按已有源码处理并跳过模板。

## 标准初始化顺序

用户明确要求创建新站点后，按顺序执行：

```bash
opscli app create "<站点显示名称>" --path <项目根目录>
opscli app init <项目根目录>
```

验收两个命令的结果：

1. `app create` 成功生成 `.opscli/app.json`，其中包含 `app_id`、`slug` 和完整 `repo_url`。
2. `app init` 成功配置站点仓库为 `origin`，本地分支为 `main`。
3. 全新项目必须返回 `template_applied=true`。
4. 模板地址和分支来自当前环境的 `OPSCLI_APP_TEMPLATE_REPO` 与 `OPSCLI_APP_TEMPLATE_BRANCH`。
5. 模板拉取失败时停止，不运行其他脚手架命令作为降级替代。

用户未明确授权远端创建应用时，只在会话中整理需求并请求确认，不得执行 `app create`，也不得提前生成项目文件。

## 模板是唯一基线

模板初始化成功后重新读取项目目录，以实际模板内容作为后续盘点、设计和修改依据：

- 不运行 `pnpm create vue`、`create-vite` 或其他脚手架覆盖模板；
- 不从 Skill assets 复制一套与模板重复的完整项目；
- 不假设模板固定使用 React 或 Vue，必须读取依赖、入口和锁文件确认；
- 保留模板的包管理器、锁文件、目录结构、测试框架和部署基线；
- 仅按业务需求和规范补齐实际缺失的部分。

模板缺少声明的关键能力时，记录缺失文件和证据，提示维护模板仓库；不得静默再造第二套工程规避问题。

## 项目身份同步

模板完成后读取：

```text
.opscli/app.json.app_id
.opscli/app.json.slug
```

并同步到：

```text
ops-app.config.appId
ops-app.config.appName
```

要求：

- `appId` 必须等于 binding 的 `app_id`；
- `appName` 必须等于 binding 的 `slug`；
- 保留 `ops-app.config` 的其他字段；
- 使用临时文件原子替换；
- 已有非占位身份与 binding 冲突时停止，不得自动覆盖；
- 模板缺少 `ops-app.config` 或文件格式非法时停止并报告模板问题；
- 不在首次发布阶段再次注册应用或猜测应用 ID。

## 模板最低合同

正式模板的 `main` 分支应提供可继续开发的基础结构，并与实际发布平台保持一致。至少应能识别：

- 前端依赖、入口、路由和统一 `/api` Client；
- FastAPI 后端入口、健康检查和业务 API 分层；
- SQLite 连接、迁移和持久化边界；
- 前后端测试入口；
- `ops-app.config`；
- `deployment/` 下的 Dockerfile、Compose、Nginx 和共享配置资产；
- 根目录 `.dockerignore` 和非敏感环境变量示例。

模板不得包含其他站点的 `.opscli/app.json`、真实凭据、真实业务数据或指向其他业务仓库的 Git 配置。

## 模板后的盘点与开发

模板初始化和身份同步完成后，才允许：

1. 生成 `docs/ops-app/assessment.md`；
2. 生成或更新 project-spec、migration-plan、development 和 deployment；
3. 修改前端页面、FastAPI、SQLite、测试和部署文件；
4. 有真实数据需求时调用 `$ops-app-data-builder`。

后续依赖安装、构建和测试使用模板实际声明的命令。不得把未运行的验证写成已通过。

## 已有项目边界

已有源码项目不使用模板初始化：

- 先按实际源码盘点和生成迁移计划；
- 需要绑定 AppHub 时执行 `opscli app create --path <root>`；
- 再执行 `opscli app init <root>` 配置凭据、origin 和 main；
- 必须确认 `template_applied=false` 且现有文件未被覆盖；
- 缺少前端或后端时按对应规范处理，不得把已有项目重新伪装为空目录。

## 初始化验收

- 全新项目的第一批代码来自模板仓库，而不是 Skill 生成的脚手架；
- `.opscli/app.json` 与 `ops-app.config` 身份一致；
- Git `origin` 指向 AppHub 返回的当前站点独立仓库；
- 默认分支为 `main`；
- 模板项目可以按其实际说明安装依赖并运行最小构建、测试；
- 没有真实密钥、业务数据或其他站点 binding。
