# AppHub 源码复制迁移薄适配需求

> 状态：已实施并完成迁移验证  
> 适用仓库：`open-opscli`  
> AppHub 事实源：`ops-apphub` 当前已实现源码  
> 本文同时记录已确认需求、实施边界与最终验证结果。

## 1. 背景

`ops-app-build-spec` 当前已经形成一条源码复制迁移流程：源目录只读、目标目录隔离、排除依赖和缓存、生成迁移状态、扫描启动方式、创建 AppHub 应用、初始化 Git、执行迁移验证并在推送前校验指纹。

该流程的总体方向正确，本质上是在原项目外增加一层薄适配，使原项目满足 AppHub 的发布和运行门禁，而不是把原项目重构成标准模板项目。

当前主要问题不是迁移流程缺失，而是薄适配层使用了标准 FastAPI/Vite/Nixpacks 模板作为门禁模型，导致部分原本可以通过 Dockerfile 发布的项目被错误要求具备：

- `backend/app.py`
- `frontend/package.json`
- `nixpacks.toml`
- `backend.app:app`
- Python 依赖声明文件

这些要求与 `ops-apphub` 当前实际发布实现不完全一致。

## 2. 已确认决策

### 2.1 AppHub 不改动

本需求不修改 `ops-apphub`：

- 不增加合同接口。
- 不增加合同导出模块。
- 不调整 AppHub 发布校验。
- 不调整 Coolify 创建和部署行为。
- 不调整网关、健康检查或数据库实现。

`ops-apphub` 仅作为本需求确认平台真实门禁的源码事实源。

### 2.2 保留薄适配架构

继续保留现有迁移架构：

```text
源项目只读扫描
  → 隔离复制到目标目录
  → 识别原项目运行证据
  → 建立最小 AppHub 薄适配
  → 创建并绑定 AppHub 应用
  → 验证迁移合同
  → 推送源码
```

不引入新的大型迁移框架，不要求所有项目统一成同一种目录结构。

### 2.3 新建流程保持不变

以下流程不得受本需求影响：

- 标准模板克隆。
- `opscli app create`。
- `opscli app init`。
- 普通非迁移项目的 `opscli app push`。
- `TemplateService` 的现有行为。
- 标准模板项目的开发规范和目录约定。

本需求只适用于本地项目标记满足以下条件的项目：

```json
{
  "origin_type": "migration_copy"
}
```

## 3. AppHub 实际门禁基线

本需求以 `ops-apphub` 当前源码实现为准，而不是以历史文档或本机模板项目为准。

### 3.1 发布清单

- 根目录必须存在 `app.yaml`。
- `apiVersion` 必须为 `apps.aukeys/v1`。
- `app_id` 必须是五位大小写敏感字母或数字。
- `app_id` 必须与目标 AppHub 应用一致。
- `app.yaml` 未知字段禁止通过。
- 顶层不接受历史字段 `name`。

源码依据：`ops-apphub/apphub/schemas/appyaml.py`、`ops-apphub/apphub/publish/validate.py`。

### 3.2 构建和启动

- 根目录必须存在 `Dockerfile`。
- AppHub 使用 Dockerfile build pack。
- 应用构建方式和启动命令由 Dockerfile 的 `ENTRYPOINT` 或 `CMD` 负责。
- AppHub 不要求 `nixpacks.toml`。
- AppHub 不要求 FastAPI。
- AppHub 不要求 `backend/app.py`。
- AppHub 不要求入口为 `backend.app:app`。

源码依据：`ops-apphub/apphub/publish/validate.py`、`ops-apphub/apphub/publish/steps_deploy.py`。

### 3.3 运行合同

- 容器服务端口固定为 `8000`。
- 平台注入 `PORT=8000`。
- 应用必须提供 `/__apphub_healthz`。
- 健康检查必须直接返回 HTTP 200；重定向不视为通过。
- Dockerfile 必须最终启动一个能够持续提供服务的前台进程。

源码依据：`ops-apphub/apphub/runtime/command.py`、`ops-apphub/apphub/publish/steps_deploy.py`。

### 3.4 路由合同

- 对外地址使用 `/ops-app/{app_id}/{slug}/`。
- 网关在转发到应用前移除公开前缀。
- 应用内部接收根路径 `/`、`/api/...`、`/assets/...`。
- 浏览器中的资源地址、请求地址和表单地址必须使用相对 URL。
- 浏览器根绝对路径 `/api/...`、`/assets/...`、`/styles.css` 等不得作为迁移交付结果。

源码依据：`ops-apphub/apphub/runtime/labels.py`、`ops-apphub/apphub/paths.py`。

### 3.5 SQLite 合同

- 仅在 `app.yaml` 声明 SQLite 数据库时应用数据库规则。
- 新数据库应用必须提供合法的 `compose.apphub.yaml`。
- 已发布数据库应用不能修改或删除 `database.kind` 和 `database.path`。
- 未发现明确数据库证据时，迁移流程不得猜测并自动声明 SQLite。

源码依据：`ops-apphub/apphub/publish/validate.py`。

### 3.6 服务端最终门禁

以下检查继续由 AppHub 服务端负责，Skill 不需要完整复制其实现：

- 提交 SHA 合法。
- 提交位于 `master`。
- 提交归档大小不超过平台限制。
- 服务端 gitleaks 扫描。
- Dockerfile 实际构建。
- Coolify 容器运行状态。
- 容器直连健康检查。
- 网关健康检查。

本地迁移验证只能提前发现明确问题，不能替代 AppHub 最终发布裁决。

## 4. 目标

### 4.1 核心目标

- 保留源码复制迁移现有能力。
- 让薄适配精确匹配 AppHub 实际门禁。
- 不再把标准模板目录结构当成平台发布合同。
- 本机不存在模板项目时仍然能够完成源码迁移。
- 尽可能保留原项目框架、目录、包管理器、业务代码和启动方式。
- 只在迁移目标副本中增加必要的 AppHub 适配。
- 保证新建和普通推送流程行为不变。

### 4.2 质量目标

- 所有自动判断必须能够给出仓库证据。
- 无法确认的运行方式进入人工适配，不得猜测。
- 自动生成文件必须可追踪、可重复生成并进入迁移清单。
- 迁移验证结果必须可以被 push 前门禁复验。
- 验证通过后源码变化必须导致验证清单过期。

## 5. 非目标

- 不把旧项目重构成标准模板项目。
- 不强制迁移到 FastAPI、Vite 或 Vue。
- 不强制创建 `backend/` 或 `frontend/`。
- 不强制增加 Nixpacks。
- 不设计新的 AppHub 发布协议。
- 不修改 AppHub 服务端。
- 不自动猜测数据库、业务 API 或第三方依赖。
- 不绕过 AppHub 服务端发布门禁。
- 不在源项目目录写入文件。
- 不以生成伪造占位文件的方式通过门禁。

## 6. 薄适配职责

### 6.1 必须处理

薄适配层必须能够根据项目实际证据完成或指导完成：

1. 生成或修正根目录 `Dockerfile`。
2. 创建 AppHub 应用后回填根目录 `app.yaml` 的真实身份。
3. 让生产服务监听环境变量 `PORT`，缺省值可为 `8000`。
4. 提供 `/__apphub_healthz` 并直接返回 HTTP 200。
5. 修复浏览器可见的根绝对 URL。
6. 确保运行时使用的静态文件、数据快照和配置进入最终镜像。
7. 保证 `.gitignore` 忽略 `.opscli/` 和本地运行数据。
8. 保证 `.dockerignore` 不会误排除生产运行所需文件。
9. 检测到明确 SQLite 声明时检查 `compose.apphub.yaml`。
10. 保留原项目唯一包管理器和锁文件。

### 6.2 禁止处理

薄适配层禁止：

- 为满足旧门禁创建无业务作用的 `backend/app.py`。
- 为满足旧门禁创建无业务作用的 `frontend/package.json`。
- 生成不参与 AppHub 构建的 `nixpacks.toml`。
- 把任意项目入口改写成 `backend.app:app`。
- 未经证据确认就修改业务进程模型。
- 未经证据确认就声明 SQLite。
- 覆盖项目已有且有效的 Dockerfile。
- 在源目录执行格式化、依赖安装、构建或源码修改。

## 7. 启动识别需求

### 7.1 当前问题

当前实现只有同时识别到 backend 和 frontend 时才把启动状态标记为 `ready`。该规则不能覆盖 Node-only、Python-only、Streamlit、Gradio、静态站点加 HTTP Server，以及根级混合项目。

### 7.2 调整要求

启动识别应回答以下问题：

- 是否存在明确的生产构建命令。
- 是否存在明确的生产启动命令。
- 哪个进程负责监听 HTTP 端口。
- 如何把监听端口调整为 `PORT`。
- 当前是否已经提供 AppHub 健康路径。
- 哪些目录和文件是生产运行时资产。
- Dockerfile 最终阶段是否包含这些资产。

启动状态判定应改为：

```text
存在可执行且证据明确的生产启动路径 → ready
存在候选入口但无法安全确定适配方式 → startup_manual_required
未发现可用服务入口 → startup_manual_required
```

不得再以 backend 和 frontend 是否同时存在作为唯一条件。

### 7.3 兼容项目类型

至少覆盖：

- Python-only Web 服务。
- Node-only Web 服务。
- Streamlit。
- Gradio。
- 静态站点加 Python HTTP Server。
- 前端构建后由单一服务进程托管。
- 明确配置的多进程项目。
- 项目自带完整 Dockerfile 的 Dockerfile-native 项目。

## 8. 迁移验证合同

继续保留现有三个顶层合同字段，避免破坏已有迁移状态和调用方：

- `migration_integrity`
- `dual_runtime`
- `release_gate`

### 8.1 `migration_integrity`

继续校验：

- 源目录和目标目录隔离。
- 源目录未发生变化。
- 复制清单完整。
- 排除文件未进入目标副本。
- 迁移状态和 AppHub binding 身份一致。

### 8.2 `dual_runtime`

继续校验：

- 原项目入口能够按原方式进行轻量启动验证。
- AppHub 薄适配入口能够按生产方式启动。
- AppHub 薄适配入口监听目标端口。
- AppHub 健康路径返回 HTTP 200。

只有变更了业务 API、SPA 路由、WebSocket、后台任务、存储或业务执行链路时，才要求更完整的行为一致性验证。

### 8.3 `release_gate`

调整为检查：

- 根目录存在合法 `app.yaml`。
- 根目录存在 `Dockerfile`。
- `app_id` 与 binding 一致。
- Dockerfile 有明确生产启动入口。
- 生产服务使用 `PORT` 或明确监听 8000。
- `/__apphub_healthz` 可由生产入口提供。
- 浏览器 URL 满足前缀剥离后的相对路径要求。
- 最终镜像包含生产运行资产。
- 敏感文件、本地数据库、日志和 `.opscli/` 不进入 Git 或镜像。
- 声明 SQLite 时满足 Compose 规则。

`release_gate` 不再要求：

- `backend/app.py`
- `frontend/package.json`
- `nixpacks.toml`
- `backend.app:app`
- `requirements.txt` 或 `pyproject.toml`
- 同时存在前端和后端目录

## 9. 当前项目适配示例

对于 `project-10-git` 这类项目，已观察到的证据包括：

- 根级 `package.json` 和 `pnpm-lock.yaml`。
- `scripts/server.py` 提供 HTTP 服务。
- `web/index.html` 和 `public/dashboard` 提供页面和静态资产。
- Node 与 Python 混合工具链。
- 原服务健康路径为 `/health`。

合理的薄适配方向为：

1. 保留现有目录和业务实现。
2. 复用现有前端构建或静态快照流程。
3. 让现有服务监听 `PORT`。
4. 在现有服务或最小适配入口中增加 `/__apphub_healthz`。
5. 生成匹配该项目真实依赖和启动方式的根目录 Dockerfile。
6. 检查 `web`、`public` 和运行时数据是否进入最终镜像。
7. 修复浏览器根绝对 URL。
8. 不创建假的 FastAPI/Vite/Nixpacks 模板结构。

本节只定义适配原则，具体 Dockerfile 和源码修改须在需求确认后，根据目标副本的完整运行证据确定。

## 10. 修改范围

### 10.1 Skill 文档和脚本

计划修改：

- `opscli/skills/templates/ops-app-build-spec/SKILL.md`
- `opscli/skills/templates/ops-app-build-spec/references/migration-standard.md`
- `opscli/skills/templates/ops-app-build-spec/references/migration-validation-contract.md`
- `opscli/skills/templates/ops-app-build-spec/references/deployment-standard.md`
- `opscli/skills/templates/ops-app-build-spec/scripts/validate_migration_contract.py`

### 10.2 迁移专属实现

为保证 Skill 验证与 push 前复验一致，计划同步修改：

- `opscli/app/services/migration.py`
- `opscli/app/services/migration_contract.py`

这两个模块属于源码复制迁移的薄适配实现，不改变普通新建和普通项目推送合同。

### 10.3 原则上不修改

- `opscli/app/services/template.py`
- 普通 create/init 实现
- 非迁移项目的 manifest 校验
- 非迁移项目的 push 流程
- AppHub 服务端代码

`manager.py` 原有的 `migration_copy` 条件分流原则上保持不变；只有在测试证明必须调整错误提示或迁移专属调用参数时，才允许做最小修改。

## 11. Skill-only 边界说明

如果“只修改建站 Skill”被严格解释为只能修改 `opscli/skills/templates/ops-app-build-spec/` 目录，则本需求无法完整落地。

原因是 push 前会由 `opscli/app/services/manager.py` 直接调用 `opscli/app/services/migration_contract.py` 重新检查发布资产。即使 Skill 脚本已经按照新规则验证通过，旧的核心迁移门禁仍会因为缺少 `backend/app.py`、`nixpacks.toml` 或 `backend.app:app` 阻止推送。

因此建议确认以下范围定义：

> “只改 opscli 建站 Skill”包括修改 Skill 本身，以及为保证该 Skill 在迁移项目中生效所必需的迁移专属服务 `migration.py` 和 `migration_contract.py`；不包括 AppHub、新建流程、模板克隆和普通项目推送逻辑。

如果不接受上述范围，只能更新 Skill 文档和前置检查，无法解决最终 push 门禁漂移。

## 12. 状态兼容要求

- 保留现有迁移状态目录结构。
- 保留现有 `schema_version`，除非实现阶段发现无法向后兼容。
- 保留三个顶层验证合同名称。
- 已完成复制的迁移任务不得因为升级而重新复制源码。
- 已创建 AppHub 应用的迁移任务不得重复创建应用。
- 已初始化 Git 的迁移任务不得重复初始化。
- 合同规则变化后允许要求重新生成 `adaptation-manifest.json` 和 `validation-manifest.json`。
- 重新验证不得修改源目录。

## 13. 新建流程非影响要求

必须通过自动测试证明：

- 普通项目不读取迁移清单。
- 普通项目不读取迁移发布门禁。
- 普通 push 不执行浏览器相对路径扫描。
- 普通 push 不执行迁移运行资产检查。
- 普通 push 不要求迁移验证清单。
- 普通 create 不依赖迁移识别器。
- 普通 init 不依赖迁移识别器。
- 模板克隆不依赖迁移合同。
- 即使迁移验证模块抛出异常，普通 create/init/push 仍能正常工作。

## 14. 错误处理要求

迁移验证失败必须提供：

- 稳定错误码。
- 失败规则名称。
- 失败文件。
- 检测到的实际值。
- AppHub 要求值。
- 可执行修复建议。
- 是否可以自动修复。

建议保留或细化：

- `APP-MIGRATION-PATH`
- `APP-MIGRATION-STARTUP`
- `APP-MIGRATION-PUBLIC-PATH`
- `APP-MIGRATION-RUNTIME-ASSET`
- `APP-MIGRATION-RELEASE-GATE`
- `APP-MIGRATION-VALIDATION`
- `APP-MIGRATION-VALIDATION-STALE`

不允许仅返回“项目不符合模板规范”而不指出与 AppHub 实际门禁的具体差异。

## 15. 测试矩阵

### 15.1 应通过

- Python-only 项目。
- Node-only 项目。
- Streamlit 项目。
- Gradio 项目。
- 静态 HTML 加 Python HTTP Server。
- 根级 Node/Python 混合项目。
- 前端构建后由单一后端进程托管。
- 项目自带完整 Dockerfile。
- 缺少 `nixpacks.toml`。
- 缺少 `backend/app.py`。
- 缺少 `frontend/package.json`。

### 15.2 应阻止

- 缺少根目录 `Dockerfile`。
- 缺少或无法解析 `app.yaml`。
- `app_id` 与 binding 不一致。
- 生产服务未监听 8000 或 `PORT`。
- 缺少 `/__apphub_healthz`。
- 健康检查返回重定向或非 200。
- 浏览器使用根绝对资源或 API URL。
- Dockerfile 最终阶段缺少被代码引用的运行资产。
- 敏感文件、数据库或日志将被提交。
- SQLite 新应用缺少合法 Compose。
- 无法确认生产启动命令。

### 15.3 新建回归

- 标准模板 clone 行为不变。
- 普通 create 行为不变。
- 普通 init 行为不变。
- 普通 push 行为不变。
- 普通项目即使存在根绝对 URL，也不触发迁移专属门禁。
- 普通项目即使没有迁移验证清单，也可以正常推送。

## 16. 验收标准

需求完成后必须满足：

1. 迁移不依赖本机存在已合规模板项目。
2. AppHub 不需要任何代码改动。
3. 源项目保持只读。
4. 目标副本只增加必要薄适配。
5. 迁移验证不再要求模板专属目录和入口。
6. Skill 验证与 push 前迁移复验使用相同规则。
7. `project-10-git` 类型项目可以通过真实适配进入 AppHub 发布验证。
8. 无明确启动证据的项目进入人工适配，不被误判为 ready。
9. 验证通过后的源码变化仍会使验证清单失效。
10. 新建、模板克隆、普通初始化和普通推送的回归测试全部通过。

## 17. 实施顺序

需求确认后按以下顺序实施：

1. 先补充迁移和普通流程回归测试，锁定非影响边界。
2. 修改 `migration_contract.py`，校正实际发布门禁。
3. 修改 `migration.py`，校正启动识别和适配状态。
4. 修改 Skill 验证脚本，使其与 push 前门禁同源。
5. 更新 Skill 和迁移参考文档。
6. 使用多种项目形态执行定向测试。
7. 使用 `project-10-git` 迁移副本执行端到端验证。
8. 确认所有测试通过后再进行实际项目迁移。

## 18. 确认记录

代码实施前需要确认：

- [x] 接受 `ops-apphub` 零改动。
- [x] 接受继续使用薄适配架构，不重做迁移流程。
- [x] 接受移除迁移门禁中的 Nixpacks、FastAPI 和标准目录强制要求。
- [x] 接受“建站 Skill 修改范围”包含迁移专属的 `migration.py` 与 `migration_contract.py`。
- [x] 接受普通新建和普通 push 必须保持原行为。
- [x] 接受无法识别生产启动方式时进入人工适配，而不是自动猜测。
- [x] 接受先补回归测试、后修改实现。
- [x] 接受在实现完成后再执行 `project-10-git` 的实际迁移。

上述项目已于 2026-10-10 全部确认，并已按本需求完成实施。

## 19. 实施结果

- `ops-apphub` 保持零改动。
- 迁移发布门禁已改为 AppHub 实际 Dockerfile 合同，不再强制 Nixpacks、FastAPI、标准前后端目录或固定模块入口。
- 普通新建、模板克隆、普通初始化和普通 push 继续沿用原逻辑。
- 人工薄适配可记录已验证的运行入口、浏览器相对路径及本地运行数据变更，同时继续阻断 README 等无关源码漂移。
- `ops-app-build-spec` 已更新为 `v0.0.31`，明确区分标准模板合同与迁移合同。
- 聚焦回归测试共 105 项通过；新增忽略规则回归后相关定向测试 3 项通过。
- `project-10-git` 已迁移到 `prev-015`，AppHub 应用名称为“项目10部prev-015”，`app_id=HaJHK`，最终 `delivery_ready=true`、`phase=push_ready`。
- 本次只完成迁移、AppHub 登记、Git 初始化和本地验证，未执行 `opscli app push`。
