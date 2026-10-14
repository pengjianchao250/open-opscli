# AppHub 迁移验证合同

迁移改造可以因源项目而异，但改造结果只使用三项必须合同验收：

1. `migration_integrity`：源目录只读、源目标隔离、复制和适配状态完整，`opscli app migrate verify` 已通过；
2. `dual_runtime`：字段名为兼容既有清单保留，实际采用轻量运行兼容门禁；原本地冒烟和 AppHub 薄适配冒烟必需，核心业务一致性只在风险触发时必需；
3. `release_gate`：AppHub 发布资产、身份、入口、端口、健康检查、构建、安全和运行时资源合同通过。

```text
release_ready = migration_integrity && dual_runtime && release_gate
```

`release_gate` 以 AppHub 已实现的 Dockerfile 发布合同为准：根目录 `app.yaml` 通过严格字段校验，`Dockerfile` 有可执行的 `CMD` 或 `ENTRYPOINT`，运行时监听 8000 或读取 `PORT`，`/__apphub_healthz` 可直接返回 HTTP 200；声明 SQLite 时还必须存在合法的 `compose.apphub.yaml`。Nixpacks、FastAPI、`backend/app.py`、`frontend/package.json` 和固定的 `backend.app:app` 不是迁移发布门禁。

## 默认执行方式

迁移适配前先从源项目 `README.md`、包脚本和实际启动入口记录本地基线、运行版本和可复用依赖环境。完成目标副本薄适配并执行 `opscli app migrate verify` 后，默认只运行两个快速冒烟：

```bash
python scripts/validate_migration_contract.py "<target-project>" \
  --local-check-json '["<local-smoke-command>", "<arg>"]' \
  --apphub-check-json '["<apphub-smoke-command>", "<arg>"]'
```

- 本地冒烟只需证明原入口仍能启动或完成最小健康检查。
- AppHub 冒烟只需证明薄适配入口能启动、`/__apphub_healthz` 返回 200，并按改动范围抽查必要页面、资源或一个核心只读接口。
- 默认不执行完整 E2E，也不要求业务一致性命令。

## 风险触发的一致性检查

当薄适配出现任一情况时，必须增加定向一致性检查：

- 修改原业务源码、API 路由、响应结构或鉴权语义；
- 修改公共路径、SPA fallback、WebSocket 或前后端代理；
- 修改 SQLite、`/data`、后台任务、进程模型或持久化行为；
- 本地入口与 AppHub 入口使用不同业务执行链路。

```bash
python scripts/validate_migration_contract.py "<target-project>" \
  --local-check-json '["<local-smoke-command>", "<arg>"]' \
  --apphub-check-json '["<apphub-smoke-command>", "<arg>"]' \
  --parity-check-json '["<targeted-parity-command>", "<arg>"]' \
  --require-parity
```

未命中风险时，`business_parity_status=not_required`。命中风险却未提供命令时，状态为 `missing_required_command` 并阻断交付。

## 命令与耗时约束

- 命令必须是 JSON 参数数组并以 `shell=false` 执行，不得拼接 shell 字符串。
- 不得虚构项目不存在的 lint、测试或构建命令；需要组合检查时建立可审查的项目脚本。
- 同一次验证中完全相同的命令只执行一次，其他检查复用结果。
- 默认复用已有 `.venv`、`node_modules`、pnpm store 和构建缓存，不在验证阶段主动重装依赖。
- 锁文件和依赖声明未变化时不重复安装，生产构建同一轮最多执行一次。
- Python/Node 版本在迁移开始时确定，不在验证过程中反复切换环境。
- 扫描排除依赖、虚拟环境、构建产物和缓存目录。
- 默认单项超时 180 秒；只有项目证据表明启动确实更慢时才调整。

验证结果写入 `.opscli/migration/<migration-id>/validation-manifest.json`。任何合同失败都只修改目标副本，并重复“定向复验 → `migrate verify` → 标准合同验证”。

## 推送规则

- 迁移项目 push 必须要求清单中三项合同全部通过，且当前交付源码指纹与清单一致；验证后源码变化必须重新验证。
- 用户在任务开始时已授权 `push_on_success`，且最终文件范围没有超出授权时，`release_ready=true` 后直接执行 `opscli app push`。
- 未授权自动推送时只报告验证通过和待推送状态。
- push 成功只表示源码到达远端 `master`；没有平台状态和线上运行证据时不得声称已发布。
- 本合同只作用于 `origin_type=migration_copy`。普通新建项目不生成、不读取 `validation-manifest.json`，继续执行原有模板克隆、create、init 和 push 流程。
