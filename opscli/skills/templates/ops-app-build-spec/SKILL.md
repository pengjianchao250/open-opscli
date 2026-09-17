---
name: ops-app-build-spec
description: AppHub 模板看板项目的开发规范。创建、开发、排错、评审、模板迁移重构或推送源码时使用，约束前端维护、项目边界和源码交付；按任务读取相关后端与数据规范。
---

# OPS 应用模板开发

统一模板仓库：`http://10.1.13.143:3000/aukeys-admin/template`，分支：`master`。模板提供应用代码和发布资产，Skill 维护跨项目开发规则；不另建脚手架。

本 Skill 中“站点”和“看板”含义相同，均指完整的 AppHub 应用项目；正文统一优先使用“看板”。“迁移”统一指基于当前统一模板审计旧看板业务能力，并在目标看板中按现行规范重新实现，即模板基础上的迁移重构，不指复制源码、搬运目录或继续扩建旧框架。

## Git 基础门禁

调用本 Skill 后第一步执行 `opscli app ensure-git --check --json`，在读取、创建或修改业务项目之前确认 Git 路径、版本、系统和原生架构。Git 正常时静默继续。

- 纯规范咨询、方案讨论和不访问本地项目的任务只检测，不安装软件或申请权限。
- 新建、迁移重构、模板克隆、仓库初始化、Git 状态或历史读取、提交和推送任务在 `ready=false` 时读取 [Git 环境规范](references/git-environment-standard.md)，执行 `opscli app ensure-git --install --json`。
- `elevation_required` 时由当前宿主申请权限后重试；`user_confirmation_required` 时等待用户完成系统安装界面后重新检测。不得由脚本绕过 UAC、Apple 系统许可或宿主审批。
- Git 门禁未通过时停止，不创建目录、AppHub 应用或 binding，不修改业务源码。

## 规范归属与读取

- 具体应用以后端实现为事实源：目标项目的 `backend/CLAUDE.md`、`docs/apphub-contract.md`、生成的 OpenAPI 和实际路由共同定义前后端合同。前端不得另行定义协议。
- 目录、依赖、命令和辅助函数以目标项目实际代码为准。发现 Skill、项目文档与代码冲突时列出证据和影响，不静默覆盖配置或用兼容分支掩盖漂移。
- 项目可补充业务约定；通用规则只在 Skill 维护，平台运行合同只在项目合同维护，避免多份文档重复。

| 本轮任务                                   | 读取                                                                                     |
| ------------------------------------------ | ---------------------------------------------------------------------------------------- |
| 前端页面、组件、样式或状态                 | [前端规范](references/frontend-standard.md)                                              |
| 修改前端请求、错误处理或前后端共享类型     | [前端规范](references/frontend-standard.md)、[后端红线](references/backend-redlines.md)  |
| 修改 FastAPI API、服务、任务或配置         | [后端红线](references/backend-redlines.md)                                               |
| SQLite 模型、事务、迁移或备份              | [SQLite 规范](references/sqlite-standard.md)                                             |
| 后端调用 opscli SDK 或 REST                | [opscli 接入规范](references/opscli-integration-standard.md)                             |
| 页面需要真实业务数据                       | [数据访问规范](references/data-access-standard.md)，按其要求使用 `$ops-app-data-builder` |
| Git 检测、安装、权限申请或环境排错         | [Git 环境规范](references/git-environment-standard.md)                                   |
| 已有看板迁移重构或补齐后端规范             | [迁移规范](references/migration-standard.md)                                             |
| 创建应用、绑定仓库、提交源码或检查交付条件 | [源码交付规范](references/deployment-standard.md)                                        |

首次接手或相关文件变化时，读取项目 `AGENTS.md`、`README.md` 和 `docs/apphub-contract.md`；进入子目录时读取适用的项目规则。后端改动与接口变化再核对 `backend/CLAUDE.md`、受影响路由、Pydantic Schema 和 OpenAPI；纯样式改动不额外读取后端全文。普通开发不读取 `assets/backend/` 中的全文规范。

## 任务分流

- **新建看板**：目标目录不存在或为空，按“新项目”流程完成模板拉取、Git 脱离、应用创建和业务仓库初始化，之后再开发业务。
- **已有合规模板看板开发**：项目已满足当前模板合同，直接在现有项目开发，不重复拉取模板、创建应用或初始化仓库。
- **已有看板迁移重构**：旧看板源码只读，目标看板必须是已核验或按“新项目”流程准备完成的模板项目；读取迁移规范，先建立业务能力基线，再在模板架构内重新实现。

### 迁移状态机门禁

明确执行已有看板迁移重构时，必须使用 `opscli app migrate` 保存机器可读状态，不能只在对话或临时 Markdown 中维护步骤：

1. 执行 `opscli app migrate init --source "<legacy-project>" --target "<target-project>" --json`，校验旧项目只读边界和目标模板合同，并生成审计快照、覆盖矩阵、UI 蓝图和迁移文档。
2. 读取 `.opscli/migration/current.json` 指向的 `coverage-matrix.json`、`ui-blueprint.json` 和 `audit-snapshot.json`，把候选证据整理成逐页逐模块覆盖项；候选文件数量不能当作迁移完成度。
3. 先一比一还原导航、路由、页面区域、模块顺序、父子层级、栅格与页面状态。执行 `opscli app migrate verify-ui --target "<target-project>" --json` 通过前，不开始真实数据接入。
4. UI 门禁通过后，使用 `$ops-app-data-builder` 逐个处理 `dynamic=true` 的模块，并把数据合同状态和证据回写覆盖矩阵。
5. 数据接入完成后依次执行 `opscli app migrate verify-data --target "<target-project>" --json` 和 `opscli app migrate verify-release --target "<target-project>" --json`；任一门禁失败时按 `detail.problems` 补齐，不绕过状态机宣布完成。
6. 最终回复前执行 `opscli app migrate status --target "<target-project>" --json`；只有 `phase=complete` 且 `delivery_ready=true` 才能使用“迁移完成”或“已交付”。其他阶段第一段必须明确写“当前为阶段性预览，尚未交付”，并报告 `next_required_gate`、未完成动态项和阻塞项。

迁移状态统一使用 `待实施`、`部分完成`、`已完成`、`blocked`、`deferred_attachment`。一个模块只有在 UI 布局、真实数据合同、业务交互、页面状态和验收证据全部完成后才能标记为 `已完成`。每完成一个模块立即更新覆盖矩阵并执行 `opscli app migrate export --target "<target-project>" --json`，不要在任务末尾一次性补写。

### AppHub 真实取数交付门禁

页面需要 OPS、Keepa 或 SellerSprite 数据时，必须委托 `$ops-app-data-builder` 完成“需求识别 → 正式查询尝试 → 合同固化 → 业务 API/页面接入”的闭环。业务范围已经足够明确时，不得因为用户没有提供 dataset、field、scenario 或轮询参数而停止；这些技术细节由对应查询 Skill 验证并回填。

- 没有真实查询尝试的产品只能保持 `candidate`，不得直接交付 `blocked` 页面或固定返回 `blocked` 的 API。
- 查询成功但零行属于合同已验证，页面显示“暂无数据”，不显示“待接入”或“尚未完成在线验证”。
- 认证外的临时服务异常、超时和上游不可用属于 `degraded`；按 `ops-feedback` 规则处理后继续其他模块，不把临时故障解释成正式能力缺失。
- 只有正式能力不支持、权限缺失、业务口径无法确认或运行时硬前置缺失才允许 `blocked`，并必须提供结构化阻塞证据。
- 交付前检查项目的 `docs/ops-app/data-contracts.json`，运行 `ops-app-data-builder` 提供的 `scripts/validate_data_contracts.py <contract-file> --mode delivery --project-root <project-directory>`；校验失败时不能把项目报告为真实取数完成。
- 合同 `verified` 只表示上游数据集、字段、参数和响应已确认；项目还必须记录 `implementation_status=verified`，并提供后端 API、service、Pydantic Schema、前端消费者、测试和 OpenAPI 工件。`contract_verified_only`、`layout_only`、`not_started`、`in_progress` 都不是交付完成。
- 一个数据产品合同验证成功后继续处理全部未阻塞动态项，不得停在首个成功产品；局部 `degraded`、`blocked` 或 `deferred_attachment` 只影响对应项，但会使整体 `delivery_ready=false`。
- 页面仅展示业务可理解的失败提示；“合同未验证”“字段尚未补齐”等内部诊断保留在 data-spec、合同凭证、日志和交付报告。

旧看板目录和目标看板目录不得混用。目录身份、模板合同或迁移目标无法确认时先停止，不猜测、不覆盖。

## 新项目

1. 确认 Git 基础门禁已通过，再确认应用展示名称和目标目录不存在或为空。
2. 使用 `opscli` 正式命令克隆模板；Git 检测、模板 clone 和模板根 `.git` 清理均由 `opscli` 自身运行时完成：

   ```bash
   opscli app clone-template "<project-directory>" --json
   ```

   命令直接 clone 到目标目录，成功后立即删除项目根目录 `.git` 并验证其不存在；保留 `.gitignore` 和原有项目说明，不使用临时目录。任一步失败都停止，禁止手动跳过清理继续开发。

3. 模板准备成功后立即创建 AppHub 应用并写入本地 binding：

   ```bash
   opscli app create "<app-name>" --path "<project-directory>" --json
   ```

4. `create` 成功后立即初始化全新 Git 仓库并绑定业务仓库：

   ```bash
   opscli app init "<project-directory>" --json
   ```

5. 核对独立 Git 根、`master` 分支和 `origin`，确认 `origin` 不指向统一模板仓库；首次绑定目标远端必须已有 `git-bind-preflight` 成功证据，正常后续 push 不重复执行空仓库预检。确认 `.opscli/app.json.app_id == app.yaml.app_id`，并按部署规范检查 binding。
6. 开发前读取目标项目的规则与本轮参考文件，再实现业务需求。

clone 并脱离模板 Git 元数据、`create` 和 `init` 是开始开发前连续执行的必需步骤。`create/init` 不负责获取模板。任何一步失败都停止后续开发，业务代码不得推回模板仓库。不得运行项目生成器、手写替代脚手架，或从 Skill 复制应用代码与发布资产。

## 已有看板与项目约定

应用唯一身份是严格匹配 `^[0-9A-Za-z]{5}$`、区分大小写的 `app_id`。只接受 schema v4 的 `.opscli/app.json`；v1、v2、v3、`site_name/site_id/created_by` 旧字段、非法 ID 或缺失环境标识时立即停止，不迁移、不备份替换。仅在目录完全没有 binding 时，核对平台应用 ID 后执行 `opscli app init "<project-directory>" --app-id "<app_id>" --json`。`--app` 仅核对 slug，不能查询、选择、恢复或创建应用。

创建超时或失败后，在原目录使用相同名称、账号和环境重试 `create`；保留 `.opscli/creation.json` 的本地创建意图和并发保护记录，但不得把其中 UUID 作为 `Idempotency-Key` 发送给 AppHub。服务端按同一 owner 和 slug 幂等重入。真实 `app_id` 同时写入 `app.yaml` 和本地 binding；slug 只保留在 AppHub 与 binding 中。仓库地址只使用平台返回的 `repo_url`，不得从 slug 拼接。

Git 凭据由 `app init` 和 `app push` 自动恢复：现有凭据探测成功时直接复用；明确属于认证失败时，平台未绑定凭据则首次签发，平台已绑定凭据则自动请求服务端轮换。非认证类 Git 失败不得触发凭据刷新，用户无需操作或理解轮换参数。

业务项目绑定自己的远端后，不能只根据 remote 判断模板身份。根目录应有 `app.yaml`、`AGENTS.md`、`docs/apphub-contract.md`、`frontend/`、`backend/app.py` 和 `backend/CLAUDE.md`，运行入口与项目合同一致。合同缺失时读取迁移规范，不在旧看板目录重新初始化、继续扩建旧框架或批量覆盖。

无论新项目还是已绑定项目，都沿用实际项目规则：

- Skill 的安装和调用入口由模板项目维护，本 Skill 不注入项目规则或宿主钩子。
- `AGENTS.md` 保持简短，只放项目约束和规范入口；保留原有业务说明与其他工具规则。开发命令继续维护在 `README.md`，不为普通需求强制生成另一套 `project-spec/development/deployment` 文档。
- 只有新增长期有效的业务约定、维护限制或验证方式时，才更新对应项目文档，并引用实际源码或测试。数据层需要的 `docs/ops-app/data-spec.md` 等文档仍按数据访问规范维护。
- 迁移项目缺少后端规范时，可按迁移规范从 `assets/backend/` 补齐；这些资产只有规范，不含构建或发布脚手架。

## 开发纪律

- 动手前查现有实现和调用方。较大改动简要说明目标、涉及模块及可观察的验收结果；小改动直接处理，不强制任务目录、PRD、多 Agent 或重复确认。
- 技术事实从代码、测试和配置查证；只向用户确认项目无法回答的业务口径、范围或验收行为。不让非开发用户选择实现框架。
- 优先复用项目已有能力和依赖。仅实现当前需求；不提前设计插件系统、万能组件、配置驱动框架或未使用的扩展点。
- 同一业务概念需要一起变化时再抽取公共能力；外观相似或字面量相同不构成抽象理由。文件按职责拆分，不追求最少文件或固定行数。
- 只修改当前需求相关代码，保留用户已有修改；清理本次产生的无用代码，不顺手格式化或重构无关模块。简短注释说明业务规则与特殊处理的原因。
- 改公共组件、请求函数或状态字段时搜索全部调用方，检查影响；修复行为实际所属位置，避免调用处层层补丁。不得用前端兼容分支掩盖后端合同漂移。
- 页面涉及真实数据时按数据规范交给数据 Skill；本 Skill 不选择或猜测数据集、字段、聚合、筛选、第三方场景或运行时签名。前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 不读取、输出或提交真实密钥、本地运行数据库和业务数据文件。已初始化的空白模板库按项目合同保留。
- 执行沿用用户已明确授权的范围和宿主权限。范围内的检查、修复不重复求确认；提交、推送、部署和真实数据写入须有相应授权，加载本 Skill 不授予这些权限。

- 无论新项目还是已绑定项目，开发前都先读取目标项目的 `AGENTS.md`、`backend/CLAUDE.md`、`docs/apphub-contract.md` 和 `README.md`。
- 修改前端、后端、SQLite 或 opscli 接入时读取对应规范，只执行与当前改动相关的条款。
- 前端请求或共享类型变化时，先确认后端路由、Schema 和 OpenAPI，再改前端；不得用前端兼容分支掩盖后端合同漂移。
- 页面需要真实业务数据时必须读取取数规范并使用 `$ops-app-data-builder`；不选择或猜测数据集、字段、聚合、筛选、第三方场景、凭证、SDK 签名或运行时入口。
- 本 Skill 所称看板是 AppHub 应用项目。只有当前会话同时提供 `dashboard_session_get_context` 和 `dashboard-tools.v2`、页面上下文返回运营系统中的真实平台仪表盘配置对象且用户目标是直接编辑该对象时，才使用 Dashboard 专用 Skill；URL、路由名、页面标题或“Dashboard/看板”字样不能作为判断依据。AppHub 仓库中的看板源码仍按本 Skill 和真实数据流程处理。
- 前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite；所有线上取数都经过当前站点 FastAPI `/api`。
- 只修改当前业务需要的代码，保留用户已有修改和模板基础能力。
- 不读取、输出或提交真实密钥、本地数据库和业务数据文件。
- 用户未授权时，不安装依赖、启动服务、执行数据库写入、提交、推送或部署。
- 迁移重构开始前按迁移规范记录项目身份、模板合同、业务能力基线、迁移风险、未识别项和预计文件变更。
- 涉及真实数据时记录数据用途、现有数据源、调用路径、前端直连或凭证风险，以及第三方原始数据、异步任务和用户私有加工结果的分层情况。
## 验证与源码交付

## 本地开发预览

- 用户明确提出“本地启动当前项目”“本地预览”“启动开发环境”或“边改边看”等请求时，视为已授权启动本地服务，统一调用 `opscli app dev <project-root>`。
- 不得绕过 `opscli app dev` 直接调用 `uvicorn`、`npm run dev` 或 `pnpm dev`；该命令负责生成和校验 `.env`、准备依赖、启动后端 reload 与前端 Vite 热更新，并在失败时阻止服务继续启动。
- 默认启动由命令从后端 `8035`、前端 `5173` 起自动选择空闲端口；不得为释放默认端口而停止、重启或干扰其他项目，也不得在命令正常工作时手动猜测端口。用户显式指定端口时遵循命令的严格校验结果。
- 启动成功后向用户报告命令实际输出的前后端 URL，不得仍按默认端口回复。
- 启动器输出 URL 后，必须另行执行 `opscli app dev-status <project-root> --json` 验证归属；只有 `success=true`、`running=true`、`identity_verified=true` 且 `project_root` 与当前项目解析后的绝对路径一致时，才能报告“当前项目正在运行”。
- 单独请求健康检查得到 HTTP 200、发现端口可连接、看到浏览器已有页面或复用旧标签页，都不能证明服务属于当前项目；不得据此把其他项目或后来复用同一端口的进程认领为当前项目。
- `opscli app dev` 所在命令会话退出、失败或被宿主回收后，必须重新执行 `dev-status`；结果不是 `running` 时明确报告服务已停止，不得继续声称“保持运行”。浏览器只打开 `dev-status` 返回的 `frontend_url`。
- 开发模式使用 Vite 按需编译和热更新，不要求先执行生产版前端构建；一次构建后启动仍使用项目已有的 `scripts/start.ps1` 或 `scripts/start.sh`。
- `opscli app dev` 是纯本地编排命令，不创建、修改或推送 AppHub 应用，不改变 `app.yaml`、Dockerfile、Nixpacks 或生产端口合同。

- 完成后检查实际 diff，包括新增文件和已有暂存改动，确认没有无关重构、重复基础设施、调试残留或通过关闭规则绕过检查。
- 真实 OPS 数据交付还必须确认正式查询使用在线验证后的精确 `dataset_alias`、`table_id` 和 `field_name`，不存在关键词打分、`includes`、子串搜索、`global_alias` 查询回退或最相近字段替换；相似字段、字段缺失和 metadata 漂移测试已经覆盖。
- 按改动运行相关行为测试；Bug 修复应有能复现问题的验证。文案、间距等低风险改动不机械新增测试。已有无关失败要说明，不删测试以换取通过。
- 源码交付前按部署规范执行前端测试、生产构建及项目合同要求的检查；命令取实际项目，不能编造尚不存在的 `lint/typecheck`。
- 页面主流程、布局、真实联调、平台环境分别需要对应证据；构建通过不能代替浏览器或线上验收。
- 提交前重新读取部署规范，确认本次完整文件范围、binding 与目标仓库。用户明确授权后执行 `opscli app push "<project-directory>" --message "<summary>"`；不绕过它直接 Push，不创建第二条 release。
- push 成功只表示源码到达远端。线上构建、发布、健康状态和回滚由 AppHub 处理，没有平台证据时不得报告已部署。
- `opscli app push` 返回 `pushed=true` 时，Codex 最终回复统一原样使用：“推送成功；运营系统将自动部署并发布当前站点，您可以前往运营系统查看发布状态、或进行站点权限设置。”该提示描述后续异步流程，不表示当前已经部署或发布成功。
- `opscli app push` 返回 `pushed=false` 时，说明远端源码已是最新版本；按命令结果说明无需重复推送，不使用上述成功提示。

## 错误与输出

模板克隆或 Git 清理失败时保留原始错误并停止后续初始化；合同无法核实时保留已验证部分，不伪造实现。迁移重构无法确认业务行为或目标看板不满足模板门禁时保持旧看板只读并停止目标实现。

`opscli` CLI 或相关 MCP 工具失败时，立即按 `ops-feedback` 规范提交结构化反馈并返回 `feedback_uuid`；认证未授权、用户取消和五分钟内已反馈的同一错误除外。

先判断目标是否已经符合模板合同。需要迁移重构时读取唯一的迁移规范，在独立模板项目中重新实现业务能力；旧看板保持只读和可回退，不复制旧源码或旧架构。

## 提交与部署

首次源码交付或后续推送时读取部署规范。Skill 负责配置校验、当前 opscli 命令边界和提交前检查；源码推送后的构建、自动 release、健康状态和回滚由线上 AppHub 处理。Skill 不绕过 `opscli app push` 直接 Push，也不调用 release 创建接口生成第二条 release。

发布态固定为一个 FastAPI 进程托管 Vite 构建产物、API 和健康检查：

```text
frontend/
backend/
migrations/
tests/
docs/ops-app/
app.yaml
requirements.txt
nixpacks.toml
Dockerfile
.dockerignore
.gitignore
```

只创建实际使用的目录和功能。全新 opscli app 必须在模板项目上改造，不自行初始化空项目或生成第二套脚手架；已有项目按支持结论补齐必要结构。任何项目都不得生成虚假业务接口、业务表或示例生产数据。

生成或更新：

- `docs/ops-app/project-spec.md`：当前技术栈、目录、命令、路由、接口、数据和约束。
- 有真实数据需求时生成 `docs/ops-app/data-spec.md`：数据产品、真实合同、执行模式、站点 API、加工、SQLite、安全、测试和阻塞项。
- 第一阶段不增加运行时数据 YAML，避免形成第二套配置权威源。
- `docs/ops-app/development.md`：本地开发、环境变量和联调方式。
- `docs/ops-app/deployment.md`：构建、持久化、发布检查和回滚说明。
- 根目录 `AGENTS.md`：只写简短受管区块，引用上述规范；已有文件时保留其他内容。

保留现有前端包管理器及唯一锁文件。依赖安装、服务启动、数据库迁移和发布仍遵守当前宿主的授权要求。

### 5. 唯一发布声明

根目录 `app.yaml` 是应用发布声明的唯一来源。模板中的 `app_id/title` 是示例身份；执行 `opscli app create` 后，以 AppHub 返回的真实 `app_id` 和创建时确认的展示名称回填 `app.yaml.app_id/title`。顶层 `name` 已废弃，不得补回；slug 只存在于 AppHub 与 `.opscli/app.json`。其他运行时、入口、服务、数据集和可见范围字段按项目实际需求维护；保持：

```yaml
apiVersion: apps.aukeys/v1
app_id: Ab123
title: 示例应用
database:
  kind: sqlite
  path: /data/app.db
```

禁止在应用代码、环境文件、构建文件或前端配置中重复维护平台身份、公开前缀或发布地址。`app.yaml` 必须位于独立 Git 仓库根目录，发布分支必须为 `master`；模板源目录嵌套在另一个仓库中时先迁出并初始化独立仓库。

首次源码交付前确认根目录存在 schema v4 的 `.opscli/app.json`，binding 和 `app.yaml` 中的 `app_id` 均严格匹配 `^[0-9A-Za-z]{5}$`、大小写完全一致，`default_branch` 固定为 `master`，且 `app.yaml` 不含顶层 `name`。slug、仓库、Owner 和 Git 信息只保留在本地 binding；`.gitignore` 必须忽略 `.opscli/`。

已有看板迁移重构时按计划补齐目标项目的根级资产；全新模板缺少这些必需资产时报告模板问题，不静默复制另一套基线：

- `assets/nixpacks.toml` → `nixpacks.toml`
- `assets/Dockerfile` → `Dockerfile`
- `assets/requirements.txt` → `requirements.txt`
- `assets/.dockerignore` → `.dockerignore`

### 6. 运行合同

当前路由合同为 `root-v1`。浏览器公开前缀由平台在鉴权后移除，应用只接收根路径请求：

- Vite 固定 `base: './'`，路由、静态资源、Axios 和 WebSocket 使用相对 URL。
- FastAPI 先注册 `/__apphub_healthz`、`/api/*` 和 WebSocket，再挂载静态资源，SPA fallback 最后注册。
- FastAPI 不读取公开前缀，不设置框架子路径参数。
- Vite `dist` 由同一个 FastAPI 进程托管，不启动第二个生产 Web 进程。
- SQLite 只读取 `SQLITE_PATH`；模板库为 `data/app.db`，本地运行库为已忽略的 `.data/app.db`，容器运行库为 `/data/app.db`。平台只把命名卷挂到 `/data`，不注入数据库路径变量。

### 7. 构建与源码交付

项目构建合同以 AppHub 的 Nixpacks 运行环境为准：

- `nixpacks.toml` 分别在 `install` 与 `python:install` 使用 `...` 保留 Node/Python provider 计划；平台 SDK 导入门禁追加到 `python:install`，Vite 构建显式依赖两个安装阶段，并以平台同款命令启动 FastAPI。
- 根目录 `requirements.txt` 中普通第三方依赖使用 `==` 精确锁定；平台 SDK 使用真实包 `aukeys-opscli>=0.0.129`，并在构建阶段验证 `import opscli.app`。若索引中尚无兼容正式版本，停止源码交付并联系 IT，不得用本地同名包绕过。
- 禁止创建本地 `opscli/` 包、同名模块或路径依赖来绕过真实包安装。
- `Dockerfile` 只用于本地、CI 和可复现构建，不改变 AppHub 的 Nixpacks 运行合同。
- 启动命令为 `uvicorn backend.app:app --host 0.0.0.0 --port 8000`，数据库初始化和迁移遵循项目合同与 AppHub 运行时能力，不调用已废弃的项目侧部署命令。
- 平台健康检查固定为 `/__apphub_healthz`，必须快速返回 200，且不依赖业务查询。

源码交付前必须确认：

- `app.yaml` 能通过当前 schema，入口文件存在，Git 根独立且当前分支为 `master`。
- `requirements.txt` 的普通依赖全部精确锁定，真实 `aukeys-opscli` 通过兼容模块导入检查。
- 前端合同检查、前端测试和生产构建、后端测试、健康检查通过。
- 已运行 `scripts/validate_frontend_contracts.py <project-root>`，前端不存在字符串组件模板、`Vue.compile` 或从 `vue` 导入运行时 `compile`。
- Nixpacks 与 Dockerfile 的构建产物、启动模块、端口和健康路径一致。
- 构建产物使用相对 URL，根路径页面、静态资源、SPA 刷新、API 和 WebSocket 可用。
- `.data/` 和 SQLite 文件不进入源码或构建产物。
- 根目录 `.gitignore` 忽略 `.opscli/`，`.opscli/app.json` 未被跟踪或暂存；`app.yaml` 必须保留在源码中。
- 根目录 `.dockerignore` 排除依赖目录、构建缓存、本地数据库、环境文件和密钥，同时保留 `app.yaml`、锁文件、源码和必要构建资产。
- Dockerfile 使用精确 `COPY` 分层和 BuildKit 缓存；禁止无边界 `COPY . .`，但必须复制依赖清单、锁文件、源码和必要配置。
- 后端依赖统一使用 `uv`、`pyproject.toml`、`uv.lock`；项目不得自行派生 AppHub 公开路径、Compose service 名或线上镜像名。
- 模板项目开发只要求 Node.js 主版本大于 22；补丁版本 engine 警告允许记录到评估文档，不作为构建或测试的阻断条件。
- 前后端构建、测试和健康检查通过。
- 构建产物引用部署前缀，本地开发仍使用根路径。
- SPA 嵌套路由刷新、API 访问和容器重启后的数据持久化通过。
- 前端只调用当前站点 `/api`，没有直连 OPS、opscli REST、Keepa 或 SellerSprite。
- `VITE_*`、源码、构建产物、日志和 SQLite 中没有 API Key、JWT、Cookie 或完整鉴权头。
- OPS viewer 运行时使用 `OPSCLI_MCP_REST_API_BASE_URL` 对应的 opscli-mcp REST 接口：查询固定为 `POST /api/v1/query/simple`，元数据固定为 `GET /api/v1/query/metadata`；不得生成 `/v1/data-metrics/viewer/*` 或让前端直连该服务。
- OPS 使用实际项目中经过批准的应用运行时身份适配器，未隔离的 viewer 数据没有写入共享 SQLite。
- Keepa 页面运行时只使用正式 `POST /api/v1/keepa/run`，请求级 `ThirdPartyApiClient` 复用模板 `get_query_credentials()` 解析出的 `viewer/session/local` 身份。
- SellerSprite 使用正式异步 jobs 或 Listing Analysis 接口，按当前 `owner_user_id` 持久化并复用 pending `job_id`，成功 JSON 结果只进入当前用户私有快照。
- OPS、Keepa 和 SellerSprite 只共用 `OPSCLI_MCP_REST_API_BASE_URL`；生产注入 `https://ops.mcp.xenkee.com`，预发布注入 `https://mcp.ops.aukeyit.com`，不得设置默认环境、读取共享 API Key 或旧变量别名。该地址只用于 `/api/v1/*` REST，不用于 `/mcp` 或 `/sse`。
- 第三方调用只从已校验的 `QueryCredentials` 重建允许的 Header，不盲目透传浏览器 Header，不把凭证写入请求体、前端、日志、SQLite 或源码，也不在三种模式间回退。
- `third_party_source_snapshot` 和 `third_party_async_job` 都使用 `UNIQUE(owner_user_id, provider, request_hash)`；XLS/XLSX 和临时下载 URL 不写入 SQLite。
- `docs/ops-app/data-spec.md` 与实际 Pydantic Schema、前端类型、迁移和运行时能力一致。
- 具备浏览器条件时已检查业务模块正文和控制台 Vue warning；生产构建成功不能替代运行时验收。

未获得启动服务许可时，只执行静态检查、测试和构建，不启动容器。

源码交付获得用户确认后，由 Codex 执行 `opscli app push <root> --message <summary>`。返回 `pushed=true` 时按前述统一提示回复用户；该命令成功只表示源码到达应用远端仓库，随后 `opscli app` 职责结束。
应用发布、构建排队、版本状态、线上 URL、健康检查和回滚由 AppHub 或其他发布平台负责，本 Skill 不调用或指导调用 `opscli app` 发布命令。
没有线上平台证据时，不得把 push、构建或镜像生成报告成已发布或已部署。

## 错误处理

- 模板克隆或 `.git` 清理验证失败：保留原始错误并停止，不退回旧脚手架，不执行 `create/init`。
- 模板合同冲突：列出证据和影响，不猜测。
- 迁移无法保持业务行为：停止迁移，保留源实现和失败证据。
- `opscli` CLI 或 MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。
- 数据合同无法验证、OPS 运行时适配器缺失、第三方场景未验证或结果格式不支持目标数据产品：保留已验证部分，在 data-spec 标记阻塞，不伪造调用代码。

## 输出

简要报告修改文件、实际验证、交付状态和阻塞项。迁移任务必须以 `opscli app migrate status` 的 `delivery_ready` 为最终表述依据；`delivery_ready=false` 时明确写“阶段性预览，尚未交付”。未执行的测试、构建、浏览器验收或线上部署不得写成通过。
