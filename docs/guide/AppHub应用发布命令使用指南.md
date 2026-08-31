# AppHub 应用发布命令使用指南

## 适用范围

`opscli app` 按 AppHub D9 Git 直连架构发布应用：本地校验与 gitleaks 扫描后，创建普通 Git commit、执行非强制 push，再调用 release API 并通过 SSE 等待部署终态。

当前 AppHub 仅支持 `streamlit`、`fastapi`、`gradio`。检测到 `package.json`、`.openai/hosting.json`、`site.config.json` 或 `runtime: static` 时，命令会在 commit/push 前阻断。Codex Node/React/Vite 站点需要先完成 AppHub Node/static runtime 扩展。

## 环境要求

- Git 2.30 或更高版本。
- 已执行 `opscli auth login`。
- 应用根目录存在合法 `app.yaml`，且位于 Git 仓库根目录的 `main` 分支。
- `origin` 与 AppHub `git-config` 返回的 `apps/{slug}` 仓库一致。
- 本机安装可用的 gitleaks；缺失、执行异常或报告损坏都会 fail-closed。

## 绑定 Git 凭据

```bash
opscli app git bind .
```

已有有效凭据时，服务端会拒绝重复签发。需要换新凭据时显式执行：

```bash
opscli app git bind . --rotate
```

命令将一次性 token 通过 Git credential stdin 协议写入 `{CONFIG_DIR}/app/git-credentials`，并用 `git ls-remote` 探活。token 不进入命令参数或输出。

## 检查状态

```bash
opscli app git status .
opscli app git status . --json
```

输出包括服务端绑定状态、本地受控凭据是否存在、仓库探活是否通过和 `token_hint`，不返回 token 明文。

## 发布应用

```bash
opscli app publish . -m "发布首页更新"
```

结构化输出：

```bash
opscli app publish . -m "发布首页更新" --json
```

发布顺序固定为：

1. 读取并严格校验 `app.yaml`。
2. 检查 Git 版本、仓库根、`main` 和 `origin`。
3. 检查受控 Git 凭据并 fetch `origin/main`。
4. 用 gitleaks 扫描工作区和 `origin/main..HEAD`。
5. 工作区 dirty 时执行 `git add -A` 和普通 commit。
6. 执行非强制 `git push origin HEAD:main`。
7. 调用 `POST /api/apps/{slug}/releases`。
8. 消费 SSE 到 `healthy`、`failed` 或 `cancelled`。

工作区干净且 `origin/main` 与服务端最近健康发布的完整 commit SHA 相同时，命令返回 NOOP，退出码为 0。

## 断线续订

发布流中断后，本地句柄保存在 `{CONFIG_DIR}/apps/{slug}/publish-session.json`。网络恢复后执行：

```bash
opscli app publish . --resume
```

续订不会创建新 commit、push 或 release，而是从句柄中的 `last_seq` 继续读取同一次发布。终态后句柄自动删除。

## 吊销凭据

```bash
opscli app git revoke
```

该命令吊销当前用户全部 AppHub Git token，并删除本机受控凭据文件。吊销后再次发布前需要重新 bind。

## 常见错误

| 错误码 | 含义 | 处理方式 |
|---|---|---|
| `APP-RUNTIME-UNSUPPORTED` | 当前项目是 Node/static 或未支持 runtime | 先扩展 AppHub runtime，不要伪造 manifest |
| `GIT-001` | Git 缺失、版本过低、分支或 remote 错误 | 安装 Git 2.30+，修正仓库状态 |
| `GIT-002` | 本地凭据缺失或失效 | 执行 `opscli app git bind`；必要时带 `--rotate` |
| `GIT-003` | 本地与远端分叉或 push 竞态 | 人工 pull/rebase 并解决冲突，命令不会自动 reset/rebase |
| `AUTH-003` | gitleaks 检测到疑似密钥 | 先吊销源系统凭据，再清理代码和必要的本地 Git 历史 |
| `ERR_UPSTREAM` | gitleaks 或上游服务无法完成安全检查 | 修复环境或网络后重试，本轮不会 commit/push |
| `APP-PUBLISH-INTERRUPTED` | SSE 在终态前中断 | 执行 `opscli app publish --resume` |

