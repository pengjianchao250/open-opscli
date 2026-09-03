# OPS 站点数据层构建能力需求与设计

> 文档日期：2026-09-02  
> 文档状态：已确认并实施  
> 新 Skill：`ops-app-data-builder`  
> 原 Skill：`ops-business-data-orchestrator`  
> 本轮约束：允许修改 `ops-app-build-spec` 并重写、改名数据 Skill；暂不修改 `opscli/app/sdk`

## 1. 业务背景

当前业务流程为：用户安装 `aukeys-opscli`，通过 `opscli app create` 创建站点，通过 `opscli app init` 拉取包含前端、FastAPI 后端和 SQLite 能力的完整模板，在 Codex 中按 `ops-app-build-spec` 搭建业务页面，最后通过 `opscli app push` 推送并自动部署。

全新项目必须严格按上述顺序执行：Codex 识别新建站点、新建看板或从零开发运营数据应用意图后，加载 `ops-app-build-spec` 作为统一入口；Skill 阶段 0 只确认站点名称和空目标目录并编排 `opscli app create/init`，模板拉取成功后同一个 Skill 才进入正式盘点和开发。`ops-app-data-builder` 只在模板初始化完成后进入，已有源码项目不套用模板。

当前建站、Git 和发布主流程已经存在，本次要补齐的是：

> 用户通过自然语言搭建依赖真实数据的页面时，Codex 如何识别数据需求、验证数据合同、生成后端取数和加工代码，并让线上站点通过合规方式持续取数。

## 2. 数据源与当前能力

| 数据源 | 典型数据 | 当前正式能力 |
| --- | --- | --- |
| OPS 公司运营系统 | 销售、库存、广告、流量、利润、权限数据 | REST query、Query SDK、应用运行时 `OpsClient` |
| Keepa | 商品、价格历史、Offer、Buy Box、排名 | 正式 REST `/api/v1/keepa/*`、Keepa SDK/CLI |
| SellerSprite | 关键词、反查词、转化率、竞品流量 | SellerSprite SDK/CLI；当前正式 REST 文档未声明 SellerSprite 端点 |

## 3. 权威规范

本需求以当前仓库中的下列文件为依据：

- `opscli/skills/templates/ops-app-build-spec/SKILL.md`
- `opscli/skills/templates/ops-app-build-spec/references/frontend-standard.md`
- `opscli/skills/templates/ops-app-build-spec/references/backend-standard.md`
- `opscli/skills/templates/ops-app-build-spec/references/deployment-standard.md`
- `docs/spec/API调用规范.md`
- `docs/spec/SDK调用规范.md`
- `docs/guide/API使用文档.md`
- `docs/guide/SDK使用文档.md`

关键约束：

1. 前端默认只访问当前站点 `/api`，浏览器环境变量不得保存密钥。
2. FastAPI 路由只处理协议、参数和响应，业务编排进入 service，数据库访问进入 repository/db。
3. SQLite 只允许单写实例，不适合多实例共享、高并发持续写入或高频任务队列。
4. opscli REST API 当前正式覆盖 query 和 Keepa。
5. 应用运行时 `OpsClient` 从请求头 `x-ops-token` 取得身份，不走普通 `AuthClient`。
6. Keepa 和 SellerSprite 使用各自平台凭证，不能与 OPS 用户身份混用。
7. API Key、JWT、Cookie 和账号信息不得进入源码、前端产物、日志或项目文档。

## 4. 当前缺口

### 4.1 `ops-app-build-spec` 缺少数据开发路由

当前 Skill 负责项目盘点、技术栈、迁移、部署和项目文档，但没有独立的数据访问规范，也没有定义：

```text
发现真实数据需求
→ 识别数据源
→ 验证真实查询
→ 生成项目数据层
```

### 4.2 原数据 Skill 定位偏离

原 `ops-business-data-orchestrator` 只拆解多个查询、调用 `ops-dataset-query` / `ops-query-wizard`、汇总一次性结果，并明确禁止创建站点代码、API、数据库和同步任务，无法满足站点数据层建设需求。

### 4.3 运行时入口不统一

- OPS 可以复用应用运行时 `OpsClient`。
- Keepa 可以使用正式 opscli REST API。
- SellerSprite 当前未出现在正式 REST 端点清单中。

本轮不修改 `opscli/app/sdk`，因此新 Skill 必须基于现有能力生成代码，不能假设存在统一 Provider SDK。

## 5. 本次目标

1. 扩展 `ops-app-build-spec`，增加数据需求识别、数据规范路由和数据层验收。
2. 将 `ops-business-data-orchestrator` 改名并重写为 `ops-app-data-builder`。

目标闭环：

```text
自然语言业务需求
→ ops-app-build-spec 识别真实数据需求
→ ops-app-data-builder 分析数据产品
→ 调用对应数据 Skill 验证真实合同
→ 生成 FastAPI 数据层和前端 API 调用
→ 可选生成 SQLite 存储
→ 更新项目数据规范和测试
```

## 6. 新 Skill 命名与定位

### 6.1 名称

```text
ops-business-data-orchestrator
→ ops-app-data-builder
```

`ops-app` 明确只处理 opscli app 站点，`builder` 强调最终交付为数据层代码、接口、迁移和测试，避免被误认为一次性查询或经营分析 Skill。

### 6.2 新定位

`ops-app-data-builder` 负责：

- 读取当前站点上下文；
- 将页面需求拆成有限数据产品；
- 识别 OPS、Keepa、SellerSprite 或派生数据；
- 使用现有数据 Skill 验证真实合同；
- 选择实时查询、请求时组合或 SQLite 物化；
- 生成 FastAPI Client、Service、Repository、Schema 和 API；
- 生成前端 API Client 和类型；
- 生成数据规范、迁移和测试；
- 明确平台当前不支持的运行时能力。

## 7. 职责划分

```text
ops-app-build-spec
  └─ 识别站点结构和真实数据需求
       ↓
ops-app-data-builder
  └─ 验证数据合同并生成项目数据层
       ↓
站点 FastAPI 后端
  ├─ OPS：现有应用运行时 OpsClient
  ├─ Keepa：后端统一 opscli REST Client
  ├─ SellerSprite：第一阶段标记运行时阻塞
  └─ SQLite：保存允许共享的业务结果
       ↓
前端只调用当前站点 /api
```

### 7.1 `ops-app-build-spec`

负责识别真实数据需求、加载数据访问规范、委托 `$ops-app-data-builder`，并将数据源、接口、存储和安全边界纳入项目规范与发布检查。不负责选择具体数据集、猜字段或实现业务加工。

### 7.2 `ops-app-data-builder`

负责项目化需求分析、数据源路由、合同验证、执行模式判断、代码生成、文档、迁移和测试。不负责修改 `opscli/app/sdk`、新增服务端端点、创建认证协议或保存用户凭证。

### 7.3 运行期

本轮不修改 `opscli/app/sdk`。生成后的站点只执行普通 Python/FastAPI 代码，线上运行不加载 Skill。

## 8. 数据源路由

### 8.1 OPS 公司运营数据

开发期：需求清晰时使用 `$ops-dataset-query`；需求缺参、模糊或有歧义时使用 `$ops-query-wizard`；不得凭记忆猜数据集、字段、聚合、公式或筛选枚举。

运行期：

```text
浏览器
→ 站点 FastAPI /api
→ 现有应用运行时 OpsClient
→ OPS data-metrics
```

约束：

- 使用宿主请求中注入的 `x-ops-token`。
- 生成调用代码前必须检查当前站点或正式模板实际提供的运行时适配器导入路径、方法签名和错误合同；当前同步仓库只有规范引用，没有对应 SDK 源码，不得据此猜测实现。
- 不读取本地 opscli 登录凭证。
- 不在前端保存 Token。
- 不自行拼用户身份字段。
- 不直接调用 OPS 底层 API 绕过应用运行时身份通道。

默认执行模式为 `viewer-live`：按当前访问用户实时查询，默认不写入共享 SQLite。

### 8.2 Keepa

开发期使用 `$ops-keepa` 获取场景清单、验证参数和少量样本。

运行期：

```text
浏览器
→ 站点 FastAPI /api
→ 站点后端统一 OpscliApiClient
→ /api/v1/keepa/*
```

约束：

- API Key 仅存在于后端运行环境。
- 使用 `Authorization` Header。
- 必须检查 HTTP 状态码和统一信封 `success`。
- 长任务使用 `job_id` 幂等语义。
- 处理 `truncated`、`total_count` 和分页。
- 可按业务需要实时请求或物化到 SQLite。

计划使用的后端配置名称：

```text
OPSCLI_API_BASE_URL
OPSCLI_API_KEY
```

真实值不写入 `.env.example`。

### 8.3 SellerSprite

开发期使用 `$ops-seller-sprite` 验证场景、参数、返回结构和少量样本，可以生成数据规范、Pydantic Schema、Mock、SQLite 表设计和页面 API 合同。

当前正式 API 文档没有声明 SellerSprite REST 端点，本轮又不修改 `opscli/app/sdk`，因此第一阶段默认策略为：

```text
只完成开发合同和待接入边界
不生成伪造的正式线上调用代码
```

禁止站点读取本机 Cookie、执行 opscli CLI 子进程、临时连接 MCP、固化个人 session/JWT 或由前端直连 SellerSprite。

如果项目已经存在经过批准的 SellerSprite 运行时适配器，Skill 可以复用现有适配器，但不得自行发明新的认证入口。

## 9. 数据执行模式

### 9.1 `viewer-live`

适用于当前用户权限相关的 OPS 数据：每次通过当前请求身份查询，默认不写共享 SQLite。

### 9.2 `app-materialized`

适用于 Keepa 公共商品数据、已有合规服务身份的数据、用户录入和与访问者权限无关的共享结果：后端获取、规范化并批量写入 SQLite。

### 9.3 `hybrid`

适用于当前用户 OPS 数据与 Keepa 公共数据组合：OPS 实时查询，Keepa 从 SQLite 读取共享快照，由 FastAPI Service 请求时组合。

## 10. SQLite 边界

允许保存：

- Keepa 等应用共享第三方数据；
- 用户录入数据；
- 页面配置；
- 标签、备注和业务状态；
- 公共加工结果；
- 数据新鲜度；
- 同步执行记录。

默认禁止保存：

- 未按用户隔离的 OPS viewer 查询结果；
- API Key、JWT、Cookie、Authorization Header；
- 大 Excel、大文件和大型 BLOB；
- 高频任务队列数据。

写入要求：单写实例、网络调用在事务外、短事务、批量写入、结构变更走迁移、缓存类表有过期和清理策略。

## 11. 新 Skill 工作流

### 11.1 读取项目上下文

读取项目根目录、`AGENTS.md`、`docs/ops-app/project-spec.md`、前端页面和 API 封装、后端 API/service/db/schema、SQLite 模型和迁移、`.env.example` 与测试。不得只凭目录名猜项目结构。

### 11.2 识别数据产品

按业务判断拆解有限数据产品，不按页面卡片数量机械拆解，例如：

```text
sales_overview
inventory_risk
keepa_price_history
keyword_competition
product_operation_overview
```

### 11.3 验证数据合同

每个数据产品至少验证数据源、数据集或场景、维度、指标、筛选、粒度、时间字段、返回结构、分页、自然键、数据量、截断、空值和限制。

只获取足以验证合同的少量真实样本，不把真实样本提交进项目源码。

### 11.4 选择执行模式

按身份、实时性、额度、数据量和复用频率选择 `viewer-live`、`app-materialized` 或 `hybrid`。

### 11.5 生成数据规范

每个站点生成 `docs/ops-app/data-spec.md`。第一阶段不新增第二个运行时 YAML 权威源，避免配置漂移。

`data-spec.md` 至少包含页面与数据产品映射、数据源、查询合同、执行模式、后端 API、加工规则、SQLite 设计、数据新鲜度、环境变量、权限边界、测试策略和阻塞项，同时更新 `docs/ops-app/project-spec.md` 的数据层摘要。

### 11.6 生成项目代码

按项目现有结构生成实际需要的文件，典型职责为：

```text
backend/app/api/             FastAPI 路由
backend/app/clients/         OPS/opscli API 调用封装
backend/app/services/        业务编排和二次加工
backend/app/repositories/    SQLite 访问
backend/app/schemas/         Pydantic 合同
backend/app/models/          数据库模型
backend/app/db/              迁移与连接
backend/tests/               数据合同和接口测试
frontend/src/api/            前端 API Client
frontend/src/types/          前端类型
```

如果项目现有结构不同，应复用现有目录和命名，不为套模板进行无关重构。

### 11.7 验证

完成前检查：

- 前端只调用当前站点 `/api`；
- OPS 使用现有应用运行时身份通道；
- Keepa API Key 未进入前端和源码；
- SellerSprite 未生成当前不存在的正式 REST 调用；
- OPS viewer 数据未写入共享缓存；
- SQLite 符合单写和迁移约束；
- Pydantic Schema 与前端类型一致；
- API 错误处理检查统一信封；
- 测试覆盖主要数据合同和异常路径；
- 项目中没有真实业务数据文件和凭证。

## 12. `ops-app-build-spec` 计划修改

新增：

```text
opscli/skills/templates/ops-app-build-spec/references/data-access-standard.md
```

Reference 路由增加：

```markdown
| 页面需要真实业务数据 | `references/data-access-standard.md` |
```

执行流程增加：

```text
发现真实业务数据需求
→ 读取 data-access-standard.md
→ 使用 $ops-app-data-builder
```

项目文档和发布检查计划增加：

- `assessment.md` 记录当前数据源和违规调用；
- `migration-plan.md` 记录数据接口、存储和加工映射；
- `project-spec.md` 记录数据层摘要；
- 有真实数据需求时生成 `data-spec.md`；
- `development.md` 记录安全环境变量和 Mock 联调方式；
- `deployment.md` 记录 SQLite 持久化和第三方 Secret；
- 发布检查覆盖前端直连、`VITE_*` 密钥、运行时身份、真实数据文件和 SQLite 权限边界。

## 13. `ops-app-data-builder` 计划结构

```text
opscli/skills/templates/ops-app-data-builder/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── data/
│   └── VERSION.json
└── references/
    ├── data-layer-contract.md
    └── runtime-source-routing.md
```

`SKILL.md` 保留触发边界、必要输入、项目化工作流、依赖路由、安全边界、输出和完成条件；详细数据合同与运行时数据源差异分别下沉到两个 Reference。

## 14. 旧 Skill 迁移策略

计划直接将 `ops-business-data-orchestrator` 改名为 `ops-app-data-builder`。

当前旧版本为 `0.0.1`，且定位尚未稳定，推荐直接替换旧名称，不保留同功能兼容副本，避免两个 Skill 同时匹配数据需求。

旧 Skill 的一次性复合查询能力不再保留。后续临时查询继续使用 `ops-dataset-query`、`ops-query-wizard` 和对应第三方数据 Skill。

## 15. 计划修改文件

确认后预计修改：

### 15.1 Skill

- 删除 `opscli/skills/templates/ops-business-data-orchestrator/`
- 新增 `opscli/skills/templates/ops-app-data-builder/`
- 新增 `ops-app-build-spec/references/data-access-standard.md`
- 修改 `ops-app-build-spec/SKILL.md`
- 更新 `ops-app-build-spec/data/VERSION.json`

### 15.2 Manifest、评估与测试

- 修改 `opscli/skills/templates/manifest.json`
- 删除 `opscli/skills/evals/cases/ops-business-data-orchestrator.json`
- 新增 `opscli/skills/evals/cases/ops-app-data-builder.json`
- 删除 `tests/skills/test_ops_business_data_orchestrator_skill.py`
- 新增 `tests/skills/test_ops_app_data_builder_skill.py`
- 修改 `tests/skills/test_ops_app_build_spec_skill.py`

### 15.3 文档

- 本文作为新需求与设计文档。
- 原 `docs/design/业务取数编排Skill需求与设计.md` 在实施时由本文替代或删除。
- 原 `docs/plans/业务取数编排Skill落地计划.md` 在实施时替换为新计划。

## 16. 测试与评估计划

### 16.1 新 Skill 模板契约测试

覆盖名称、版本、安装、references、manifest、敏感信息、数据源路由、SellerSprite 阻塞、OPS viewer 存储边界以及项目交付物。

### 16.2 `ops-app-build-spec` 测试

覆盖数据访问 Reference、真实数据需求路由、`data-spec.md` 输出职责和发布安全检查。

### 16.3 静态 eval 场景

1. OPS 销售看板数据层构建。
2. OPS 模糊库存需求，需要查询向导。
3. OPS + Keepa 混合产品分析。
4. SellerSprite 页面需求，开发合同完成但运行时明确阻塞。
5. 单次明确查询，不应触发站点数据层构建。
6. 当前 Dashboard 页面编辑，不应触发。
7. 前端直连数据源改造请求，应改为站点 `/api`。
8. OPS viewer 数据共享落库请求，应阻止权限泄漏方案。

## 17. 验收标准

### 17.1 功能验收

1. `ops-app-build-spec` 可以稳定识别真实数据需求并路由新 Skill。
2. 新 Skill 只在标准站点数据层构建场景触发。
3. OPS 数据需求可验证数据集和字段并生成合规运行时代码要求。
4. Keepa 数据需求可验证正式场景并生成后端 REST 接入要求。
5. SellerSprite 不会生成当前不存在的正式 REST 调用。
6. 多数据源加工逻辑进入 FastAPI service，不进入前端。
7. 前端只调用站点 `/api`。
8. SQLite 不保存未隔离的 OPS viewer 数据。

### 17.2 安全验收

1. Skill 资源不包含 Token、API Key、Cookie、真实地址和本机绝对路径。
2. 生成规范禁止凭证进入源码、前端和日志。
3. OPS 用户身份不由业务请求体自报。
4. Keepa API Key 仅通过后端安全配置注入。
5. SellerSprite 不通过个人凭证绕行。

### 17.3 工程验收

1. 新 Skill 通过 `quick_validate.py`。
2. 专属测试通过。
3. `ops-app-build-spec` 回归测试通过。
4. manifest 和打包矩阵验证通过。
5. 静态 eval 达到配置要求。

## 18. 本轮明确不做

- 不修改 `opscli/app/sdk`。
- 不新增或修改 opscli REST API 服务端端点。
- 不实现 SellerSprite 正式 REST 接入。
- 不实现每用户第三方账号切换。
- 不实现 AppHub 自动签发应用 API Key。
- 不实现新的统一后台调度平台。
- 不修改 `opscli app create/init/push` 的命令数量和职责；通过 Skill 启动门禁确保全新项目先 `create/init` 拉取模板，再生成业务代码。
- 不让 Skill 成为线上站点运行依赖。
- 不在第一阶段引入新的运行时数据 YAML 权威源。

## 19. 确认记录

以下事项已于 2026-09-02 全部确认：

1. Skill 名称使用 `ops-app-data-builder`。
2. 直接删除旧名称，不保留兼容副本。
3. OPS viewer 数据默认实时查询，不写共享 SQLite。
4. Keepa 由站点后端通过正式 opscli REST API 调用，并使用后端 Secret。
5. SellerSprite 第一阶段只完成开发合同、Mock 和待接入边界，不生成正式线上调用。
6. 第一阶段仅生成 `docs/ops-app/data-spec.md`，暂不增加运行时 YAML。
7. 第一阶段不自动生成 OPS 无人值守同步；Keepa 定时同步仅在项目已有合规调度入口时复用。
8. 实施时由本文替代并删除旧需求设计与旧落地计划。

## 20. 实施顺序

1. 新增 `data-access-standard.md`。
2. 修改 `ops-app-build-spec` 的 Reference 路由、执行流程、输出和验收。
3. 创建 `ops-app-data-builder` 新目录和资源。
4. 删除旧 `ops-business-data-orchestrator`。
5. 更新 manifest、版本和 UI 元数据。
6. 更新测试与静态 eval。
7. 替换旧设计与计划文档。
8. 运行 Skill validator、定向测试、打包验证和静态 eval。

## 21. 最终需求摘要

本次改动不是新增一个线上取数服务，而是补齐 Codex 建站阶段的数据层构建能力：

```text
ops-app-build-spec 负责识别和委托
ops-app-data-builder 负责验证真实数据合同并生成站点数据层
现有 opscli/app/sdk 继续承担 OPS 应用运行时身份通道
正式 opscli REST API 承担 Keepa 运行时调用
SellerSprite 在第一阶段只完成开发合同和待接入边界
```

本文所列 Skill、manifest、测试、评估和规范改动已实施，并按落地计划完成验证。
