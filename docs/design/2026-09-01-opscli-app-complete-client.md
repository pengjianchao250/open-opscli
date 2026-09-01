# opscli app 完整客户端需求与实施方案

> 日期：2026-09-01  
> 目标仓库：`E:\wwwroot\localProjects\open-opscli`  
> 权威服务端：`E:\wwwroot\localProjects\codex-custom-sites-all\ops-apphub`

## 1. 背景与结论

`opscli app` 是 AppHub 面向业务开发者与 AI 工具的完整客户端，不是单一发布器。AppHub 的 API、`app.yaml` 契约、启动命令和业务规范是客户端实现的权威依据。

当前客户端仅具备 `publish` 与 `git status/bind/revoke` 的基础实现，缺少项目初始化、本地同构运行、迁移、独立校验、版本运维、应用配置管理和运行时 SDK。尤其 AppHub 容器启动命令固定执行 `python -m opscli.app.migrate`，客户端缺少该模块会直接影响应用启动。

## 2. 强制原则

1. `apphub/schemas/appyaml.py` 是 `app.yaml` 的单一事实源；客户端只消费其导出的 JSON Schema，不维护第二份手写字段模型。
2. `opscli app validate` 与 `opscli app publish` 共用同一个校验引擎。
3. `publish` 必须先完成完整校验；阻断问题存在时不 commit、不 push、不调用 release API。
4. 客户端只执行普通 Git 操作，禁止 force push、自动 reset 和静默覆盖用户分支。
5. secret 与 Git token 不得出现在日志、稳定输出、本地普通配置文件或异常详情中。
6. 本地 `run` 与线上启动保持同构：相同 base path、平台环境变量和 migrations 入口。
7. 所有命令统一返回 `success/command/data/error`，并支持稳定 JSON 输出。

## 3. 必做功能范围

### 3.1 开发

- `opscli app init <slug>`：三 runtime 模板、AppHub 登记、Git 初始化/绑定、重入处理。
- `opscli app run`：本地同构启动、平台环境注入、启动前迁移。
- `python -m opscli.app.migrate`：SQLite migrations 顺序、幂等执行。

### 3.2 规范

- `opscli app validate`：AppYaml、文件、SQLite、SDK、依赖与 gitleaks 规则。
- `opscli app publish`：强制复用 validate，随后执行普通 commit/push/release/SSE。

### 3.3 源码协作

- `opscli app pull`
- `opscli app git status`
- `opscli app git bind`
- `opscli app git revoke`

### 3.4 发布运维

- `opscli app publish`
- `opscli app versions`
- `opscli app rollback`
- `opscli app logs`

### 3.5 应用管理

- `opscli app env get/set/unset`
- `opscli app secret list/set/unset`
- `opscli app members list/add/remove`
- `opscli app db info/backups/restore`

### 3.6 运行时 SDK

- `current_user()`
- `ops_client()`，含 `query/query_df/metadata`
- `get_engine()`
- `base_path()`

## 4. 不进入普通 CLI 的能力

- 超管强制转移 owner。
- SQLite 任意 SQL 与管理台表级浏览。
- 应用启停、归档、平台部署诊断等管理台运维能力。
- MCP 版 AppHub 工具。
- `diff/archive` 作为后续增强，不阻塞本次核心闭环。

## 5. 模块设计

```text
opscli/app/
├── commands/cli.py
├── contracts/appyaml.schema.json
├── domain/{constants,exceptions,models}.py
├── services/
│   ├── appignore.py
│   ├── manager.py
│   ├── migrate.py
│   ├── project.py
│   ├── publish.py
│   ├── runner.py
│   ├── templates.py
│   └── validator.py
├── sdk/{context,engine,ops_client}.py
├── transport/client.py
└── migrate.py
```

## 6. 发布状态机

```text
load project
→ validate AppHub schema
→ validate local rules
→ gitleaks
→ requirements 检查/补齐
→ Git preflight/fetch
→ auto commit（有改动）
→ ordinary push
→ POST release
→ SSE/resume
→ healthy/failed/cancelled
```

## 7. 验收标准

1. 三 runtime 均可生成标准项目，并能生成正确本地启动命令。
2. `migrate` 在无 SQLite、无 migrations、重复执行三种情况下均安全。
3. validate 每条阻断规则至少有一对正反测试。
4. publish 校验失败时 Git 与 AppHub API 均无副作用。
5. versions/rollback/logs/env/secret/members/db 与 AppHub 契约一致。
6. secret/token 不进入输出和错误详情。
7. SDK 四函数在本地模式可用，viewer 模式可消费网关注入上下文。
8. AppYaml 导出 Schema 与客户端打包副本可自动对比。
9. app 专项测试、CLI 注册测试、compileall 与 diff 检查通过。

## 8. 实施顺序

1. 契约副本、领域模型、迁移运行器。
2. init/run/templates 与 Git 初始化。
3. validate 引擎及 publish 强制接线。
4. versions/rollback/logs/env/secret/members/db/pull。
5. SDK 四函数与 requirements 注入。
6. 测试、文档和构建资源收口。

## 9. 本次落地结果

截至 2026-09-01，本方案中的核心闭环已在 `open-opscli` 落地：

- 开发链路：`init`、`run`、`python -m opscli.app.migrate`。
- 规范链路：独立 `validate`，以及 `publish` 发布前强制复用同一校验引擎。
- 源码协作：`pull`、`git status/bind/revoke`。
- 发布运维：`publish`、`versions`、`rollback`、`logs`。
- 应用管理：`env`、`secret`、`members`、`db` 命令组。
- 运行时 SDK：`current_user()`、`ops_client()`、`get_engine()`、`base_path()`。
- 契约治理：客户端消费 AppHub 导出的 `app.yaml` JSON Schema，并提供同步检查脚本。

本次明确不包含：`diff/archive`、超管 owner 转移、任意 SQLite SQL/表浏览、应用启停/归档、AppHub MCP 工具。这些属于后续增强或管理台能力，不影响普通开发者从创建、校验、推送、发布到运维的主闭环。

## 10. 验证记录

- `python scripts/sync_apphub_appyaml_schema.py --check`：通过。
- `python -m compileall -q opscli/app tests/app scripts/sync_apphub_appyaml_schema.py`：通过。
- `python -m pytest tests/app tests/test_setup.py -q`：35 项通过。
- `python -m opscli.app.migrate`：无数据库或无 migrations 时安全跳过。
- 锁文件同步后，SQLAlchemy `get_engine()` 已通过真实 SQLite `select 1` 烟测。
- 纯 Python wheel 构建、隔离安装和导入通过；wheel 已确认包含 `opscli/app/migrate.py` 与 `opscli/app/contracts/appyaml.schema.json`。
- 本机缺少 Microsoft Visual C++ 14.0+，因此生产 Cython wheel 未在本机完成编译；失败发生在编译器环境检查，不是本次 app 模块测试或打包资源错误。
- pytest 仅出现 `.pytest_cache` 目录无写权限警告，不影响测试结果。

## 11. 上线前联调项

以下项目依赖真实基础设施或运行环境，未在本地自动化测试中执行：

- AppHub 注册、版本列表、回滚、日志、配置、成员和数据库恢复接口联调。
- Gitea 凭据签发、普通 push、pull 和分支保护联调。
- Coolify 部署、SSE 断线续传和运行日志跟随联调。
- gitleaks 二进制下载、哈希校验与真实仓库扫描联调。
- Streamlit、FastAPI、Gradio 三种 runtime 的浏览器级启动与发布烟测。
