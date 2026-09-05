# opscli app 四命令职责重构需求定稿

> 日期：2026-09-05  
> 状态：已确认，进入代码落地  
> 范围：opscli app create / init / push / release、AppHub API 适配、本地 binding 与 Git 操作  
> API 依据：AppHub Apifox 文档，页面最后修改时间为 2026-09-04 00:54:04

## 1. 背景与目标

当前 opscli app 同时承载应用创建、模板拉取、Git 初始化、源码推送、版本发布和 SSE 跟踪，容易与建站流程、开发规范和发布前检查混淆。

本次将 opscli app 收敛为 AppHub 应用登记、Git 仓库绑定、源码推送和版本发布工具，只关注四类必要动作：

1. 创建或恢复 AppHub 应用基础信息。
2. 根据应用信息初始化本地 Git 仓库。
3. 将源码提交并推送到应用独立仓库。
4. 基于已推送的远端提交创建 AppHub release。

opscli app 不负责建站过程、建站顺序、业务代码生成、代码规范、测试、构建和发布前质量检查。

## 2. 四命令模型

~~~text
opscli app create
opscli app init
opscli app push
opscli app release
~~~

| 命令 | 用户意图 | 核心结果 |
| --- | --- | --- |
| create | 创建 AppHub 应用 | 保存应用、仓库和 Git 凭据基础信息 |
| init | 初始化本地源码仓库 | 本地目录绑定应用仓库并具备 Git 操作能力 |
| push | 只交付源码 | 源码推送到远端 main，不发布 |
| release | 发布应用版本 | 确保源码已推送，再创建 release |

内部使用幂等 ensure 语义自动补齐前置条件，用户不必记忆固定顺序：

~~~text
create  = ensure_app
init    = ensure_app → ensure_git
push    = ensure_app → ensure_git → ensure_pushed
release = ensure_app → ensure_git → ensure_pushed → ensure_released
~~~

## 3. 职责边界

### 3.1 负责

- AppHub 应用创建、查询和本地信息恢复。
- 应用独立仓库地址获取与本地绑定。
- 当前用户 Git 凭据签发、轮换和安全存储。
- Git 初始化、远端校验、提交和普通推送。
- AppHub release 创建、状态跟踪和 SSE 续订。
- 非敏感 binding 的本地持久化与旧版本迁移。

### 3.2 不负责

- 不维护或强制执行建站与开发顺序。
- 不拉取、生成或复制业务项目模板。
- 不生成前端、后端、数据库或部署代码。
- 不负责代码规范、目录规范或架构规范。
- 不运行测试、lint、构建、容器或健康检查。
- 不判断业务代码是否满足上线质量要求。
- 不管理环境变量、密钥、成员或访问范围。
- 不直接调用 Gitea 管理 API，不持有管理员凭据。

建站和开发规范继续由模板仓库、项目内 AGENTS.md、相关 Skill 和 CI 管理。

## 4. AppHub API 契约

### 4.1 API 前缀

根据 2026-09-04 更新的 Apifox 文档，正式接口前缀为 /api/v1。本次需要移除当前代码使用的旧前缀 /api/apphub/v1。配置项只保存 AppHub 服务根地址，客户端统一追加 /api/v1。

### 4.2 本次使用的接口

| 用途 | 方法与路径 | 使用命令 |
| --- | --- | --- |
| 创建应用 | POST /api/v1/apps | create、自动补全 |
| 获取应用详情 | GET /api/v1/apps/{slug} | init / push / release |
| 获取可访问应用 | GET /api/v1/accessible-apps | binding 丢失时恢复应用 |
| 获取 Git 配置 | GET /api/v1/apps/{slug}/git-config | init / push / release |
| 签发 Git 凭据 | POST /api/v1/git/credentials | 凭据缺失或轮换时 |
| 获取应用版本 | GET /api/v1/apps/{slug}/releases | baseline 与 NOOP 判断 |
| 发布应用版本 | POST /api/v1/apps/{slug}/releases | release |
| 续订发布事件 | GET /api/v1/apps/{slug}/releases/{id}/events | SSE 中断恢复 |

### 4.3 创建应用请求

~~~json
{
  "apiVersion": "apps.aukeys/v1",
  "name": "app-slug",
  "title": "应用名称",
  "description": "",
  "contact": null,
  "resources": {"cpu": null, "memory": null},
  "database": {"path": null},
  "opscli": {"auth_mode": "viewer", "datasets": []},
  "llm": {"enabled": false},
  "access": {"visibility": "members"}
}
~~~

不再默认发送旧字段：runtime、python、entrypoint、services.sqlite。

创建响应使用 app_id、slug、path、status、repo_url、owner_user_id、owner_email、git_username、git_credential、git_warning。一次性 git_credential.token 只允许写入 Git credential helper，不得进入 binding、命令输出、日志或 remote URL。

## 5. 命令详细需求

### 5.1 create

~~~bash
opscli app create <app-name> [--path PATH] [--json]
~~~

1. 校验应用名称并生成合法 slug。
2. 调用创建接口，接受同 owner、同 slug 的幂等重入。
3. 保存应用和独立仓库基础信息。
4. 安全保存一次性 Git 凭据。
5. 在目标目录写入 .opscli/app.json。

不执行 git init、模板拉取、源码生成、commit、push 或 release。目录已绑定同一应用时幂等成功；绑定其他应用时停止。

### 5.2 init

~~~bash
opscli app init [PATH] [--app APP_SLUG] [--json]
~~~

1. 确保当前目录具有应用基础信息。
2. 获取应用详情和 Git 配置。
3. 确保当前用户拥有可用 Git 凭据。
4. 初始化 Git 并设置正确的 origin。
5. 获取远端 main 并建立本地分支关系。
6. 保留已有源码，不覆盖业务文件。
7. 保存或刷新 binding。

不拉模板、不应用模板、不生成文件、不提交、不 push、不 release。

binding 缺失时按以下顺序处理：

1. 优先使用显式 --app APP_SLUG。
2. 否则从目录名或已有应用描述文件获取候选 slug。
3. 查询应用详情或可访问应用，优先恢复已有应用。
4. 找到唯一应用时恢复 binding，不重复创建。
5. 多个候选或无法唯一确认时停止，要求显式指定应用。
6. 明确确认远端不存在且能够得到有效应用名称时，才自动 create。

不得因缺少 binding 就盲目创建重复应用。

### 5.3 push

~~~bash
opscli app push [PATH] --message "源码修改说明" [--json]
~~~

1. 自动补齐 ensure_app 和 ensure_git。
2. 校验 origin 与 AppHub repo_url 一致。
3. 获取远端 main 并拒绝 non-fast-forward。
4. 工作区有修改时执行 git add -A 和普通 commit。
5. 将本地 HEAD 普通推送到远端 main。
6. 输出实际远端 commit_sha。

push 不调用 releases API、不消费 SSE、不输出版本号、URL 或部署状态、不使用 force push。无修改但有未推送 commit 时正常推送；本地与远端一致时幂等成功，不制造空 commit。

输出必须表述为“源码已推送到远端仓库”，不得表述为已发布或已部署。

### 5.4 release

~~~bash
opscli app release [PATH] --message "版本发布说明" [--json]
~~~

1. 自动补齐 ensure_app、ensure_git 和 ensure_pushed。
2. 获取远端 main 的真实 commit SHA。
3. 获取最近 release baseline。
4. baseline 等于远端 SHA 时返回 noop。
5. baseline 不一致时调用 releases API。
6. 消费 SSE，断线时按 since_seq 续订。
7. 输出 commit_sha、release_id、version、status、url。

ensure_pushed 是幂等确保：有修改则提交并推送；有未推送 commit 则推送；本地与远端一致则直接发布；push 成功但 release 中断时基于同一 SHA 恢复；同一 SHA 已发布时返回 noop。

release --message 作为 release message；发现未提交源码时可复用为 Git commit message。无源码修改时不得制造 commit。

应用处于 disabled、archived、deleted 等状态时只阻止 release。默认允许继续纯 Git push，前提是仍有仓库权限。

## 6. 本地 binding

.opscli/app.json 只保存恢复应用和 Git 操作所需的非敏感信息。建议升级为 schema v3：

~~~json
{
  "schema_version": 3,
  "app_id": "string",
  "app_name": "应用名称",
  "slug": "app-slug",
  "repo_url": "https://gitea.example/apps/app-slug.git",
  "default_branch": "main",
  "git_username": "string",
  "owner_user_id": "string",
  "owner_email": "string",
  "created_at": "string"
}
~~~

不得保存 Git token、Session ID、JWT、Cookie、Authorization、CSRF token 或 Gitea admin token。

template_repo_url 和 template_branch 不再属于 opscli app binding。schema v1、v2 继续允许读取，第一次成功执行 init、push 或 release 时迁移到 v3；旧模板字段读取后忽略，不再写回。旧共享仓库地址必须通过 AppHub 应用详情和 git-config 刷新；无法确认应用身份时停止迁移，不静默覆盖 origin。

## 7. 代码结构调整建议

### 7.1 AppManager

对外提供 create_app、init_git、push、release；内部提取 _ensure_app、_ensure_binding、_ensure_git、_ensure_credential、_ensure_pushed、_refresh_binding。

### 7.2 GitService

initialize 移除 template_repo_url、template_branch、apply_template、template remote 和模板 checkout，只保留 Git 可用性检查、仓库初始化、origin 校验、main 获取、普通 commit/push 和远端 SHA 查询。

### 7.3 PublishService

PublishService 只由 release 调用，负责 baseline、NOOP、releases API、SSE 续订和终态错误映射。push 不再依赖 PublishService。

### 7.4 CLI

命令树调整为 create、init、push、release。帮助文本统一使用“应用”“仓库”“源码”“发布版本”，移除“Codex 站点”“建站”“应用模板”“推送并自动部署”等混淆表达。

## 8. 错误与幂等语义

| 错误码 | 场景 |
| --- | --- |
| APP-ARGUMENT | 缺少应用名、slug 或 message |
| APP-NOT-BOUND | 无 binding 且无法安全恢复应用 |
| APP-AMBIGUOUS | 找到多个候选应用，必须显式选择 |
| APP-ALREADY-BOUND | 目录已经绑定其他应用 |
| APP-STATE | 应用状态不允许 release |
| APPHUB-PROTOCOL | AppHub 响应缺少必要字段 |
| GIT-001 | Git 缺失或版本不满足要求 |
| GIT-002 | Git 凭据缺失或无效 |
| GIT-003 | non-fast-forward，禁止覆盖远端提交 |
| GIT-REPO-NOT-READY | 应用已登记但仓库或 main 暂不可访问 |
| RELEASE-NOOP | 当前远端 SHA 已发布，属于成功提示 |

幂等要求：重复 create 返回已有应用；重复 init 不覆盖源码；重复 push 无新提交时返回当前远端 SHA；重复 release 同一 SHA 返回已有结果或 noop，不制造新版本。

## 9. 安全要求

1. Git token 只在内存中短暂处理并写入 credential helper。
2. remote URL 不嵌入用户名、token 或 session。
3. 普通输出和 --json 均不得包含敏感凭据。
4. 错误、Git stderr 和日志必须脱敏。
5. 测试不得访问真实 AppHub、Gitea、用户 Keychain 或用户 Git credential。
6. 不引入 Gitea 管理 API 或管理员 token。

## 10. 测试范围

- CLI 只暴露 create、init、push、release 四个命令。
- Client 使用 /api/v1，create 请求符合 2026-09-04 契约。
- binding v3 可读写，v1/v2 可迁移，新 binding 无模板字段和 token。
- create 只创建和绑定，不初始化 Git。
- init 缺少 binding 时先恢复已有应用，不拉模板。
- push 可补齐 create/init，只执行 Git push，不调用 releases API。
- release 自动确保源码已推送，可恢复中断，对已发布 SHA 返回 noop。
- 不可发布状态只阻止 release，不阻止纯 push。
- Git 初始化不覆盖已有源码，不 force push，不制造空 commit。

## 11. 验收标准

1. opscli app 只包含四个用户命令。
2. create 只创建应用并保存基础信息。
3. init 只初始化和绑定 Git，不拉模板、不生成代码。
4. push 只推送源码，不调用 releases API。
5. release 确保源码已推送，再创建 release。
6. init、push、release 可幂等补齐缺失前置条件。
7. binding 丢失时优先恢复已有应用，不盲目创建。
8. API 全部切换到 /api/v1。
9. create 请求体符合当前 Apifox 契约。
10. 新 binding 不包含模板信息和敏感凭据。
11. push 与 release 的输出语义明确区分。
12. push 成功、release 失败后可直接重试 release。
13. 同一远端 SHA 重复 release 不产生重复版本。
14. app 单元测试全部使用 mock 和临时 Git 仓库。

## 12. 待确认决策

1. release 是否强制要求 --message：本稿建议强制要求，并允许在有未提交修改时复用为 commit message。
2. push 是否允许不可发布状态应用继续推送源码：本稿建议允许，状态只限制 release。
3. init 自动 create 的名称来源：只在显式信息或唯一可确认信息充分时创建，否则要求 --app 或应用名称。
4. 是否保留 site_name 字段兼容：建议模型改为 app_name，读取旧 binding 时兼容 site_name。
5. 无新内容是否返回错误：建议 push 和 release 的无变化场景均作为幂等成功，不返回退出码 1。

以上决策确认后再修改代码、测试和相关旧设计文档。
