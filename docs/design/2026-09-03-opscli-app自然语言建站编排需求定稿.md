# opscli app 自然语言建站编排需求定稿

> **历史方案，已被取代**：2026-09-05 起自然语言建站编排由 Skill 负责，`opscli app` 只提供 create/init/push/release 四个原子命令。

> 日期：2026-09-03  
> 状态：需求定稿并落地  
> 关联：`docs/design/2026-09-03-opscli-app模板先行建站流程需求定稿.md`

## 1. 需求背景

用户通常不会逐条输入 CLI 命令，而是在 Codex 中使用自然语言表达需求，例如：

- 帮我用 `opscli app` 创建销售看板；
- 搭建一个库存站点；
- 开发一个运营数据应用。

全新站点必须先由 `opscli app` 调用 AppHub 创建应用和独立仓库，再由
`opscli app init` 拉取标准模板。模板成功前如果 Codex 或 Skill 先生成 assessment、
README、前后端或部署文件，`app init` 会把目录识别为已有项目并跳过模板。

## 2. 本次决策

1. 用户表达新建站点、新建看板或从零开发运营数据应用意图时，Codex 将其路由为全新
   `opscli app` 建站流程。
2. `ops-app-build-spec` 作为统一入口，阶段 0 固定执行 `app create → app init → 模板`，随后同一个 Skill 进入正式开发，最后执行 `app push`。
3. `opscli app` 继续保留 `create / init / push` 三个命令，不增加第四个编排命令。
4. 不增加工作流状态机、项目类型字段或新的 AppHub API。
5. `ops-app-build-spec` 只增加必要的模板先行门禁；其技术栈盘点、迁移、数据路由和
   发布检查职责保持不变。
6. 已有源码项目继续跳过模板，不覆盖用户文件。

## 3. 意图路由

以下表达应进入全新站点流程：

```text
帮我用 opscli app 创建销售看板
新建一个库存站点
从零开发一个运营数据应用
搭建一个需要真实业务数据的独立看板站点
```

以下场景不进入全新模板流程：

- 用户明确要求改造或接入当前已有源码项目；
- 用户只要求一次性查询、导出或经营分析；
- 用户要求修改已绑定的 Dashboard 页面，而不是创建独立 AppHub 站点。

存在歧义时只确认是否创建独立 AppHub 站点、站点名称和目标目录。

## 4. 全新项目标准流程

```text
用户表达新建站点或看板意图
    ↓
Codex 加载 ops-app-build-spec 作为统一建站入口
    ↓
ops-app-build-spec 阶段 0 确认站点名称和空目标目录
    ↓
Codex 执行 opscli app create
    ↓
AppHub 创建应用、apps/{slug} 独立仓库和 main
    ↓
Codex 执行 opscli app init
    ↓
opscli app init 配置凭据、origin 和 main，并拉取标准模板
    ↓
首次初始化确认 template_applied=true
    ↓
同一个 ops-app-build-spec 进入正式阶段，重新盘点模板
    ↓
有真实数据需求时调用 ops-app-data-builder
    ↓
Codex 在模板上完成业务开发和验证
    ↓
ops-app-build-spec 执行发布检查
    ↓
Codex 执行 opscli app push
    ↓
Git push、AppHub release、构建部署和 SSE 结果
```

## 5. 模板前硬门禁

全新项目在 `app init` 成功前：

- 目标目录只能不存在、为空，或只包含 `.git` 与 `.opscli`；
- 需求内容保留在 Codex 会话或目标目录之外；
- 不写入 assessment、README、需求文档、前后端、`app.yaml` 或部署文件；
- 不运行 `pnpm create vue` 或其他脚手架；
- 不自行复制 Skill assets 形成第二套项目基线。

标准模板是全新项目的唯一代码基线。模板缺少必需结构时停止并报告模板问题，不静默创建
替代脚手架。

## 6. Skill 职责

### 6.1 ops-app-build-spec

- 作为自然语言新建站点的统一入口；
- 阶段 0 只执行模板门禁和 `app create/init` 命令编排，不写项目文件；
- 模板完成后重新读取项目，不使用空目录阶段的结论；
- 从 `.opscli/app.json` 校验应用身份和仓库绑定；
- 需要真实数据时路由到 `ops-app-data-builder`；
- 开发完成后执行发布检查并交给 `opscli app push`。

### 6.2 ops-app-data-builder

维持现有门禁：只有模板已初始化，或者已有项目结构已通过
`ops-app-build-spec` 确认时，才允许生成真实业务数据层。

## 7. 实现范围

### 修改

- `ops-app-build-spec/SKILL.md`：增加自然语言新建意图和模板门禁；
- Skill 版本和契约测试；
- AppHub 使用指南、模板先行需求文档和开发规范。

### 不修改

- 不修改 `opscli app create / init / push` 的 Python 行为；
- 不修改 AppHub API；
- 不新增用户命令；
- 不合并 `create` 与 `init`；
- 不增加配置项或环境变量；
- 不改变已有源码跳过模板的规则；
- 不改变 `app push → release → SSE` 发布闭环。

## 8. 验收标准

1. Skill 能识别新建站点、新建看板和从零开发运营数据应用意图。
2. 全新项目在模板完成前不会生成 assessment 或项目代码。
3. 初始化 Reference 明确执行 `app create` 和 `app init`。
4. 全新项目不再运行 `pnpm create vue` 创建第二套脚手架。
5. 同一个 Skill 在模板完成后才从阶段 0 进入项目盘点、数据层开发和发布检查。
6. 已有源码项目继续跳过模板并保留用户文件。
7. 用户命令仍只有 `create / init / push`。
