# opscli app push 成功提示统一需求

## 1. 背景

`opscli app push` 完成 Git 源码推送后，CLI 当前只提示“源码已推送到远端仓库”。Codex 在面向运营用户交付时可能继续自行概括后续动作，导致不同会话的提示不一致，也没有直接告诉用户应到运营系统查看发布状态或配置站点权限。

AppHub 已在源码到达应用仓库后接手自动部署和发布流程，因此需要统一 CLI 与 Codex 的成功提示，同时继续保持 `opscli app` 只负责源码交付、不查询发布状态、不把异步流程误报为已完成的职责边界。

## 2. 目标

1. 实际发生远端推送时，CLI 普通输出和 `--json` 返回统一成功提示。
2. 使用 `ops-app-build-spec` 执行源码交付时，Codex 最终回复原样使用同一提示。
3. 明确自动部署和发布是运营系统接手后的异步流程，不表示当前已经部署或发布成功。
4. 源码没有变化、远端已是最新版本时，不误报“推送成功”。

## 3. 统一提示

当 `opscli app push` 返回 `pushed=true` 时，统一使用以下完整文案：

```text
推送成功；运营系统将自动部署并发布当前站点，您可以前往运营系统查看发布状态、或进行站点权限设置。
```

CLI 文本输出直接显示该文案；`--json` 将该文案放在 `data.message`；Codex 最终回复原样使用该文案，不增加“部署成功”“发布成功”等状态判断。

## 4. 无变化分支

当 `opscli app push` 返回 `pushed=false` 时，表示本地 `HEAD` 与远端目标分支一致，没有执行新的 Git push。该分支继续返回：

```text
远端 master 已是最新源码，无需重复推送。
```

该分支不得使用统一成功提示，避免把未发生的推送报告为成功。

## 5. 职责边界

- 不新增或调用 AppHub release API。
- 不查询部署、构建、版本、健康检查或发布事件。
- 不等待运营系统完成部署或发布。
- 不改变 Git commit、fast-forward 校验、目标分支、凭据恢复或 push 行为。
- “将自动部署并发布”只描述源码推送完成后的平台流程，不是线上状态证据。

## 6. 改动范围

- `opscli/app/services/manager.py`：替换 `pushed=true` 的成功文案，保留 `pushed=false` 分支。
- `tests/app/test_manager.py`：覆盖真实推送和无变化两种业务结果。
- `tests/app/test_cli.py`：覆盖普通输出和 `--json` 的统一文案。
- `opscli/skills/templates/ops-app-build-spec/`：固定 Codex 最终回复和异步状态边界，升级 Skill 版本。
- 使用指南与源码交付设计文档：同步用户可见行为和职责说明。

## 7. 验收标准

1. `pushed=true` 时，业务层 `message` 与统一提示逐字一致。
2. 普通 CLI 输出包含统一提示。
3. `--json` 的 `data.message` 与统一提示逐字一致。
4. `pushed=false` 时仍返回“远端 master 已是最新源码，无需重复推送。”
5. Skill 明确要求 Codex 原样回复，并禁止把异步流程表述为当前已部署或已发布。
6. `opscli app` 不新增任何发布状态查询或 release 调用。
7. App 模块定向测试、Skill 契约测试和 Skill 快速校验通过。
