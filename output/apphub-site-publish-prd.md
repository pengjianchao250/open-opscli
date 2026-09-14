# AppHub 站点发布命令 PRD

> 日期：2026-08-31  
> 状态：待确认  
> 产品入口：`opscli app publish`

## 1. 背景

用户在 Codex 中通过自然语言生成或修改应用源码后，需要用低心智成本的命令把当前代码提交到 AppHub，并看到部署进度和最终访问地址。

AppHub 当前已冻结为 D9 git 直连发布链。`opscli` 不是源码上传器，也不是 Git 特权代理，而是本地校验、普通 Git 操作和 AppHub 发布授权的编排入口。

## 2. 产品目标

### 2.1 P0 目标

1. 已初始化的 AppHub 应用可以通过一条命令完成校验、提交、普通 push、发布登记和状态展示。
2. 发布失败时输出稳定错误码、可执行修复建议和可恢复路径。
3. 网络断开后可以用 `--resume` 继续读取同一次发布，不重复创建版本。
4. token、密钥原文和特权凭据不进入日志、终端输出、argv 或本地发布句柄。
5. 严格遵守 AppHub 冻结 API 与 D9 发布语义。

### 2.2 P1 目标

1. 提供 `opscli app git status/bind/revoke`，让新设备和凭据失效场景可自助恢复。
2. 由 Codex Skill 在用户明确授权后编排 init/publish，但不得扩大 Git 操作范围。
3. 支持结构化输出，方便 Codex 读取 release、commit、version、URL 和错误信息。

### 2.3 非目标

- 不实现 tar/zip 源码上传。
- 不由 opscli 或 AppHub bot 代用户提交源码。
- 不支持强制 push、rebase 或自动覆盖远端历史。
- 不在 opscli 中实现 Gitea 建号、建仓、协作者管理或打 tag 的特权 API。
- 不在本任务中扩展 AppHub 的 Node/static runtime。
- 不把 Codex Sites 的 `.openai/hosting.json` 当作 AppHub 部署清单。

## 3. 用户画像

### 3.1 业务用户

- 通过 Codex 创建应用。
- 不希望手工处理 Git 凭据、提交 SHA、SSE 和发布状态机。
- 可以理解“首次初始化”和“后续发布”是两个阶段。

### 3.2 Codex Skill

- 能读取项目文件并执行命令。
- 可以按用户明确授权执行一次普通 commit 和一次普通 push。
- 遇到冲突时只给出安全修复步骤，不执行强推或历史重写。

### 3.3 平台开发与 SRE

- 需要稳定错误码、请求 ID、release ID、commit SHA 和审计链。
- 需要确认客户端不会泄露用户 token 或绕过服务端发布门禁。

## 4. 核心用户旅程

### 4.1 已初始化应用发布

```bash
opscli app publish -m "更新销售日报筛选条件"
```

系统行为：

1. 读取并校验 `app.yaml`。
2. 检查 Git 版本、仓库、main 分支、origin 和凭据状态。
3. 执行本地 validate 与强制 gitleaks。
4. 工作区有改动时执行 `git add -A` 和一次普通 commit。
5. 执行普通 `git push origin main`。
6. 取得 40 位 `commit_sha`。
7. 调用 `POST /api/apps/{slug}/releases`。
8. 实时显示 SSE 进度。
9. 成功时显示版本、commit 和正式地址；失败时显示错误码与修复建议。

### 4.2 无改动发布

如果工作区干净且 `origin/main` 等于最近一次非回滚健康发布的 commit SHA：

- 输出“没有可发布的改动”。
- 退出码为 0。
- 不调用 release API。

如果工作区干净但 `origin/main` 比最近发布更新：

- 不创建新 commit，不重复 push。
- 直接用 `origin/main` HEAD 发起 release。
- 用于恢复“push 成功但 release 请求失败”的中间态。

### 4.3 非 fast-forward 冲突

- 识别普通 push 的 non-fast-forward 失败。
- 输出 `GIT-003`。
- 建议先执行 `opscli app pull` 或安全的 `git pull` 合并，再重新发布。
- 不自动 rebase，不执行 force push。

### 4.4 发布断线恢复

```bash
opscli app publish --resume
```

- 读取 `{CONFIG_DIR}/apps/{slug}/publish-session.json`。
- 使用 `release_id` 和 `last_seq` 调用事件回放端点。
- 不重复打印已消费事件。
- 终态后删除或归档句柄文件。

### 4.5 凭据缺失或失效

- 本地无凭据时输出 `GIT-002` 和 `opscli app git bind` 指引。
- 服务端 `bound=true` 但本地无凭据时，要求用户确认 rotate。
- bind 成功后必须执行 `git ls-remote` 探活，探活成功才报告绑定完成。

### 4.6 runtime 不兼容

当项目是 Codex React/TypeScript 站点，但 `app.yaml` runtime 不在 AppHub MVP 白名单内：

- 在任何 commit、push 和 release 之前失败。
- 明确提示“AppHub 当前仅支持 streamlit/fastapi/gradio；Node/static 站点需先完成 AppHub runtime 扩展”。
- 不提供把 `.openai/hosting.json` 自动转换为 `app.yaml` 的隐式降级。

## 5. 命令设计

### 5.1 主命令

```text
opscli app publish [PATH]
  -m, --message TEXT
  --resume
  --pretty
  --json
```

约束：

- `PATH` 默认当前目录。
- `--message` 最长 512 字符。
- 首次发布建议必填 message；交互终端可提示输入，非交互模式缺失则失败。
- `--resume` 与 `--message` 互斥。
- `--json` 输出单个稳定 JSON 对象，不混入进度装饰字符。

### 5.2 支撑命令

```text
opscli app git status [PATH]
opscli app git bind [PATH] [--rotate]
opscli app git revoke
```

可后续扩展：

```text
opscli app init
opscli app validate
opscli app pull
opscli app versions
opscli app rollback
opscli app logs
```

## 6. 功能需求

### FR-1 项目识别

- 从目标目录读取 `app.yaml`。
- slug 以 `app.yaml.name` 为唯一来源。
- 禁止从目录名猜测并覆盖 manifest。
- 检查当前 Git remote 对应 `apps/{slug}`。

### FR-2 本地校验

- 使用与 AppHub 同构的 AppYaml 模型。
- 未知字段拒绝。
- runtime、slug、datasets、visibility 等规则与冻结 schema 一致。
- 本地校验失败时不产生 Git 副作用。

### FR-3 密钥扫描

- publish 前强制执行 gitleaks。
- 扫描工作区和领先于 `origin/main` 的本地提交。
- 命中时返回 `AUTH-003`，不产生本轮 commit/push。
- 输出仅含规则、文件和行号，不含密钥原文。
- 二进制缺失、哈希不匹配或执行异常按 fail-closed 处理。

### FR-4 Git 编排

- Git 最低版本 2.30。
- 只允许普通 `git add -A`、commit、push、fetch、rev-parse、status、ls-remote 等必要命令。
- 所有 subprocess 使用参数数组，禁止 shell 拼接。
- token 不进入命令参数。
- publish 永不传 `--force`。

### FR-5 AppHub 认证

- CLI API 使用 `X-Session-Id` 和 `X-Opscli-Version`。
- AppHub CLI 请求禁止携带 cookie。
- 低版本 426 统一提示 `opscli self-update`。

### FR-6 发布 API

- 请求体严格为 `commit_sha` 与可选 `message`。
- commit SHA 固定 40 位小写。
- 处理 pre-stream 401/403/404/409/422/426/502。
- 处理 200 SSE 中的 failed 终帧。

### FR-7 SSE

- 支持 `data:` JSON、`event: done` 和 `: ping`。
- 忽略 `hidden` 事件。
- 以 `seq` 去重并防止倒序覆盖。
- release id 以响应头和首帧双通道交叉校验。

### FR-8 断线句柄

- 路径固定为 `{CONFIG_DIR}/apps/{slug}/publish-session.json`。
- 字段固定为 `release_id`、`last_seq`、`slug`、`commit_sha`、`started_at`。
- 原子写入，文件损坏时给可恢复提示，不猜测 release id。

### FR-9 输出

- 成功至少返回 `slug`、`release_id`、`version`、`commit_sha`、`tag`、`url`、`status`。
- 失败至少返回 `code`、`message`、`fix_hint`、`request_id`、`release_id`。
- token、Authorization、cookie、密钥原文必须统一脱敏。

## 7. 非功能需求

### NFR-1 安全

- 凭据文件仅当前用户可读写。
- 不记录 HTTP 签发响应原文。
- 不记录 Git credential approve 输入。
- 不允许软链接把句柄或凭据写出配置目录。

### NFR-2 可靠性

- 同一 SHA 的 release 重试依赖服务端幂等。
- 网络超时不自动重复 commit 或 push。
- 发布中断后优先 resume，不创建第二次 release。

### NFR-3 跨平台

- 支持 Windows、macOS、Linux。
- Windows 路径传给 Git 时使用 Git 可接受的标准路径形态。
- 终端输出兼容 Windows UTF-8 重配置和窄终端。

### NFR-4 可测试性

- HTTP 使用可注入 transport 或 respx。
- Git 使用临时裸仓库和可替换 runner。
- 凭据层使用临时 HOME/USERPROFILE，禁止污染开发机真实凭据。

## 8. 错误语义

| 场景 | 结果 |
|---|---|
| Git 缺失/版本过低 | `GIT-001`，退出码 1 |
| 凭据缺失/失效 | `GIT-002`，退出码 1 |
| non-fast-forward | `GIT-003`，退出码 1 |
| 无可发布改动 | 提示级 NOOP，退出码 0 |
| commit 不在 main | SSE 终帧 `GIT-010`，退出码 1 |
| 本地或服务端密钥命中 | `AUTH-003`，退出码 1 |
| 另有发布进行中 | `PUB-409-IN-PROGRESS`，退出码 1 |
| CLI 版本过低 | `UPGRADE_REQUIRED`，退出码 1 |
| runtime 不支持 | `YAML-INVALID` 或专用本地错误，退出码 1 |

## 9. 验收标准

1. dirty 工作区可完成一次普通 commit、push 和 release，终态显示健康版本和 URL。
2. `git push` 命令行中不出现 force 参数。
3. token 不出现在 stdout、stderr、日志、异常、argv 和 session 文件。
4. non-fast-forward 不修改本地历史，给出合并指引。
5. push 成功但 release 请求失败后，重试能发布远端 HEAD。
6. 相同远端 HEAD 已健康发布时 NOOP 退出 0。
7. SSE 断线后 resume 不漏帧、不重帧、不创建新版本。
8. 426、409、AUTH-003、GIT-010 均按冻结契约呈现。
9. Node/static Codex 站点在 Git 副作用前被明确阻断。
10. Windows 路径、UTF-8 输出和 credential 文件权限有专项测试。

## 10. 发布策略

- 首先以隐藏或 beta 命令交付相关面测试。
- 完成 AppHub 测试环境端到端后再进入首个 GA 版本。
- GA 当天由 AppHub 回填 `min_version`，低版本客户端开始收到 426。
- 若 Node/static runtime 尚未完成，文档必须明确当前支持范围，不得宣传为 Codex 站点全量可用。

