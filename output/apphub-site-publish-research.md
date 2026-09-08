# AppHub 站点推送命令研究报告

> 日期：2026-08-31  
> 阶段：Super Dev `research`  
> 目标：为 `open-opscli` 新增 AppHub 发布命令提供事实基线，不进入编码。

## 1. 研究问题

本次研究聚焦四个问题：

1. AppHub 当前真正生效的源码发布架构是什么。
2. `open-opscli` 应承担哪些职责，哪些职责必须留在 AppHub 控制面。
3. Codex 当前生成的独立站点工程能否直接被 AppHub 接收和部署。
4. 新命令应采用上传源码包、服务端代写 Git，还是本地 Git 直推。

## 2. 资料优先级

### 2.1 第一优先级：AppHub 现行冻结契约与代码

- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/21-git直连发布链重构方案.md`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/contracts/cli-api.yaml`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/contracts/error-codes.md`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/tasks/T09-opscli骨架与init-run.md`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/tasks/T11-publish链与四组子命令.md`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/tasks/T36-Gitea账号与凭证面.md`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/docs/tasks/T37-密钥泄漏双层防线.md`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/apphub/api/publish.py`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/apphub/api/git_credentials.py`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/apphub/schemas/appyaml.py`
- `E:/wwwroot/localProjects/codex-custom-sites-all/ops-apphub/apphub/runtime/command.py`

### 2.2 第二优先级：当前 opscli 工程事实

- `opscli/cli.py` 使用 Typer 注册子命令组。
- `pyproject.toml` 已包含 `typer>=0.12`、`httpx>=0.27`、`rich>=13`、`keyring>=25`。
- 当前仓库尚不存在 `opscli/app/` 模块。
- `opscli/config.py` 提供统一 `CONFIG_DIR` 和版本号。
- `opscli/auth` 已有登录态与 session 持久化能力。
- 项目约定新增复杂模块采用 `commands/services/transport/domain` 四层结构。

### 2.3 第三优先级：Codex 站点工程事实

- `codex-custom-sites` 的标准站点是 React、TypeScript、Vite/vinext、Worker、pnpm 工程。
- 每个站点包含独立 `package.json`、`pnpm-lock.yaml`、`.openai/hosting.json` 和 `site.config.json`。
- 当前 `sites/` 为空，但标准模板和仓库契约已经定义。
- 其现有发布目标是 Codex Sites，不是 AppHub 的 Python runtime。

### 2.4 外部官方资料

- Git 凭据机制：`https://git-scm.com/docs/gitcredentials`
- Git credential-store：`https://git-scm.com/docs/git-credential-store`
- Git push 与 non-fast-forward：`https://git-scm.com/docs/git-push`
- Gitea REST API：`https://docs.gitea.com/api/1.25/`
- Gitleaks 官方仓库与命令说明：`https://github.com/gitleaks/gitleaks`

外部资料只用于验证 Git/Gitea/Gitleaks 的通用行为；AppHub 内部端点、错误码和版本约束仍以冻结契约为唯一权威。

## 3. 关键事实

### 3.1 旧方案对比文档已不是现行架构

`docs/AppHub源码推送技术方案对比.md` 建议 MVP 采用“opscli 上传源码包，AppHub 服务端代写 Git”，长期再演进为独立 Git Writer。

但 AppHub 在 2026-08-28 已通过 D9 决策推翻该链路。现行链路是：

```text
本地真实 Git 仓库
  -> opscli 本地校验与密钥扫描
  -> 普通 git commit / git push
  -> POST /api/apps/{slug}/releases {commit_sha, message}
  -> AppHub 控制面复验、打 vN tag、触发 Coolify 部署
  -> SSE 返回发布进度与终态
```

因此以下旧设计不得进入新命令：

- tar/zip 源码包上传。
- AppHub 服务端 bot 代提交源码。
- `.apphub/state` 基线文件。
- `--force` 覆盖发布。
- 客户端持有 Gitea admin token 或 token-issuer 凭据。
- 多站点共享仓库中的 `sites/{site_id}` 目录写入模型。

### 3.2 AppHub 当前是“一应用一仓库”，不是站点 Monorepo

冻结契约规定控制面创建 Gitea 仓库 `apps/{slug}`，成员通过 collaborator 权限访问对应仓库。`opscli` 只持有当前用户的用户级 scoped token。

这与旧调研中的“AppHub 专属 Monorepo + `sites/{site_id}` 目录隔离”不同。新命令必须服从 AppHub 现行仓库模型，不应自行构造共享 Monorepo 路径。

### 3.3 `push` 与 `publish` 是两个不同动作

AppHub 明确保持：

- `git push` 只表示源码已经进入应用仓库。
- `POST /api/apps/{slug}/releases` 才表示用户授权 AppHub 执行发布。
- 服务端必须在部署前完成 commit 位于 main、服务端 gitleaks、tag、部署和健康验证。

因此命令名应为 `opscli app publish`，内部包含普通 push 和显式 release 调用；不建议把用户面命名为 `push`，否则会弱化“部署授权”的语义。

### 3.4 首次初始化不能偷偷塞进 publish

冻结契约规定：

- `POST /api/apps` 是 `opscli app init/create` 的落点。
- `publish` 遇到未登记应用应提示先初始化。
- 同 owner 重复登记为幂等重入，其他 owner 占用同 slug 返回 409。

因此“一键发布”应理解为：初始化完成后，每次发布只需一条命令。首次使用仍需要 `opscli app init` 或由 Codex Skill 先执行初始化编排。

### 3.5 凭据边界已经冻结

AppHub 现行凭据模型：

- 控制面持有 Gitea 特权凭据。
- `opscli` 永不持有 Gitea admin token。
- 用户 token scope 为 `write:repository`，明文只在签发响应出现一次。
- `GET /api/apps/{slug}/git-config` 只返回 `bound`、`username`、`token_hint`、`repo_url`。
- MVP 每账号只允许一枚有效 token；换机或丢失时使用显式 rotate。
- AppHub 现行裁决要求 token 写入受控本地 credential 文件，并通过 Git credential 协议使用；任何日志、异常和命令参数都不得出现 token。

Git 官方文档同时明确 `credential-store` 把凭据以未加密形式保存在磁盘。这意味着该设计可以遵循 AppHub 冻结决策，但必须在文档和 CLI 输出中如实披露，并用严格文件权限、日志脱敏和吊销能力降低风险。

### 3.6 发布状态机与断线恢复已经冻结

`POST /api/apps/{slug}/releases`：

- 请求体：`{commit_sha, message}`。
- `commit_sha` 必须是 40 位小写十六进制 SHA。
- `message` 最长 512 字符。
- 成功响应为 SSE。
- release id 通过响应头 `X-Apphub-Release-Id` 和首帧双通道返回。
- 终结事件使用 `event: done`。
- 心跳使用 `: ping`。
- 句柄文件固定为 `{CONFIG_DIR}/apps/{slug}/publish-session.json`。
- `--resume` 使用 `GET /api/apps/{slug}/releases/{id}/events?since_seq=` 恢复。
- 同一 commit SHA 重试时由服务端幂等续跑。

### 3.7 Codex 站点与 AppHub runtime 当前不兼容

这是本次研究最重要的产品缺口。

Codex 标准站点是 Node.js/React/TypeScript/Worker 工程；AppHub 当前 `app.yaml` 只允许：

- `streamlit`
- `fastapi`
- `gradio`

`static`、`dash`、`flask` 被标记为二期，当前服务端启动命令也只实现上述三种 Python runtime。

因此即使 `opscli app publish` 完整实现，当前 Codex 标准站点仍会在 `app.yaml` 校验或部署启动阶段失败。不能把“源码成功 push”描述成“站点已可在 AppHub 发布”。

## 4. 可选路线

### 路线 A：只实现当前 AppHub 支持范围的 publish

适用：已经是合法 AppHub Python 应用的项目。

优点：完全遵守冻结契约，可独立开发和测试。  
缺点：不能闭合“Codex React 站点一键发布到 AppHub”的原始业务目标。

### 路线 B：先扩展 AppHub static/node runtime，再实现 publish

适用：真正承接 Codex 标准站点。

需要 AppHub 跨仓变更：

- 扩展 `app.yaml` runtime 契约。
- 明确 Node 版本、包管理器、安装命令、构建命令、启动命令和内部端口。
- 明确 Vite/vinext/Worker 在 Coolify 的构建与运行形态。
- 扩展部署与健康检查。
- 更新冻结 OpenAPI、错误码、业务规范和控制面测试。

优点：闭合业务目标。  
缺点：不是单纯 opscli 改动，必须先走 AppHub 契约变更流程。

### 路线 C：Codex Builder 输出 AppHub Python 包装工程

示例：把静态构建产物嵌入 FastAPI，由 Python 容器托管。

优点：不立即扩展 runtime 枚举。  
缺点：改变现有 Node BFF、Worker、D1/R2 和 Codex Sites 能力模型，属于高耦合适配，不建议作为默认架构。

## 5. 推荐结论

采用“两轨并行、契约不混淆”的方案：

1. 在 `open-opscli` 设计并实现符合 D9 的 `opscli app publish`，命令本身不做源码包上传。
2. 把首次登记与凭据绑定保留在 `opscli app init` / `opscli app git bind`，publish 不隐式创建应用。
3. 对不在 AppHub MVP runtime 白名单内的站点，在本地校验阶段明确失败，禁止 commit、push 和 release。
4. 另立 AppHub `static/node` runtime 契约变更任务，完成后 Codex 标准站点才能真正进入 AppHub。
5. Codex Skill 用户面可以编排“缺初始化则 init，已初始化则 publish”，但 Skill 不能绕过 opscli 的安全检查，也不能把两次授权动作伪装成一次隐式行为。

## 6. 对本次 opscli 任务的范围建议

本次评审建议冻结为：

- 新增 `opscli app` 四层模块骨架。
- 首期交付 `opscli app publish -m` 和 `--resume`。
- 同批交付 publish 必需的 AppHub client、Git 编排、SSE、session handle、错误映射和凭据读取能力。
- 如果当前仓库没有可复用的 init/bind，实现最小 `git status/bind/revoke` 支撑命令；否则 publish 无法在新设备上形成闭环。
- 不在本任务内扩展 AppHub runtime，不伪造 Node/static 已支持。

## 7. 待确认决策

进入 Spec 和编码前，需要用户确认以下产品决策：

1. 本次是否接受“先交付 D9 publish，Codex Node 站点仍需 AppHub runtime 扩展”的分阶段方案。
2. 本次是否同时实现 `app init` 与 `app git bind/status/revoke`，还是只消费已经存在的远端初始化结果。
3. AppHub CLI API 的生产 base URL 是否固定使用 `https://ops.xenkee.com`，还是增加 `OPSCLI_APPHUB_URL` 作为测试/私有环境覆盖项。
4. gitleaks 内网二进制分发源 `TODO(GITLEAKS-SRC)` 尚未关闭时，publish 是否允许以“未安装则阻断并给安装指引”先行交付。

