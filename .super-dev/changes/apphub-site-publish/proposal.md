# AppHub 站点发布命令 Proposal

> 日期：2026-08-31

## 目标

- 在 `open-opscli` 新增 `opscli app publish`，按 AppHub D9 架构完成本地校验、普通 Git commit/push、release API 调用与 SSE 状态展示。
- 支持 `--resume` 断线续订和稳定 JSON 输出，供 Codex Skill 调用。
- 提供 publish 必需的 `opscli app git status/bind/revoke` 凭据自助能力。
- 在 AppHub 尚未支持 Node/static runtime 时，于任何 Git 副作用前明确阻断 Codex React/TypeScript 站点。

## 改动

- 新增 `opscli/app/` 四层模块并注册顶级 `app` 命令组。
- 新增 AppYaml 本地同构模型、项目识别、Git 前置检查、NOOP 判定、普通 commit/push 编排。
- 新增 AppHub CLI client，使用 `X-Session-Id` 与 `X-Opscli-Version`，禁止 cookie。
- 新增 SSE 解析、release 句柄原子持久化和 `--resume`。
- 新增受控 Git credential 文件、bind/status/revoke 与 token 脱敏。
- 新增 gitleaks 本地门禁；二进制不可用时 fail-closed。
- 新增 `tests/app/` 相关面测试并更新依赖与变更记录。

## 约束

- 不实现源码包上传、服务端 bot 代提交或 Git Writer。
- 不执行 force push、自动 rebase、reset 或清理用户文件。
- opscli 不持有 Gitea admin token 或 token-issuer 凭据。
- 不在本次改动中扩展 AppHub Node/static runtime。
- API、错误码、SSE 与句柄字段遵循 AppHub 冻结契约。

## 验收

- dirty 工作区可完成普通 commit、push、release 并返回健康版本和 URL。
- NOOP 退出码为 0；push 成功但 release 失败可重试远端 HEAD。
- non-fast-forward 返回 `GIT-003`，不修改历史且不提供 force 旁路。
- SSE 断线后 `--resume` 不漏帧、不重帧、不创建新 release。
- token 不进入 stdout、stderr、日志、异常、argv 或 publish session。
- Node/static 工程在 commit/push 前被明确阻断。

