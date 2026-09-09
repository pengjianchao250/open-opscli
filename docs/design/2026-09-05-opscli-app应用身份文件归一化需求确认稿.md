# opscli app 应用身份文件归一化需求确认稿

> 日期：2026-09-05  
> 状态：已确认并完成代码落地  
> 范围：`opscli/app`、`ops-app-build-spec`、`ops-app-data-builder` 及相关测试和使用文档  
> API 依据：AppHub Control API 最新目录 `https://s.apifox.cn/9c71c630-8d57-44b7-becd-f09fbe370f5e/509871234e0`

## 1. 本次目标

在 `create / init / push` 三命令源码交付边界下，进一步统一应用身份信息，明确以下三个文件的唯一职责：

- `app.yaml`：项目随源码提交的 AppHub 应用声明。
- `.opscli/app.json`：当前本地目录与 AppHub 应用、Git 仓库的本地绑定。
- `ops-app.config`：历史遗留的混合配置文件，拆分有效语义后退出正式流程。

本次不是把所有 `ops-app.config` 文本机械替换为 `app.yaml`，而是先判断旧字段属于“应用声明”“本地绑定”还是“旧部署派生配置”，再分别迁移或删除。

## 2. 核心结论

### 2.1 `app.yaml`

`app.yaml` 是应用源码仓库中的 AppHub 应用声明，必须进入 Git。

统一模板中的 `app.yaml.name`、`app.yaml.title` 只能视为示例或占位数据。AppHub API 创建成功后返回的真实应用身份才是最终依据，因此需要将真实身份同步回项目中的 `app.yaml`：

```yaml
name: <AppHub 返回的 slug>
title: <创建应用时确认的展示名称>
```

只允许 `opscli app` 同步应用身份字段：

- `name`
- `title`

以下项目声明继续由模板、项目开发者或相关 Skill 维护，`opscli app create` 不得覆盖：

- `apiVersion`
- `description`
- `runtime`
- `python`
- `entrypoint`
- `services`
- `resources`
- `database`
- `opscli.auth_mode`
- `opscli.datasets`
- `llm`
- `access`
- 其他未来扩展字段

以下 AppHub 平台信息不得写入 `app.yaml`：

- `app_id`
- `repo_url`
- `owner_user_id`
- `owner_email`
- Git 用户名、Token 或凭据状态
- release ID、版本、构建状态、访问 URL

### 2.2 `.opscli/app.json`

`.opscli/app.json` 由 `opscli app create` 创建并由 `opscli app` 后续命令维护，用于保存当前目录与 AppHub 应用的本地绑定。

该文件应保存：

- binding schema 版本
- `app_id`
- `slug`
- 应用展示名称
- `repo_url`
- 默认分支
- Git 用户名或非敏感凭据状态
- 为兼容升级所需的非敏感历史字段

该文件不得保存：

- Git Token
- Cookie、Session、Authorization Header
- AppHub 或 Gitea 管理凭据
- 业务密钥或环境变量值

`.opscli/app.json` 是本地状态，不得进入 Git。项目 `.gitignore` 必须忽略：

```gitignore
.opscli/
```

`opscli app push` 使用 `git add -A`，因此除模板 `.gitignore` 外，CLI 还需要增加代码级保护，避免 `.opscli/app.json` 被暂存或已跟踪后继续推送。

### 2.3 `ops-app.config`

`ops-app.config` 历史上同时承担应用身份、AppHub 绑定、公开路径、Compose 和镜像命名等多种职责，已经与当前 AppHub 独立仓库和源码交付模型不一致。

最终目标是不再保留实际的 `ops-app.config` 文件，但需要按字段语义迁移，而不是简单删除。

| `ops-app.config` 历史职责 | 新位置或处理方式 |
| --- | --- |
| 稳定应用名称 `appName` | 迁移到 `app.yaml.name` |
| 展示名称 | 迁移到 `app.yaml.title` |
| AppHub 应用 ID `appId` | 迁移到 `.opscli/app.json.app_id` |
| 仓库、用户、Owner 等绑定信息 | 迁移到 `.opscli/app.json` |
| `/ops-app/{appId}/{appName}/` 公开路径拼接 | 删除，由 AppHub 网关处理 |
| Compose service 名称 | 删除，不迁移到 `app.yaml` |
| Docker image 名称 | 删除，不迁移到 `app.yaml` |
| Nginx 双服务或项目侧路由规则 | 删除，不迁移到 `app.yaml` |
| 旧迁移命令或旧部署编排参数 | 删除，由 AppHub 或其他平台处理 |

因此，只有“应用发布声明”相关语义改为 `app.yaml`；“本地平台绑定”相关语义改为 `.opscli/app.json`；部署过程派生语义直接废弃。

## 3. 三个工具的职责边界

### 3.1 `opscli/app`

`opscli app` 只负责 AppHub 和 Git 操作需要的最小信息：

- 创建或恢复 AppHub 应用。
- 创建和维护 `.opscli/app.json`。
- 将 AppHub 真实 `slug/title` 同步到现有 `app.yaml`。
- 初始化本地 Git 与应用独立仓库的绑定。
- 推送源码。

`opscli app` 不负责：

- 拉取或生成建站模板。
- 决定建站顺序和开发流程。
- 生成业务代码。
- 检查代码规范、架构规范、测试、lint 或构建结果。
- 维护 Compose、Nginx、Docker 镜像命名或线上公开路径。
- 创建 AppHub release、查询版本或跟踪发布事件。

### 3.2 `ops-app-build-spec`

`ops-app-build-spec` 负责项目模板和应用开发规范，应把 `app.yaml` 视为唯一的应用发布声明，把 `.opscli/app.json` 视为本地 AppHub 绑定证据。

需要调整的门禁：

1. 根目录存在 `.opscli/app.json`，并包含有效 `app_id` 和 `slug`。
2. 根目录存在 `app.yaml`。
3. `.opscli/app.json.slug == app.yaml.name`。
4. `.opscli/app.json` 不得被 Git 跟踪。
5. `.gitignore` 必须忽略 `.opscli/`。
6. 不再检查或生成 `ops-app.config`。

需要删除的旧规范：

- `ops-app.config.appId/appName` 同步规则。
- 项目侧 `/ops-app/{appId}/{appName}/` 公开路径拼接。
- Compose service 和 Docker image 命名规则。
- Nginx 双服务部署要求。
- 已废弃迁移命令和项目侧部署编排要求。

不能把这些旧部署规则改写成 `app.yaml` 规则，因为它们应由 AppHub 或其他平台负责。

### 3.3 `ops-app-data-builder`

`ops-app-data-builder` 只在已经具备标准模板和有效 AppHub 身份的项目中构建数据层。

模板门禁改为：

1. 根目录存在 `.opscli/app.json`。
2. binding 中存在有效 `app_id` 和 `slug`。
3. 根目录存在 `app.yaml`。
4. `.opscli/app.json.slug == app.yaml.name`。
5. 标准 `QueryGateway` 文件和模板结构存在。

数据集白名单继续写入：

```text
app.yaml.opscli.datasets
```

本 Skill 不再读取、生成或校验 `ops-app.config`。

## 4. `opscli app create` 的目标流程

### 4.1 目录绑定检查

无论用户是否显式传入 `--path`，`create` 都必须先解析最终目录并检查 `.opscli/app.json`，不能只在传入 `--path` 时检查。

```text
解析目标目录
→ 检查 .opscli/app.json
  → 不存在：允许调用 AppHub 创建接口
  → 已存在且 binding 有效、slug 相同：按幂等成功处理，不重复 POST
  → 已存在但绑定其他应用：返回 APP-ALREADY-BOUND
  → 文件存在但内容损坏或字段不完整：返回 APP-BINDING-INVALID
```

“文件存在”只能说明目录曾经尝试建立绑定，不能直接视为创建成功；仍需校验 schema、`app_id`、`slug` 和 `repo_url` 等必要字段。

### 4.2 创建请求

当前用于 AppHub 创建请求的领域模型命名为 `AppYaml`，容易与仓库中的真实 `app.yaml` 混淆，应改名为 `AppCreateRequest`。

创建请求只承载 `POST /api/v1/apps` 所需字段，不应同时承担本地 YAML 文件读写职责。

### 4.3 创建成功后的写入顺序

推荐顺序：

```text
POST /api/v1/apps 成功
→ 安全保存一次性 Git 凭据
→ 原子写入 .opscli/app.json
→ 如果 app.yaml 已存在，只同步 name/title
→ 返回应用和仓库基础信息
```

如果 `create` 执行时尚不存在 `app.yaml`：

- 不由 `opscli app` 生成完整 `app.yaml`，避免重新承担模板职责。
- `.opscli/app.json` 先保存真实 AppHub 身份。
- 后续 `init`、`push` 发现 `app.yaml` 后执行身份同步或一致性校验。

### 4.4 `app.yaml` 同步规则

新增独立 manifest 服务，只修改 `name/title`，保留其他字段、未知扩展字段和尽可能多的原始格式信息。

同步规则：

- `name` 始终使用 AppHub 返回的 `slug`。
- `title` 使用创建应用时确认的展示名称；必要时可由应用详情接口补全。
- 文件写入必须原子化，避免中途失败损坏 YAML。
- YAML 无法解析时返回明确错误，不得静默覆盖整个文件。
- 不把 binding 的 `app_id/repo_url/owner` 写入 YAML。

## 5. `init / push` 的一致性处理

### 5.1 `init`

`init` 仍只负责 Git 初始化，不拉取模板、不生成项目代码。

- 缺少 binding 时自动执行 `create` 的 ensure 逻辑。
- 发现 `app.yaml` 时同步或校验 `name/title`。
- 未发现 `app.yaml` 时不阻断 Git 初始化，但不生成 YAML。

### 5.2 `push`

`push` 只推送源码，不创建 release。

- 缺少 binding 或 Git 初始化信息时自动补齐 `create → init`。
- `app.yaml` 存在时，在提交前确保 `app.yaml.name == binding.slug`。
- `app.yaml` 不存在时允许只推送源码，不把项目规范检查扩展到 `push`。
- 无论是否存在 `app.yaml`，都必须阻止 `.opscli/app.json` 进入提交。

## 6. AppHub API 对应关系

本次涉及的最新 API：

| 用途 | 方法与路径 |
| --- | --- |
| 创建应用 | `POST /api/v1/apps` |
| 查询当前用户创建的应用 | `GET /api/v1/apps` |
| 查询应用详情 | `GET /api/v1/apps/{app_id}` |
| 查询当前用户可访问应用 | `GET /api/v1/accessible-apps` |
| 查询 Git 配置 | `GET /api/v1/apps/{app_id}/git-config` |
| 签发 Git 凭据 | `POST /api/v1/git/credentials` |

`GET /api/v1/accessible-apps` 与 `GET /api/v1/apps` 职责不同。当前 binding 恢复逻辑使用前者是合理的，不应仅因为存在 `/apps` 列表接口就替换。

AppHub 创建响应中的平台事实包括：

- `app_id`
- `slug`
- `path`
- `status`
- `repo_url`
- `owner_user_id`
- `owner_email`
- `git_username`
- 一次性 `git_credential`

其中只有 `slug` 和创建时确认的展示名称需要进入 `app.yaml`；其余信息进入 binding、凭据存储或仅用于命令输出。

## 7. 具体文件改动范围

### 7.1 `opscli/app`

- `opscli/app/domain/models.py`
  - 将 API 请求 DTO `AppYaml` 重命名为 `AppCreateRequest`。
  - 保持创建请求模型与本地 manifest 模型分离。
- `opscli/app/services/manager.py`
  - 修复未传 `--path` 时不检查已有 binding 的问题。
  - 接入 manifest 身份同步和一致性校验。
  - 为 `create/init/push` 明确各自的 manifest 行为。
- `opscli/app/services/manifest.py`
  - 新增 `app.yaml` 读取、身份同步、原子写入和一致性校验。
- `opscli/app/services/gitops.py`
  - 在 `git add -A` 前后增加 `.opscli/app.json` 防误提交保护。
  - 对已跟踪或已暂存的 binding 给出明确错误。
- `opscli/app/domain/exceptions.py`
  - 视实现需要新增 manifest、binding 损坏和本地状态泄漏错误码。
- `opscli/app/commands/cli.py`
  - 仅在错误提示、帮助文本或输出字段需要变化时修改，不扩展建站参数。

### 7.2 App Skill

- `opscli/skills/templates/ops-app-build-spec/SKILL.md`
  - 用 `app.yaml + .opscli/app.json` 一致性门禁替换 `ops-app.config`。
  - 删除 Compose、镜像、Nginx、旧公开路径和旧迁移命令规范。
  - 增加 `.opscli/` 必须被忽略的要求。
- `opscli/skills/templates/ops-app-build-spec/references/deployment-standard.md`
  - 明确源码声明与 AppHub 平台发布边界。
  - 删除残留的旧部署编排语义。
- `opscli/skills/templates/ops-app-build-spec/assets/backend/CLAUDE.md`
  - 将“前端与部署由 `ops-app.config` 承担”改为：根目录 `app.yaml` 承担 AppHub 声明，`.opscli/app.json` 仅承担不入库的本地绑定。
- `opscli/skills/templates/ops-app-build-spec/data/VERSION.json`
  - 更新 Skill 版本和变更说明。
- `opscli/skills/templates/ops-app-data-builder/SKILL.md`
  - 删除 `ops-app.config` 门禁。
  - 改为校验 binding `app_id/slug` 与 `app.yaml.name`。
  - 保留 `app.yaml.opscli.datasets` 白名单要求。
- `opscli/skills/templates/ops-app-data-builder/agents/openai.yaml`
  - 同步对外说明和提示语。
- `opscli/skills/templates/ops-app-data-builder/data/VERSION.json`
  - 更新 Skill 版本和变更说明。

### 7.3 测试

- `tests/app/test_manager.py`
  - 覆盖默认目录已有 binding 时不重复创建。
  - 覆盖同应用幂等、不同应用冲突和损坏 binding。
  - 覆盖创建成功后同步 `app.yaml.name/title`。
  - 覆盖 `app.yaml` 不存在时不生成完整文件。
- `tests/app/test_manifest.py`
  - 覆盖只修改 `name/title`。
  - 覆盖其他字段和未知扩展字段保留。
  - 覆盖 YAML 损坏、原子写入和身份不一致。
- `tests/app/test_gitops.py`
  - 覆盖 `.opscli/app.json` 未跟踪、已暂存、已跟踪场景。
- `tests/app/test_client.py`
  - 保持 `/accessible-apps` 响应解析和 API 路径契约。
- `tests/skills/test_ops_app_build_spec_skill.py`
  - 删除对 `ops-app.config`、Compose 和旧部署规则的正向断言。
  - 增加 `app.yaml`、binding 一致性和 `.opscli/` 忽略断言。
- `tests/skills/test_ops_app_data_builder_skill.py`
  - 将项目身份门禁断言迁移到 `app.yaml + .opscli/app.json`。

### 7.4 文档

- `docs/design/2026-09-05-opscli-app三命令源码交付职责定稿.md`
  - 作为 `opscli app` 当前唯一职责定稿。
- `docs/guide/AppHub应用创建初始化与源码推送指南.md`
  - 更新三命令行为、`app.yaml` 回填和 binding 忽略规则。
- `docs/change-log-pending.md`
  - 记录 manifest 归一化和 `ops-app.config` 退出流程。
- 旧设计文档
  - 不重写历史内容，只增加“已被新方案取代”的提示，保留决策演进记录。

## 8. 建议错误码

| 错误码 | 场景 |
| --- | --- |
| `APP-ALREADY-BOUND` | 目录已绑定另一个 AppHub 应用 |
| `APP-BINDING-INVALID` | `.opscli/app.json` 存在但损坏或缺少必要字段 |
| `APP-MANIFEST-INVALID` | `app.yaml` 无法解析或结构错误 |
| `APP-IDENTITY-MISMATCH` | `app.yaml.name` 与 binding `slug` 不一致且无法安全同步 |
| `APP-BINDING-TRACKED` | `.opscli/app.json` 已被 Git 跟踪或暂存 |

错误信息只描述 AppHub 身份和 Git 安全问题，不扩展为代码质量或建站规范检查。

## 9. 验收标准

### 9.1 应用创建

- 未显式传 `--path` 时也会检查默认目录中的 `.opscli/app.json`。
- 同目录、同 slug 重复执行 `create` 不重复调用创建 API。
- 同目录绑定其他 slug 时明确拒绝。
- 损坏 binding 不被误判为已经创建成功。
- 创建成功后 `.opscli/app.json` 保存真实 AppHub 绑定。
- `app.yaml` 已存在时只回填真实 `name/title`。
- `app.yaml` 不存在时不由 `opscli app` 生成模板文件。

### 9.2 源码推送

- `push` 只推送源码，不创建 release。
- `.opscli/app.json` 在任何情况下都不会进入提交。
- `app.yaml` 存在时，push 前必须确保应用身份一致。
- push 完成后 `opscli app` 立即结束，不查询或触发发布流程。

### 9.3 Skill

- 两个 Skill 不再要求或生成 `ops-app.config`。
- `ops-app-build-spec` 使用 `app.yaml` 作为应用声明。
- `ops-app-data-builder` 继续通过 `app.yaml.opscli.datasets` 管理数据集白名单。
- Compose、镜像、Nginx 和旧公开路径规则不迁移到 `app.yaml`。

### 9.4 回归

- `tests/app` 全部通过。
- 两个 Skill 的专项契约测试通过。
- AppHub API 客户端继续使用 `/api/v1/accessible-apps` 恢复可访问应用。
- `create / init / push` 命令保持清晰、独立且幂等补齐前置条件。

## 10. 不在本次范围

- 不修改 AppHub 服务端 API。
- 不修改统一模板仓库中的业务代码和完整 `app.yaml` 默认内容；模板仓库只需另行补充 `.opscli/` 忽略规则和示例身份说明。
- 不重新引入模板拉取、自然语言建站或代码生成流程到 `opscli app`。
- 不在 CLI 中增加测试、lint、构建、Compose 或容器检查。
- 不将 Git Token 或其他敏感信息迁移到任何项目文件。
- 不把历史部署派生字段塞入 `app.yaml`。

## 11. 最终文件关系

```text
AppHub API
  ├─ 返回 app_id/repo_url/owner/git 信息
  │    └─ .opscli/app.json + 本机 Git credential helper
  └─ 返回 slug，创建命令确认 title
       └─ app.yaml.name/title

app.yaml
  └─ 随源码提交，描述应用发布声明

.opscli/app.json
  └─ 仅本地使用，不进入 Git

ops-app.config
  └─ 有效语义拆分迁移后退出，不再生成、不再校验、不再提交
```

本确认稿对应的代码、Skill、测试和使用文档已按第 7 节范围完成落地。
