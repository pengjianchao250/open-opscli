# opscli app 三命令源码交付职责定稿

> 日期：2026-09-05  
> 状态：已确认，按本文完成代码落地  
> 范围：`opscli/app`、AppHub API 调用边界、Git 源码交付、相关 Skill、测试和使用文档  
> API 依据：AppHub Control API 最新目录 `https://s.apifox.cn/9c71c630-8d57-44b7-becd-f09fbe370f5e/509871234e0`
> 2026-09-07 修订：AppHub 请求统一使用自动刷新的 Bearer JWT；创建不再内联 Git 凭据，`init/push` 继续使用独立凭据接口。
> 2026-09-07 分支修订：文中的 `main` 分支约定已被 `docs/design/2026-09-07-opscli-app与建站Skill-master分支统一方案.md` 替代，新应用统一使用 `master`。

## 1. 需求背景

`opscli/app` 的职责需要进一步收敛。该工具只负责：

1. 创建或恢复 AppHub 应用基础信息。
2. 初始化本地 Git 项目并绑定应用独立仓库。
3. 将源码提交并推送到应用独立仓库。

源码推送完成后，`opscli/app` 的职责立即结束。

`opscli/app` 不负责调用 AppHub 发布服务，不负责等待线上构建，不负责获取版本状态，不负责消费发布事件，也不负责判断应用是否已经部署上线。

## 2. 最终命令模型

`opscli app` 只保留三个用户命令：

```text
opscli app create
opscli app init
opscli app push
```

内部前置条件采用幂等 ensure 语义：

```text
create = ensure_app
init   = ensure_app → ensure_git
push   = ensure_app → ensure_git → ensure_pushed
```

其中 `ensure_pushed` 只表示 Git 源码已经到达远端 `main`，不包含 AppHub release。

## 3. 命令职责

### 3.1 `create`

```bash
opscli app create 销售日报 --path .\sales-dashboard
```

职责：

- 解析目标目录。
- 检查目标目录是否已有 `.opscli/app.json`。
- 同一目录已经绑定相同应用时幂等返回，不重复调用创建接口。
- 已绑定其他应用时返回冲突。
- 无 binding 时调用 `POST /api/v1/apps` 创建 AppHub 应用。
- 保存 AppHub 返回的 `app_id`、`slug`、`repo_url` 和其他非敏感绑定信息。
- 创建响应不读取或保存 Git Token。
- 如果已有 `app.yaml`，同步真实的 `name/title`。

`create` 不执行：

- `git init`
- 模板拉取
- 业务代码生成
- commit
- push
- release

### 3.2 `init`

```bash
opscli app init .\sales-dashboard
```

职责：

- 读取或恢复 `.opscli/app.json`。
- binding 不存在时，优先根据可访问应用恢复；没有匹配应用时再创建应用。
- 调用 `GET /api/v1/apps/{app_id}` 获取应用详情。
- 调用 `GET /api/v1/apps/{app_id}/git-config` 获取当前 Git 仓库配置。
- 必要时调用 `POST /api/v1/git/credentials` 获取 Git 凭据。
- 初始化本地 Git 项目。
- 将 AppHub 返回的独立仓库设置为 `origin`。
- 获取远端 `main`，处理本地仓库与远端仓库的初始关联。
- 不覆盖已有业务源码。
- 如果存在 `app.yaml`，同步或校验应用身份。

`init` 不调用任何 release API，不消费 SSE，不查询发布版本。

### 3.3 `push`

```bash
opscli app push .\sales-dashboard -m 优化库存风险筛选
```

职责：

- 缺少应用 binding 时自动补齐 `create`。
- 缺少 Git 初始化信息时自动补齐 `init`。
- 校验 `origin` 与 AppHub binding 中的 `repo_url` 一致。
- 获取远端 `main` 并拒绝 non-fast-forward。
- 工作区有修改时执行普通 commit。
- 将当前 `HEAD` 推送到远端 `main`。
- 返回本地 commit SHA、远端 commit SHA、commit/push 是否发生等 Git 信息。

`push` 完成远端 Git push 后立即结束，不再执行其他 AppHub 操作。

输出只能说明：

```text
源码已推送到远端仓库。
```

不能说明或输出：

- 已发布
- 已部署
- 线上构建成功
- 版本号
- release ID
- 发布 URL
- 健康状态
- 发布事件进度

`push --message` 继续为必填参数，因为它用于工作区有修改时创建 Git commit。`push` 不需要生成 release message，也不需要根据用户和时间生成默认发布说明。

## 4. AppHub API 调用边界

所有 AppHub 请求通过 `AuthClient.get_token("ops")` 获取或刷新 JWT，只发送 `Authorization: Bearer <JWT>` 与 `X-Opscli-Version`。不发送 `X-Session-Id`、登录 Cookie 或 CSRF 头。Bearer 只负责认证，端点权限仍由 AppHub 根据稳定用户 ID 和真实 owner/member/admin/it 角色判断。

### 4.1 `opscli/app` 保留的 API

| 用途 | 方法与路径 | 使用命令 |
| --- | --- | --- |
| 创建应用 | `POST /api/v1/apps` | `create`、自动补齐 |
| 查询应用详情 | `GET /api/v1/apps/{app_id}` | `init`、`push` |
| 查询可访问应用 | `GET /api/v1/accessible-apps` | binding 恢复 |
| 查询 Git 配置 | `GET /api/v1/apps/{app_id}/git-config` | `init`、`push` |
| 签发 Git 凭据 | `POST /api/v1/git/credentials` | 凭据缺失或刷新 |

### 4.2 从 `opscli/app` 移除的 API

以下 API 仍可以由 AppHub 服务端提供，但不再由 `opscli/app` 调用或封装：

| 用途 | 方法与路径 |
| --- | --- |
| 查询应用版本 | `GET /api/v1/apps/{slug}/releases` |
| 创建应用版本 | `POST /api/v1/apps/{slug}/releases` |
| 查询发布事件 | `GET /api/v1/apps/{slug}/releases/{id}/events` |

## 5. 应用身份文件

### 5.1 `app.yaml`

`app.yaml` 是随源码提交的应用声明文件，继续保留：

- 应用 `name`
- 应用 `title`
- 运行时和入口声明
- `opscli.datasets` 数据集白名单
- `llm`、`access` 和其他项目扩展声明

模板中的 `name/title` 可以是示例数据。`opscli app create/init/push` 在文件存在时可以同步真实的 `name/title`，但不负责完整的代码规范、构建规范或发布质量检查。

`opscli app` 不把 `app_id`、`repo_url`、Owner、Git Token、release ID 或线上 URL 写入 `app.yaml`。

### 5.2 `.opscli/app.json`

`.opscli/app.json` 由 `opscli app create` 创建并由三个命令维护，用于保存本地目录与 AppHub 应用、Git 仓库的 binding：

- `app_id`
- `slug`
- `repo_url`
- 默认分支
- Git 用户名
- Owner 等非敏感信息

该文件不保存 Token、Cookie、Session、Authorization Header 或其他敏感凭据。

`.opscli/app.json` 不得进入 Git。项目 `.gitignore` 必须包含：

```gitignore
.opscli/
```

### 5.3 `ops-app.config`

当前三命令流程不再生成、读取或校验 `ops-app.config`。

历史字段按以下规则处理：

| 历史语义 | 处理方式 |
| --- | --- |
| 应用名称 | 使用 `app.yaml.name` |
| 展示标题 | 使用 `app.yaml.title` |
| AppHub `appId` | 使用 `.opscli/app.json.app_id` |
| 仓库地址和 Owner | 使用 `.opscli/app.json` |
| 公开路径拼接 | 删除，由 AppHub 网关处理 |
| Compose service 名 | 删除，不迁移 |
| Docker image 名 | 删除，不迁移 |
| Nginx 双服务编排 | 删除，不迁移 |
| 旧部署迁移命令 | 删除，由其他平台流程负责 |

## 6. `opscli/app` 的职责边界

### 6.1 负责

- AppHub 应用创建和基础信息恢复。
- 本地 binding 创建、读取、迁移和一致性维护。
- Git 仓库地址和 Git 凭据获取。
- 本地 Git 初始化。
- 普通 commit。
- 普通 push 到远端 `main`。
- `app.yaml.name/title` 身份同步。
- `.opscli/app.json` 防止进入 Git。

### 6.2 不负责

- 建站模板拉取和业务代码生成。
- 建站顺序和开发流程编排。
- 代码规范、测试、lint 或构建检查。
- AppHub release 创建。
- AppHub 发布状态查询。
- 发布事件 SSE 连接和续订。
- 线上部署、健康检查、回滚和版本管理。
- Compose、Nginx 和镜像命名。

## 7. 代码改动范围

### 7.1 必须修改

- `opscli/app/commands/cli.py`
  - 删除 `release` 命令。
  - 删除 release 事件输出。
  - 删除 `release_id/version/status/url` 输出字段。
  - 将帮助文本改为“应用信息、Git 仓库和源码推送”。
- `opscli/app/services/manager.py`
  - 删除 `AppManager.release()`。
  - 删除发布服务依赖、发布状态检查和发布 message 生成。
  - 保留 `create/init/push` 和 binding、Git、manifest 逻辑。
- `opscli/app/transport/client.py`
  - 删除 `list_releases()`。
  - 删除 `publish_release()`。
  - 删除 release/SSE 专用传输逻辑。
- `tests/app/test_cli.py`
  - 命令集合改为 `create/init/push`。
  - 删除 release 参数测试。
- `tests/app/test_manager.py`
  - 删除 release 发布、NOOP、状态阻断和默认 release message 测试。
  - 保留并强化 push 只推送源码的测试。
- `tests/app/test_client.py`
  - 删除 releases API 和 SSE 测试。
  - 保留当前 `/api/v1`、应用、accessible-apps 和 Git API 测试。
- `ops-app-build-spec` 和 `ops-app-data-builder`
  - 删除三命令之外的 release 流程描述。
  - 删除 release 状态、线上 URL 和发布质量门禁。
- AppHub 源码交付使用指南和变更日志。

### 7.2 建议删除

如果全仓库没有其他调用方，删除：

- `opscli/app/services/publish.py`
- `opscli/app/services/sse.py`

如果暂时保留，应确保没有生产代码 import，也不在 `opscli/app` 对外能力中暴露。

### 7.3 保留不变

- `opscli/app/services/binding.py`
- `opscli/app/services/gitcred.py`
- `opscli/app/services/gitops.py`
- `opscli/app/services/manifest.py`
- `opscli/app/domain/models.py`
- `opscli/app/domain/constants.py`
- `opscli/app/domain/exceptions.py`
- `.opscli/app.json` schema 和旧版本迁移能力
- `app.yaml` 身份同步能力
- `/api/v1` API 前缀
- `GET /api/v1/accessible-apps` 恢复逻辑

## 8. 测试验收标准

### 8.1 命令边界

- CLI 只暴露 `create`、`init`、`push`。
- `push` 不调用任何 release API。
- `push` 不创建 release，不消费 SSE。
- `push` 成功后不输出版本号、release ID、线上 URL 或部署状态。

### 8.2 创建和初始化

- 默认目录和显式目录都会检查已有 `.opscli/app.json`。
- 同应用重复 `create` 不重复创建 AppHub 应用。
- 不同应用绑定返回冲突。
- 损坏 binding 返回明确错误。
- `create` 成功后保存真实 AppHub binding。
- `create` 不内联获取或保存 Git 凭据，凭据只由 `init/push` 按需通过独立接口获取。
- 已有 `app.yaml` 时只同步 `name/title`，不覆盖其他字段。
- `create` 不执行 Git 初始化。
- `init` 不拉取模板、不生成业务代码、不调用 release API。

### 8.3 Git 安全

- AppHub HTTP 请求只携 Bearer JWT 与版本头，不携登录 Cookie 或旧 `X-Session-Id`。
- `origin` 必须与 AppHub 返回的仓库一致。
- 禁止 force push。
- 远端领先时拒绝 non-fast-forward。
- `.opscli/app.json` 未被跟踪、暂存或推送。
- Git Token 不进入 binding、日志、输出、remote URL 或提交历史。

### 8.4 Skill 和文档

- 两个 App Skill 不再要求执行 `release`。
- `app.yaml` 是源码声明唯一来源。
- `.opscli/app.json` 是本地 binding 唯一来源。
- `ops-app.config` 不再生成、读取或校验。
- 文档明确“源码推送完成后 `opscli/app` 结束”。

## 9. 非本次范围

- 不修改 AppHub 服务端 release API。
- 不实现新的发布工具或发布命令。
- 不把发布能力迁移到 `opscli/app` 之外的模块。
- 不修改统一模板仓库业务代码。
- 不引入模板拉取、建站编排或代码生成到 `opscli/app`。
- 不执行真实 Git push 或线上发布验证。

## 10. 最终结论

```text
opscli app = AppHub 应用登记 + Git 初始化 + 源码推送
```

最终流程为：

```text
create：创建应用并保存基础信息
init：初始化本地 Git 并绑定独立仓库
push：提交并推送源码，然后结束
```

职责边界明确为：

- 源码是否已交付：由 `opscli app push` 负责。
- 应用是否已发布：不由 `opscli/app` 负责。
- 应用是否已上线：由 AppHub 或其他发布平台负责。

本文确认后，再按第 7 节范围修改代码、测试、Skill 和使用文档。
