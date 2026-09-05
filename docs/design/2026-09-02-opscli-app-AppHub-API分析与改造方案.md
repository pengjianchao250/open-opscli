# opscli app 与 AppHub API 全量分析及改造方案

> **历史方案，已被取代**：2026-09-05 起以 `docs/design/2026-09-05-opscli-app四命令职责重构需求定稿.md` 为准。API 前缀、四命令职责以及 push/release 边界均以新文档为准。

> 日期：2026-09-02  
> 范围：Apifox 中 AppHub 68 个正式 API、`opscli/app` 当前实现、AppHub 架构与 CLI 任务设计。  
> 前提：一个站点对应一个 Gitea 仓库，仓库路径为 `apps/{slug}`，默认分支为 `main`。

## 1. 核心结论

1. `POST /api/apphub/v1/apps` 已负责应用登记、建仓、初始化 `main`、创建 Git 账号、添加协作者和首次签发 Git 凭据，当前阶段不需要新增 `git/ensure`。
2. `opscli` 不得调用 Gitea 管理 API，也不得持有 Gitea admin token。站点仓库地址必须使用 AppHub 返回的 `repo_url`，不能固定为共享仓库或由 CLI 自行拼接。
3. 当前 `opscli/app` 只有 `create/init/push` 三个简化命令，并把全部站点绑定到同一个 `apphub.git`，不符合“一站点一仓库”和正式 AppHub 契约。
4. AppHub API 不应全部映射成普通 CLI 命令。第一阶段只接入 `create/init/push` 闭环必需的应用、Git、发布、版本基线和 SSE 接口。
5. 第一阶段继续保留 `create/init/push` 三个命令，不新增 `publish`、`versions`、`git` 等用户命令；其中 `push` 内部升级为“校验 → 普通 Git push → releases → SSE”的完整发布链。
6. Apifox 正式 v1 契约在 2026-09-02 更新，本地 AppHub 源码 HEAD 为 2026-08-31，部分路径与字段存在漂移。CLI 应以正式 v1 契约为准，并用契约测试锁定。

## 2. 68 个 API 的职责边界

| 分组 | 数量 | 主要职责 | 普通 CLI 消费范围 |
|---|---:|---|---|
| releases | 9 | 发布、版本、SSE、回滚、对比、归档下载、日志、归档 | 用户侧 8 个；管理归档排除 |
| git | 3 | Git 配置、本人凭据签发和吊销 | 全部消费 |
| applications | 7 | 创建、列表、详情、修改、可访问应用、删除、反馈 | 分阶段全部消费 |
| members | 4 | 列表、新增、移除、转移 owner | 全部消费 |
| configuration | 7 | env、secret、平台配置 | 应用级 5 个；平台配置排除 |
| database | 7 | 数据库概览、恢复、管理台 SQLite 浏览 | 应用级 2 个；管理端 5 个排除 |
| internal | 2 | ForwardAuth、服务间菜单 | 排除 |
| administration | 14 | 超管应用治理、封禁、目录、凭据吊销 | 排除 |
| audit | 3 | 审计检索、导出、完整性检查 | MVP 排除，后续可做只读检索 |
| operations | 10 | 容器、部署、路由、平台健康 | 排除，保留管理台使用 |
| system | 2 | 控制面健康、JWKS | `healthz` 可供 doctor 使用 |

### 2.1 releases

- `POST /apps/{slug}/releases`：发布核心入口，参数为 `commit_sha/message`，响应为 SSE；同 SHA 重试幂等，同一应用并发发布或回滚时拒绝而非排队。
- `GET /apps/{slug}/releases`：版本列表并返回 `baseline`，用于 NOOP 判断和“push 成功但 release 中断”的恢复。
- `GET /apps/{slug}/releases/{id}/events`：按 `since_seq` 回放并续订 SSE；publish 与 rollback 共用。
- `GET /apps/{slug}/rollback/preflight`：owner 回滚前预检，说明走镜像秒切还是重建。
- `POST /apps/{slug}/rollback`：异步回滚，返回 `release_id`，继续订阅统一 events。
- `GET /apps/{slug}/releases/compare`：比较两个 vN tag，适合 `versions compare`，不替代本地 `git diff`。
- `GET /apps/{slug}/archive`：历史版本导出；D9 后不再用于 pull。
- `GET /apps/{slug}/logs`：runtime/build 日志，`follow=1` 为 SSE。
- `POST /admin/apps/{slug}/archive`：L3 管理动作，不进入普通 CLI。

### 2.2 git

- `GET /apps/{slug}/git-config` 返回 `repo_url/username/bound/token_hint/issued_at`，绝不返回 token，是 init、publish 和 git status 的统一预检入口。
- `POST /git/credentials` 签发用户级凭据；已有凭据必须显式 `rotate=true`。
- `DELETE /git/credentials` 幂等吊销本人全部 Git 凭据，CLI 必须提示会影响该用户的全部协作仓库。

安全边界：明文 token 只在创建应用响应或凭据签发响应中出现一次；不得写入 binding、日志、JSON 输出、命令行参数或 remote URL；落入受控凭据存储后立即执行 `git ls-remote` 探活。

### 2.3 applications

- `POST /apps` 是创建应用权威入口，body 为完整 AppYaml；首次返回 201，同 owner 重入返回 200，其他 owner 占用返回 409。
- `GET /apps` 返回 owner 创建的应用，适合 `app list` 和本地绑定恢复。
- `GET /apps/{slug}` 返回生命周期、`remote_main_head/repo_url/current_version/running_release_id` 等发布前信息。
- `PATCH /apps/{slug}` 修改 title/description。
- `GET /accessible-apps` 支撑成员加入已有应用和空目录 clone。
- `POST /apps/{slug}/actions/delete` 是 owner 受控软删除，需 reason 与二次确认。
- `POST /feedback` 可进入 `app feedback`，但不阻塞主链。

创建接口已完成仓库创建和 `main` 初始化，publish 不应再次尝试建仓；响应中的 `repo_url` 是仓库唯一事实源。

### 2.4 members

- `GET /apps/{slug}/members`：成员列表，CLI 通道按 owner 权限处理。
- `POST /apps/{slug}/members`：新增成员并同步 Gitea collaborator。
- `DELETE /apps/{slug}/members/{user_id}`：移除应用访问权，但不能吊销用户级 Git token。
- `POST /apps/{slug}/members/transfer-owner`：高风险操作，必须带 reason 并二次确认。

### 2.5 configuration

- `GET/PUT /apps/{slug}/env` 进入 `app env`；平台保留键由服务端和 CLI 双侧拦截。
- `GET/PUT/DELETE /apps/{slug}/secrets` 进入 `app secret`；列表只返回键名，永不回显值。
- `GET/PUT /admin/config` 仅供超管管理台，不进入普通 CLI。

### 2.6 database

- `GET /apps/{slug}/db` 返回库大小、表行数和备份列表，进入 `app db info/backups`。
- `POST /apps/{slug}/db/restore` 由 owner 恢复备份；服务端先做现场快照，CLI 必须要求输入 slug 确认。
- `/admin/sqlite/*` 五个接口属于管理台的表浏览、schema、只读 SQL 和备份能力，不进入普通 CLI。

### 2.7 其余分组

- `internal` 是 Traefik ForwardAuth 和服务间菜单，不能由用户 CLI 调用。
- `administration` 是超管工作台、应用治理、访问封禁和管理员凭据吊销，必须与普通 CLI 隔离。
- `audit` 只有检索允许成员读取，但 MVP 不应因此扩大命令面；后续可增加只读 `app audit list`。
- `operations` 是容器、Coolify 部署、路由和平台健康治理，应留在 Web 管理台。
- `/healthz` 可由 `app doctor` 使用；JWKS 由运行时验签方使用，CLI 不直接消费。

## 3. 正式契约与本地实现漂移

| 正式 v1 | 本地旧实现/痕迹 | 风险 |
|---|---|---|
| `/api/apphub/v1/*` | `/api/*`、`/apphub/api/*` 混用 | 硬编码旧前缀会整体不可用 |
| `/apps/{slug}/releases/compare` | `/apps/{slug}/diff` | 版本比较可能 404 |
| `/members/{user_id}` | `/members/{email}` | 成员移除不兼容 |
| `new_owner_user_id` | `new_owner_email` | owner 转移不兼容 |
| `/admin/users/{user_id}/git-credentials/revoke` | `{email}` | 管理参数漂移 |
| 创建响应含 `app_id/path/owner_user_id` | 旧实现以 `slug/status/repo_url/owner_email` 为主 | binding 不能依赖旧字段 |

处理原则：

1. `opscli/app` 只依赖 Apifox 正式 v1 路径和模型。
2. API base URL 与版本前缀集中在 transport 层，业务层不得拼 URL。
3. 为每个 CLI 消费接口建立 respx 契约测试，覆盖方法、路径、body、状态码和敏感字段。
4. 过渡期响应可采用“必填字段严格、兼容字段宽松”的解析，但不能并行维护两套路由。

## 4. 当前 opscli app 的根本缺口

### 4.1 transport

- 默认地址仍是临时占位地址。
- 只实现 `create_site()`，且只发送 `{name}`，不符合 AppYaml。
- 无 Git、releases、SSE、成员、配置和数据库接口。
- 错误映射未覆盖 401/403/404/409/426/429/502/503 的业务语义。

### 4.2 domain 与 binding

- `SiteBinding` 仍使用 `site_id/site_name`，不识别正式 `app_id`。
- binding schema v1 无生命周期、默认分支、owner、Git 用户名等信息。
- 无 AppYaml、GitConfig、Release、SSE Event 等稳定类型。
- 无法表达一站点一仓库的迁移状态。

### 4.3 manager 与 gitops

- 全局 `target_repo_url` 导致全部站点共用仓库。
- `init_git()` 会把真实 `repo_url` 覆盖成全局仓库。
- 模板分支直接成为本地 main，与服务端初始化的 `origin/main` 可能没有共同祖先。
- `push()` 只做本地提交和 Git push，不读应用状态、git-config、baseline，也不触发 release。
- 无 credential store、fetch、非 fast-forward、NOOP、push 后中断恢复和 SSE。

### 4.4 commands 与 tests

当前只暴露 `create/init/push`，测试还固定断言“只允许三个命令”，与 AppHub 已有正式用户能力不匹配。

## 5. 第一阶段命令面

```text
opscli app create <slug> [--path PATH] [--runtime fastapi]
opscli app init [PATH]
opscli app push [PATH] -m MESSAGE
```

命令数量仍然是三个。应用详情、Git 配置、凭据签发、版本 baseline、release 创建和 SSE 续订均作为三个命令内部调用，不单独暴露为新命令。

第一阶段不增加以下命令：`publish`、`pull`、`versions`、`rollback`、`logs`、`git`、`members`、`env`、`secret`、`db`、`list/show/update/delete`。这些能力只保留在后续规划中。

## 6. 核心流程

### 6.1 create

1. 根据参数生成或读取完整 `app.yaml`，使用与 AppHub 同源的 AppYaml 模型做本地校验。
2. 调用 `POST /api/apphub/v1/apps`。
3. 保存响应中的 `app_id/slug/repo_url/owner/git_username`，禁止自行构造仓库 URL。
4. 若响应携带 `git_credential`，立即写入受控凭据存储并从内存丢弃。
5. 执行 `git ls-remote <repo_url> refs/heads/main`，确认仓库和 main 可访问。
6. 保存 `.opscli/app.json` schema v2。

若返回 `git_warning` 或仓库暂不可访问，CLI 不尝试建仓，而是返回 `GIT-REPO-NOT-READY` 或 `GIT-002`，提示重试正式 create/git bind 流程或联系平台。

### 6.2 init

| 场景 | 幂等动作 |
|---|---|
| 新建应用 | create 已登记 → 初始化本地 Git → 设置 origin → fetch `origin/main` → 从远端 main 建本地 main → 应用模板内容 → 首次模板 commit |
| 已有本地项目 | 读取 app.yaml/binding → 补 origin、凭据和仓库级作者配置；不覆盖用户源码 |
| 加入已有应用 | 用 accessible-apps 确认成员资格 → git-config → 必要时 bind → clone → 设置仓库级作者配置 |

关键约束：

- 先 fetch 并基于 `origin/main` 建分支，不能让模板历史产生另一个 root commit。
- `bound=true` 但本机无凭据时，必须提示确认后 rotate，不能静默让旧设备失效。
- `git ls-remote` 成功后才能报告 init 完成。

### 6.3 push

```text
加载 binding/app.yaml
→ GET app detail + git-config
→ 校验生命周期与凭据
→ 本地 validate + gitleaks
→ git fetch origin main
→ 判断本地是否包含 origin/main
→ dirty 时 auto-commit
→ 读取 releases.baseline
→ 普通 git push origin HEAD:main
→ 校验远端 main SHA
→ POST releases {commit_sha, message}
→ 消费 SSE，记录 release_id/last_seq
→ 断线用 events?since_seq= 续订
```

NOOP 与恢复规则：

- 工作区干净且 `origin/main == baseline.commit_sha`：返回 GIT-004 提示级 NOOP。
- 工作区干净但 `origin/main != baseline.commit_sha`：说明之前 push 成功、release 未完成，直接以远端 HEAD 发起 release。
- 本地不包含 `origin/main`：返回 GIT-003，提示 pull/merge；绝不 force push。

## 7. 模块结构

```text
opscli/app/
├── commands/
│   ├── cli.py
│   └── cli.py
├── domain/
│   ├── models.py
│   ├── binding.py
│   ├── appyaml.py
│   ├── events.py
│   ├── constants.py
│   └── exceptions.py
├── services/
│   ├── manager.py
│   ├── project.py
│   ├── gitops.py
│   ├── gitcred.py
│   ├── publish.py
│   ├── sse.py
│   └── sse.py
└── transport/
    └── client.py
```

transport 只负责 HTTP/SSE 和错误信封；services 负责编排；domain 负责稳定模型；commands 只做参数和输出。

## 8. binding schema v2

```json
{
  schema_version: 2,
  app_id: app-123,
  slug: sales-dashboard,
  title: 销售看板,
  repo_url: http://10.1.13.143:3000/apps/sales-dashboard.git,
  default_branch: main,
  owner_user_id: user-123,
  owner_email: owner@aukeys.com,
  git_username: owner,
  template_repo_url: ...,
  template_branch: template
}
```

禁止保存 token、cookie、session id 或任何管理凭据。

v1 迁移：读取旧 slug → 调应用详情和 git-config → 获取 `app_id/repo_url` → 将固定 `apphub.git` origin 改为独立 repo → 保存 schema v2。无法确认远端身份时必须停止，不能静默覆盖 origin。

## 9. 错误码与恢复动作

| 错误码 | 场景 | CLI 动作 |
|---|---|---|
| `GIT-001` | Git 不存在或版本低于 2.30 | 提示安装/升级 |
| `GIT-002` | 本机无凭据或凭据失效 | 提示 `app git bind` |
| `GIT-003` | 非 fast-forward | 提示 pull/merge 后重发 |
| `GIT-004` | 无新内容且远端已发布 | 提示级 NOOP |
| `GIT-010` | commit SHA 不在 remote main | 先 push 再发布 |
| `GIT-CRED-EXISTS` | 已有凭据且未 rotate | 提示 `--rotate` 或 revoke |
| `PUB-409-IN-PROGRESS` | 当前已有发布/回滚 | 等待结束或由管理台取消 |
| `GIT-REPO-NOT-READY` | create 后仓库或 main 暂不可访问 | 不直接建仓，提示重试或联系平台 |
| 401 | 登录失效 | 提示 `opscli auth login` |
| 403 | 权限不足 | 区分 member/owner/超管 |
| 426 | CLI 版本过低 | 提示升级 opscli |
| 429 | 日志 follow 等资源超限 | 结束或减少连接 |
| 502/503 | AppHub/Gitea/Coolify 异常 | 保留本地状态并允许幂等重试 |

## 10. 分阶段实施

### 第一阶段：三个命令完成独立仓库发布闭环

1. 移除 `APP_TARGET_REPO_URL_DEFAULT/OPSCLI_APP_REPO_URL` 作为站点仓库来源。
2. AppHubClient 改为 base URL + `/api/apphub/v1` 正式接口。
3. 实现 AppYaml、AppCreated、GitConfig、GitCredential 模型。
4. binding 升级 schema v2，并提供 v1 迁移。
5. create 使用返回的独立 `repo_url`。
6. init 基于 `origin/main` 建立共同祖先。
7. 增加 Git 凭据存储和 `ls-remote` 探活。

8. 在现有 `push` 中实现 fetch、非 FF、NOOP、release 创建和 SSE resume。
9. 不新增其他命令。

### 后续阶段：用户自助能力

1. applications list/show/update/delete/feedback。
2. git status/bind/revoke。
3. members 全组。
4. env/secret 全组。
5. db info/backups/restore。

### 可选增强

1. versions compare 和 archive export。
2. audit 只读检索。
3. app doctor 调 `/healthz` 并检查 Git/AppHub/Gitea 连通性。

## 11. 测试策略

1. transport 契约测试覆盖每个 CLI 消费的正式 v1 路径、方法、请求体和状态码。
2. token 安全测试确保日志、异常、JSON 输出、binding 和 remote URL 均无明文 token。
3. Git 集成测试使用 tmp_path 裸仓库模拟初始化 main、双人非 FF、push 后 release 中断和恢复。
4. SSE 测试覆盖首帧、序号、断线、resume、不重复、CANCELLED 和失败终态。
5. binding 迁移测试覆盖共享仓库 v1 → 独立仓库 v2，以及 origin 不匹配时禁止静默覆盖。
6. 删除“只允许三个命令”的旧测试，改为按命令组验证帮助与统一输出。
7. 网络和凭据测试全部使用 mock/tmp_path，不访问真实 AppHub、Gitea、Keychain 或用户 Git 配置。

## 12. 最终修改顺序

```text
正式 AppHubClient（仅必需接口）
→ AppYaml 与 binding schema v2
→ 一站点一 repo 的 create/init
→ Git 凭据与 ls-remote
→ push + releases + SSE
```

本轮不新增 AppHub API。不能先在当前 `push_all()` 上增加“仓库不存在就创建”的判断，因为这会把控制面特权下沉到 CLI，并继续掩盖共享仓库和正式 API 尚未接入两个根本问题。
