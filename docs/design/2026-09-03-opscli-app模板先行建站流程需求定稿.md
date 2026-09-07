# opscli app 模板先行建站流程需求定稿

> **历史方案，已被取代**：2026-09-05 起模板获取和建站顺序不再属于 `opscli app`，以 `docs/design/2026-09-05-opscli-app三命令源码交付职责定稿.md` 为准。

> 日期：2026-09-03  
> 状态：已落地  
> 范围：固化自然语言新建站点意图的模板先行顺序，最小调整 `ops-app-build-spec` 入口门禁和相关文档、测试；不增加 opscli 用户命令，不修改 AppHub API。

## 1. 背景与问题

全新站点的标准代码应来自当前环境配置的模板仓库：

```text
OPSCLI_APP_TEMPLATE_REPO=http://10.1.13.143:3000/aukeys-admin/template.git
OPSCLI_APP_TEMPLATE_BRANCH=main
```

当前 `opscli app init` 只有在目标目录没有源码时才应用模板。除 `.git` 和
`.opscli` 外，只要目录中提前出现 README、需求文档、assessment、前端、后端或部署文件，
该目录就会被视为已有源码并跳过模板。

因此，全新项目如果先由 Codex 或 Skill 生成一批代码，再执行 `opscli app init`，模板将
失去作为项目基线的意义，也可能形成两套相互冲突的脚手架。

## 2. 核心原则

1. 全新 opscli app 项目必须先创建 AppHub 应用，再拉取标准模板，最后开始业务开发。
2. `opscli app init` 完成之前，Codex 和 Skill 不得向目标目录写入项目文件。
3. 模板是全新项目唯一的代码基线；`ops-app-build-spec` 不再对该场景运行
   `create-vue` 或自行创建另一套脚手架。
4. 已有源码项目继续保留现有代码，`opscli app init` 跳过模板，不覆盖用户文件。
5. `ops-app-data-builder` 只能在模板初始化完成或已有受支持项目结构时生成数据层。
6. 用户命令仍固定为 `opscli app create`、`opscli app init`、`opscli app push`。

## 3. 全新项目标准流程

```text
用户表达新建站点、新建看板或从零开发运营数据应用意图
    ↓
Codex 加载 ops-app-build-spec 作为统一建站入口
    ↓
ops-app-build-spec 阶段 0 识别为全新 opscli app，确认站点名称和空目标目录
此阶段只做门禁和命令编排，不写入目标目录
    ↓
opscli app create <site_name> --path <project_root>
    ↓
AppHub 创建应用、apps/{slug} 独立仓库和 main
    ↓
opscli app init <project_root>
    ↓
opscli app init 配置凭据、origin 和 main
并从当前环境模板仓库匿名拉取 main
    ↓
首次初始化确认 template_applied=true
    ↓
同一个 ops-app-build-spec 进入正式阶段，重新读取模板项目并生成 assessment、项目规范和改造计划
    ↓
需要真实数据时调用 ops-app-data-builder
    ↓
Codex 在模板代码上完成页面、后端、测试和部署文件
    ↓
ops-app-build-spec 执行发布检查
    ↓
opscli app push <project_root> --message <summary>
    ↓
Git push、AppHub release、构建部署和 SSE 结果
```

## 4. 已有项目流程

已有源码项目不执行模板覆盖：

1. `ops-app-build-spec` 盘点和规范化现有项目。
2. 未绑定 AppHub 时执行 `opscli app create --path <project_root>`。
3. 执行 `opscli app init <project_root>`，配置 binding、凭据、origin 和 main。
4. 因目录已有源码，init 必须跳过模板并保留用户文件。
5. 完成发布检查后执行 `opscli app push`。

## 5. Skill 行为调整

### 5.1 ops-app-build-spec

- 作为自然语言新建站点的统一入口，先识别“全新项目”或“已有项目”。
- 全新项目未绑定时，阶段 0 只执行或明确引导执行 `app create` 和 `app init`，不进入项目文件生成步骤。
- 在 `app init` 成功前，不生成 assessment、migration-plan、前后端、配置或部署文件。
- 模板拉取完成后重新盘点，不使用初始化前的空目录结论代替模板盘点。
- 从 `.opscli/app.json` 读取 `app_id` 和 `slug`，分别写入或校验
  `ops-app.config.appId` 和 `ops-app.config.appName`。
- 模板缺少必需结构时停止并报告模板问题，不静默创建另一套脚手架。

### 5.2 ops-app-data-builder

- 开始前检查项目不是未初始化的全新空目录。
- opscli app 站点必须存在 `.opscli/app.json`，并已具有模板或受支持的现有项目结构。
- 检查 `ops-app.config` 与 binding 的 `app_id/slug` 一致。
- 前置条件不满足时停止代码生成，并提示先执行 `opscli app create/init` 或完成
  `ops-app-build-spec` 初始化。

## 6. 模板仓库合同

模板仓库 `main` 应提供可继续开发的完整基础结构，包括项目配置、前端、FastAPI、
SQLite、测试和部署基线。模板不得包含：

- 其他站点的 `.opscli/app.json`；
- 真实凭据、业务数据或用户身份；
- 指向其他业务仓库的 Git remote 配置；
- 与 `ops-app-build-spec` 冲突的第二套项目身份配置。

模板内容由模板仓库独立维护。本仓库负责模板地址选择、拉取流程、Skill 使用约束和发布闭环。

## 7. 本次实现范围

### 修改

- `ops-app-build-spec` 新项目启动门禁、自然语言意图和模板优先规则；
- `ops-app-build-spec` 初始化、项目身份和发布检查规范；
- `ops-app-build-spec` 版本、契约测试和流程文档；
- 保留 `ops-app-data-builder` 现有模板初始化门禁；
- AppHub 使用指南与待发布变更记录。

### 不修改

- 不新增 `opscli app` 命令；
- 不合并 `app create` 与 `app init`；
- 不修改 AppHub API 或 Gitea 管理流程；
- 不改变空目录应用模板、已有源码跳过模板的现有 Python 行为；
- 不增加新的模板环境变量；
- 不修改 `app push → release → SSE` 发布闭环。

## 8. 验收标准

1. 用户表达新建站点、新建看板或从零开发运营数据应用意图时，Codex 加载 `ops-app-build-spec` 作为入口；Skill 阶段 0 先执行 `create → init`，再进入项目文件生成步骤。
2. 全新项目不再通过 Skill 执行 `create-vue` 创建另一套脚手架。
3. 模板拉取完成后，Skill 才生成 assessment、项目规范和业务代码。
4. 已有源码项目仍跳过模板且不被覆盖。
5. 数据层 Skill 在模板或现有项目初始化完成前不会生成业务代码。
6. `ops-app.config` 的应用身份来自 `.opscli/app.json`，不再依赖未定义的首次发布注册工具。
7. 用户命令保持三个，AppHub 和发布接口不变。
8. app 专项测试和两个 Skill 契约测试全部通过。
