# AppHub 站点发布命令技术架构

> 日期：2026-08-31  
> 状态：待确认  
> 适用仓库：`open-opscli`

## 1. 架构原则

1. 以 AppHub D9 和冻结 OpenAPI 为权威，不延续 tar 上传旧链路。
2. opscli 是编排入口，不是 Gitea 特权执行者。
3. `push` 不等于 `publish`，release API 是明确的部署授权边界。
4. Git 冲突使用原生 non-fast-forward 语义，不提供 force 旁路。
5. 所有 Git 副作用必须发生在 manifest 校验和本地密钥扫描之后。
6. Node/static runtime 未进入 AppHub 契约前，本地失败，不做“先推上去再说”的半成功交付。

## 2. 总体链路

```text
Codex / 用户
  -> opscli app publish
      -> ProjectLoader
      -> AppYamlValidator
      -> GitPreflight
      -> SecretScanner
      -> GitPublisher
      -> AppHubClient.create_release
      -> SSEConsumer / ResumeStore
  -> 用户级 Gitea 仓库 apps/{slug}
  -> AppHub 控制面
      -> commit 在 main 校验
      -> 服务端 gitleaks 复验
      -> vN tag
      -> Coolify 部署
      -> verifying
  -> 正式 URL
```

## 3. 模块结构

遵循 opscli 既有四层规范：

```text
opscli/app/
├── __init__.py
├── cli.py
├── commands/
│   └── cli.py
├── domain/
│   ├── exceptions.py
│   ├── models.py
│   └── constants.py
├── services/
│   ├── manager.py
│   ├── project.py
│   ├── validation.py
│   ├── gitops.py
│   ├── gitcred.py
│   ├── publish.py
│   ├── sse.py
│   └── session.py
└── transport/
    └── client.py
```

### 3.1 职责边界

| 模块 | 职责 | 禁止事项 |
|---|---|---|
| `commands/cli.py` | Typer 参数、交互确认、Rich/JSON 输出、退出码 | 不直接调 httpx 或 subprocess |
| `services/manager.py` | 用例编排、依赖注入 | 不解析 SSE 字符串细节 |
| `services/project.py` | 路径解析、读取 app.yaml、定位 repo root | 不修改文件 |
| `services/validation.py` | AppYaml 同构校验、runtime 门禁、gitleaks 编排 | 不做 Git push |
| `services/gitops.py` | Git 版本、状态、fetch、commit、push、SHA、NOOP 判定 | 不接触 token 明文 |
| `services/gitcred.py` | Git credential 协议、受控文件、ls-remote 探活 | 不写日志原文，不使用系统 helper |
| `services/publish.py` | publish 状态机编排 | 不持有 Gitea admin 能力 |
| `services/sse.py` | SSE 帧解析、seq 去重、终态识别 | 不负责 HTTP 认证 |
| `services/session.py` | publish-session 原子读写 | 不保存 token |
| `transport/client.py` | AppHub HTTP、认证头、错误信封、流式响应 | CLI 通道禁止 cookie |

## 4. 顶级命令注册

`opscli/cli.py` 只增加模块导入与一行注册：

```python
from opscli.app.cli import app as app_app

app.add_typer(app_app, name="app")
```

`opscli/app/cli.py` 只做兼容导出：

```python
from opscli.app.commands.cli import app

__all__ = ["app"]
```

## 5. 发布编排状态机

### 5.1 本地阶段

```text
LOAD_PROJECT
  -> VALIDATE_MANIFEST
  -> CHECK_RUNTIME_SUPPORT
  -> CHECK_GIT
  -> FETCH_REMOTE
  -> CHECK_CREDENTIAL
  -> SCAN_SECRETS
  -> CLASSIFY_CHANGE
      -> DIRTY: COMMIT -> PUSH
      -> CLEAN_AND_UNPUBLISHED_REMOTE: USE_REMOTE_HEAD
      -> CLEAN_AND_ALREADY_PUBLISHED: NOOP
  -> CREATE_RELEASE
  -> STREAM_EVENTS
  -> TERMINAL
```

### 5.2 副作用顺序

严格顺序：

1. 只读项目检查。
2. 只读 Git 检查与 fetch。
3. 本地 gitleaks。
4. `git add -A` 和 commit。
5. 普通 push。
6. release API。

不得把 gitleaks 放在 commit 之后，否则本轮密钥会进入本地 Git 历史。

### 5.3 NOOP 四象限

| 工作区 | origin/main 与最近非回滚健康发布 | 动作 |
|---|---|---|
| dirty | 任意 | commit、push、release |
| clean | 相等 | NOOP，退出 0 |
| clean | 远端更新 | 直接 release 远端 HEAD |
| clean | 无健康发布 | release 远端 HEAD |

最近发布通过 `GET /api/apps/{slug}/releases?is_rollback=false` 获取，比较完整 40 位 SHA。

## 6. Git 执行模型

### 6.1 Runner

定义单一 `GitRunner`：

- `subprocess.run` 使用参数数组。
- `shell=False`。
- 捕获 stdout/stderr 并做敏感信息脱敏。
- 支持注入环境，但不把 token 注入环境变量。
- 每个命令设置超时。

### 6.2 允许命令

- `git --version`
- `git rev-parse`
- `git status --porcelain`
- `git remote get-url origin`
- `git fetch origin main`
- `git rev-parse origin/main`
- `git add -A`
- `git commit -m`
- `git push origin main`
- `git ls-remote`
- Git credential `approve/reject/fill` 协议

### 6.3 禁止命令

- `git push --force`
- `git push -f`
- 自动 `git rebase`
- 自动 `git reset --hard`
- 自动清理用户未提交文件

## 7. 凭据实现

### 7.1 服务端接口

- `GET /api/apps/{slug}/git-config`
- `POST /api/git/credentials {rotate}`
- `DELETE /api/git/credentials`

### 7.2 本地文件

遵循 AppHub 当前裁决，凭据落受控本地文件。建议路径由 `CONFIG_DIR` 派生：

```text
{CONFIG_DIR}/app/git-credentials
```

如果必须与 AppHub 既有 T11 文档逐字兼容，可在 Spec 阶段确认是否使用其 `%USERPROFILE%/.apphub/git-credentials` 口径。当前 opscli 工程原则上应优先统一到 `CONFIG_DIR`，但这属于需要跨文档确认的差异，编码前不能擅自决定。

### 7.3 Git helper 调用

每次涉及凭据的 Git 命令显式清空系统 helper，再绑定仓库本地受控 helper：

```text
-c credential.helper=
-c credential.helper=store --file=<controlled-file>
```

需要保证参数顺序正确，避免系统 wincred/osxkeychain/libsecret 残留条目抢先命中。

### 7.4 安全要求

- 签发响应对象不可整体记录。
- token 只存在于短生命周期内存变量和 Git credential stdin。
- 写入完成后立即清空引用并执行 `git ls-remote` 探活。
- 文件权限：POSIX `0600`；Windows 使用仅当前用户 ACL 或能力等价实现。
- revoke 后同时删除本地 host 条目。

## 8. AppHub HTTP Client

### 8.1 Base URL

推荐：

- 默认 `https://ops.xenkee.com`。
- 支持 `OPSCLI_APPHUB_URL` 覆盖测试环境。
- 统一去除尾部 `/`。

### 8.2 认证头

```text
X-Session-Id: <session_id>
X-Opscli-Version: <opscli version>
Accept: application/json 或 text/event-stream
```

CLI 通道不携带 cookie，也不复用会自动加 `polarisUserToken` cookie 的通用请求方法。

### 8.3 错误解析

统一解析：

```json
{
  "code": "CONFLICT",
  "message": "...",
  "fix_hint": "...",
  "detail": {},
  "request_id": "..."
}
```

HTTP 状态与发布终帧分开处理：

- pre-stream：401/403/404/409/422/426/502。
- post-stream：HTTP 200，但 `event: done` 中 `status=failed`。

## 9. SSE 解析

### 9.1 帧模型

解析字段：

- `event`
- 多行 `data`
- 注释心跳
- 空行终结当前帧

### 9.2 业务规则

- `: ping` 只刷新存活时间，不产生用户输出。
- `hidden` 事件不展示，但可推进 `last_seq`。
- `seq <= last_seq` 的帧忽略。
- `event: done` 必须包含可识别终态。
- 首帧 release id 与响应头不一致时按协议错误失败，不猜测。

### 9.3 断线处理

- 每接收有效 seq 后原子更新句柄。
- 网络错误时保留句柄，提示 `--resume`。
- 终态成功或失败后删除句柄。
- replay 仍在进行时保持流式读取直到 done。

## 10. 本地校验与 runtime 适配

### 10.1 AppYaml 同构

短期可在 opscli 维护同构模型，但必须用契约测试防漂移：

- slug regex。
- reserved slugs。
- runtime 枚举。
- datasets alias。
- visibility。
- unknown fields。

长期建议 AppHub 通过版本化 JSON Schema 发布，opscli 构建时生成模型或运行时校验 schema，降低双份维护风险。

### 10.2 Codex 站点门禁

检测到以下特征但无合法 AppHub manifest 时：

- `package.json`
- `.openai/hosting.json`
- `site.config.json`

输出专用诊断：该目录是 Codex Sites 工程，不是当前 AppHub MVP runtime。命令不自动生成伪造 manifest。

## 11. 数据模型

### 11.1 本地发布句柄

```python
class PublishSession(BaseModel):
    release_id: int
    last_seq: int
    slug: str
    commit_sha: str
    started_at: datetime
```

### 11.2 发布结果

```python
class PublishResult(BaseModel):
    slug: str
    release_id: int | None
    status: str
    commit_sha: str
    version: str | None
    tag: str | None
    url: str | None
    error_code: str | None
    fix_hint: str | None
    request_id: str | None
```

## 12. 异常层次

```text
AppError
├── AppProjectError
├── AppManifestError
├── AppRuntimeUnsupportedError
├── AppGitError
│   ├── GitUnavailableError
│   ├── GitCredentialError
│   └── GitNonFastForwardError
├── AppHubHttpError
├── AppHubBusinessError
├── AppHubProtocolError
└── PublishInterruptedError
```

异常对象只保存脱敏上下文，不保存完整请求头、cookie 或 token。

## 13. 测试架构

### 13.1 单元测试

`tests/app/`：

- manifest 校验矩阵。
- Codex Node/static 工程阻断。
- Git 版本解析。
- remote/slug 一致性。
- NOOP 四象限。
- non-fast-forward 识别。
- 普通 push 无 force 参数断言。
- credential helper 参数顺序。
- token 不进日志/argv/异常断言。
- SSE 正常、心跳、hidden、乱序、断线、done。
- session 文件原子写和损坏恢复。
- 401/403/404/409/422/426/502 映射。

### 13.2 集成测试

- 临时裸 Git 仓库模拟 origin。
- respx 模拟 AppHub API。
- 真实 Git credential 文件隔离在临时 HOME。
- 同 SHA 重试和 resume。

### 13.3 端到端

依赖 AppHub 测试环境：

1. init/bind 完成的 Python 应用首发。
2. 双用户 non-fast-forward。
3. push 成功、release 请求断线、重试恢复。
4. SSE 断线 resume。
5. 本地密钥命中不产生 commit。
6. 服务端密钥命中不部署并吊销 pusher token。
7. Windows 完整流程。

## 14. 交付分期

### Phase 1：opscli D9 publish

- `app` 模块骨架。
- publish、resume。
- Git、SSE、session、HTTP client。
- 最小 git credential 支撑。
- Python runtime 相关面测试。

### Phase 2：AppHub Node/static runtime

- AppHub 契约变更。
- Coolify Node 构建/启动方案。
- Codex 标准站点 manifest 映射。
- 端到端部署。

### Phase 3：Codex Skill 一键编排

- 检测初始化状态。
- 明确提示并执行 init 或 publish。
- 读取结构化结果。
- 严格遵守普通 commit/push 授权边界。

## 15. 主要风险

1. 当前业务目标与 AppHub runtime 不兼容，若不拆分会形成“命令完成但站点不可部署”的假闭环。
2. 本地长期 token 为明文落盘，必须遵守 AppHub 已裁决的权限和吊销治理。
3. gitleaks 分发源尚未关闭，fail-closed 可能影响首次使用体验。
4. AppYaml 双份维护存在漂移风险，必须有契约测试。
5. AppHub 文档中 opscli 实现状态与当前 `open-opscli` 工作区事实不一致，编码必须以当前仓库实际文件为准重新落地，不能假设模块已存在。

