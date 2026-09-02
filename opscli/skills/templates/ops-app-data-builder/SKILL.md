---
name: ops-app-data-builder
description: 用于 Codex 中为 opscli app 站点构建真实业务数据层；读取现有前后端项目，把页面需求拆成数据产品，验证 OPS、Keepa 或 SellerSprite 数据合同，并生成或改造 FastAPI 数据层、前端 API、SQLite 迁移、测试和数据规范。单次临时查询、普通页面搭建、经营分析、当前 Dashboard 编辑或分析不使用本 Skill。
metadata:
  version: 0.1.0
---

# OPS 应用数据层构建

把自然语言页面需求转换为可审查、可测试、可部署的站点数据层。先验证真实数据合同，再按现有项目结构生成后端调用、业务加工、持久化、站点 API 和前端类型。

本 Skill 构建项目代码，不替代线上数据服务，不修改 `opscli/app/sdk`，也不让线上站点依赖 Skill 运行。

## 触发边界

使用本 Skill：

- 当前工作对象是通过 opscli app 创建或符合 `ops-app-build-spec` 的站点。
- 页面需要 OPS、Keepa、SellerSprite 或这些来源的组合数据。
- 需求包含多个字段、跨来源组合、二次加工、数据新鲜度、SQLite 物化或站点专用 API。
- 需要为现有页面补齐 FastAPI client/service/repository/schema/API、前端 API/types、迁移或测试。
- 用户要求修复前端直连运营系统或第三方平台的取数方式。

不要使用本 Skill：

- 只需要一次临时查询或导出：使用对应数据查询 Skill。
- 业务范围、指标或维度尚不明确，且当前没有站点数据层交付目标：使用 `$ops-query-wizard`。
- 只搭建静态页面、交互或样式：继续使用 `$ops-app-build-spec`。
- 只分析一次真实数据结果，不修改站点：使用对应分析 Skill。
- 创建、修改或分析当前 Dashboard 页面：使用 Dashboard 专用 Skill。
- 当前后端不是 FastAPI，或数据库不是 SQLite：停止自动改造并按 `ops-app-build-spec` 提示联系 IT。

不要为了触发本 Skill，把单次查询扩展成站点数据工程任务。

## 必要输入

- 项目根目录和当前 `AGENTS.md`。
- 已确认的页面业务需求、筛选范围、刷新要求和使用者范围。
- `docs/ops-app/project-spec.md`；存在时同时读取 assessment、migration-plan、development、deployment 和 data-spec。
- 现有前端页面及 API 封装、FastAPI 路由/service/schema、SQLite model/repository/migration 和测试。
- 当前项目实际提供的 OPS 应用运行时适配器合同。

缺少业务范围时只询问会改变数据合同、权限或存储方案的关键问题。缺少 FastAPI 后端时可以完成数据规范和前端 Mock 合同，但不得创建未经 `ops-app-build-spec` 允许的后端占位服务。

## Reference 路由

| 阶段 | 必须读取 |
| --- | --- |
| 拆解数据产品、定义接口和持久化 | `references/data-layer-contract.md` |
| 判断 OPS、Keepa、SellerSprite 运行时路径 | `references/runtime-source-routing.md` |

涉及任一真实数据源时两份 Reference 都要读取。

## 依赖路由

- OPS 需求清晰：使用 `$ops-dataset-query` 验证真实数据集、字段、口径和少量样本。
- OPS 需求缺参、模糊或有歧义：使用 `$ops-query-wizard` 完成澄清和合同验证。
- Keepa：使用 `$ops-keepa` 验证正式场景、参数、返回结构和少量样本。
- SellerSprite：使用 `$ops-seller-sprite` 验证开发期场景、参数、返回结构和少量样本。

依赖 Skill 负责认证、元数据、字段校验和真实查询。本 Skill 不凭记忆选择数据集、字段、聚合、公式、筛选枚举或第三方场景参数，也不复制其内部查询实现。

只获取足以验证合同的少量样本。真实结果、导出文件和凭证不得提交到站点源码。

## 工作流

### 1. 读取项目证据

读取项目规范、前后端入口、API 调用、环境变量、数据库、迁移和测试，确认实际技术栈和现有数据边界。不得只凭目录名套用固定结构。

重点识别：

- 浏览器是否直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 是否有密钥进入 `VITE_*`、源码、静态产物或日志。
- 后端是否已有可复用 client、service、repository 和错误信封。
- SQLite 是否为单写实例、是否有迁移、持久卷和清理策略。
- 项目是否实际提供经过批准的 OPS 应用运行时适配器。

将发现写入 `docs/ops-app/assessment.md`；保留其他工具或人员维护的内容。

### 2. 识别数据产品

按业务判断拆成有限、互不重复的数据产品，不按页面卡片或字段数量机械拆分。每个数据产品必须有明确用途、消费者和刷新要求。

示例名称：`sales_overview`、`inventory_risk`、`keepa_price_history`、`keyword_competition`、`product_operation_overview`。

读取 `references/data-layer-contract.md`，为每个数据产品记录数据源、合同状态、粒度、自然键、执行模式、站点 API、加工规则、存储和测试。

### 3. 验证真实合同

按依赖路由验证每个来源。至少确认：

- 数据集或场景的真实名称与可用状态。
- 维度、指标、筛选、时间字段、粒度和口径。
- 请求参数、响应结构、分页、截断、空值和数据量。
- 当前身份、站点、币种、时区和额度边界。
- 自然键、可重复执行语义和数据新鲜度。

无法验证的字段不得写成已确认合同。部分来源阻塞时保留已验证部分，并在 data-spec 中逐项标记 `blocked`。

### 4. 选择执行模式

- `viewer-live`：当前访问用户权限相关的 OPS 数据，请求时实时查询，默认不写共享 SQLite。
- `app-materialized`：与访问者权限无关、允许共享的数据，由后端获取并批量写入 SQLite。
- `hybrid`：OPS viewer 数据实时查询，允许共享的第三方快照从 SQLite 读取，由 service 在请求时组合。

按身份隔离、实时性、额度、数据量、复用频率和故障恢复选择模式。不得仅因查询耗时就把 viewer 数据写入共享库。

### 5. 生成数据规范

创建或更新 `docs/ops-app/data-spec.md`，至少包含：

- 页面与数据产品映射。
- 来源和验证证据。
- 字段、粒度、时间、筛选与口径。
- 执行模式、身份边界和数据流。
- FastAPI API、Pydantic 合同和前端类型。
- 二次加工、自然键、SQLite 表、迁移和清理策略。
- 数据新鲜度、分页、额度、超时和错误处理。
- 环境变量、Mock、测试、阻塞项和待接入边界。

同时更新 `project-spec.md` 的数据层摘要；初始化或迁移任务还要同步更新 migration-plan、development 和 deployment。第一阶段不创建第二个运行时 YAML 权威源。

### 6. 生成或改造项目代码

遵循项目现有结构，只创建有实际职责的文件。典型职责为：

```text
backend/app/api/             FastAPI 路由和请求协议
backend/app/clients/         已批准的 OPS/opscli API 调用封装
backend/app/services/        跨来源编排和二次加工
backend/app/repositories/    SQLite 访问
backend/app/schemas/         Pydantic 请求与响应合同
backend/app/models/          持久化模型
backend/app/db/              连接和迁移
backend/tests/               数据合同、接口和异常测试
frontend/src/api/            当前站点 /api Client
frontend/src/types/          与 Pydantic 对齐的前端类型
```

简单项目可以合并空层；已有结构不同则复用现有命名，不为套模板做无关重构。

后端路由只做协议转换、参数校验和错误映射；网络调用与业务加工进入 client/service；SQLite 访问进入 repository/db。跨来源组合必须在 service 完成，不得放到浏览器。

### 7. 验证

从最小相关测试开始，再运行项目已有的类型检查、构建和后端测试。完成前确认：

- 前端只调用当前站点 `/api`。
- OPS 使用实际项目中经过批准的应用运行时身份适配器。
- OPS viewer 数据未写入未隔离的共享 SQLite。
- Keepa API Key 只从后端 Secret 注入。
- SellerSprite 未生成当前不存在的正式线上调用。
- 网络调用发生在 SQLite 事务外，写入使用短事务和批量操作。
- Pydantic Schema、OpenAPI 和前端类型一致。
- 测试覆盖成功、空数据、上游失败、分页/截断和权限边界。
- 项目中没有真实业务数据文件、凭证或完整鉴权头。

未运行的验证不得写成已通过。

## 硬边界

- 不修改 `opscli/app/sdk` 或新增 opscli REST 端点。
- 不让前端直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 不在站点中执行 opscli CLI 子进程或临时连接 MCP 作为线上取数路径。
- 不读取本机 opscli 登录态、Cookie、Keychain 或凭证文件。
- 不把 API Key、JWT、Cookie、完整鉴权头或真实账号写入源码、前端、SQLite、日志或文档。
- 不从请求体接受用户自报身份；OPS 身份只能来自批准的宿主请求通道。
- 不把未按用户隔离的 OPS viewer 结果写入共享 SQLite。
- 不用 SQLite 保存大文件、大型 BLOB 或高频任务队列。
- 不伪造不存在的 SDK 类、导入路径、REST 端点、轮询端点或认证协议。
- 不生成无人值守 OPS 同步任务；Keepa 定时同步只复用项目已有且合规的调度入口。
- 不创建运行时数据 YAML 或另一套配置权威源。

## 阻塞规则

- 实际项目没有可检查的 OPS 应用运行时适配器：记录合同和 Mock，阻止生成 OPS 正式调用代码，不根据文档名称猜导入路径或方法签名。
- SellerSprite 没有项目既有且经批准的运行时适配器：只生成 schema、Mock、存储设计和站点 API 合同，状态标记为 `blocked`。
- Keepa 需求需要正式文档未声明的任务状态或导出下载端点：不得猜测路径；改用已声明的同步能力或标记待平台补齐。
- 依赖 Skill 或真实合同不可用：停止对应数据产品，不影响已验证数据产品继续交付。
- 需要多写实例、跨服务共享数据库或高频持续写入：停止 SQLite 方案并提示联系 IT。

## 完成交付

最终回复只报告：数据产品、已验证来源、生成或修改的代码与文档、执行模式、验证结果、阻塞项和用户下一步。不得把 Mock 写成真实接入，不得把合同验证样本写成线上数据。
