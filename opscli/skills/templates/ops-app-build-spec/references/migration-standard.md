# AppHub 源码复制迁移规范

迁移开始前先通过 [Git 本地环境规范](git-environment-standard.md) 门禁；Git 未就绪时不得创建目标目录、AppHub 应用或 binding。

本规范只适用于 `opscli app migrate`。它与新建项目流程隔离：新建项目继续执行 `app create`、模板克隆和 `app init` 的原有流程；不得因为迁移规则改变新建项目的目录、模板、身份校验或推送门禁。

## 核心边界

1. 迁移是“完整复制源码 + 最小运行适配”，不是模板迁移重构，不拉取模板，不重写业务前后端，不把旧项目按模板重新实现。
2. 必须由用户明确指定迁移源目录；源目录只读，迁移过程不得在源目录执行 `create`、`init`、写入、删除、安装依赖或启动服务。
3. 迁移目标必须与源目录不同，且不能是源目录或其父子目录。目标目录由用户明确指定；未指定时，在当前 Codex 对话目录创建 `app-hub-source-时间戳`。
4. 用户指定的目标目录为空时直接使用；目标目录非空时保留原内容，并在其中创建新的 `app-hub-source-时间戳` 子目录，同时在结果中提示 `target_reason=user_non_empty_fallback`。
5. 复制使用临时目录，复制完成后校验源指纹，再原子改名为目标目录；失败不得留下半成品目标项目。

## 复制范围

- 必须复制其余源码、配置、文档、测试和资源文件。
- 必须复制 `.env`、`.env.*` 和整个 `data/` 目录；这些内容默认加入目标项目的本地忽略规则，不默认推送。
- 不复制 `.git`、`.opscli`、虚拟环境、依赖目录、缓存、构建产物、日志、临时目录和运行时文件；迁移服务会重新生成目标项目的 `.opscli` 状态。
- 源目录中的软链接不跟随复制，避免越界复制；迁移结果记录在 `copy-manifest.json`。
- 源项目始终保持不变，迁移结果必须写入独立目标目录。

## 自动登记与标识

`opscli app migrate start` 在复制成功后自动：

1. 写入 `.opscli/project.json`，其中至少包含 `origin_type=migration_copy`、`migration_id`、源目录、目标目录、`template_cloned=false` 和 `business_source_rewritten=false`；
2. 识别启动证据并建立最小适配层；只有证据明确时才调用普通 AppHub create，创建请求不发送 `origin_type`、`migration_id`，迁移创建也不猜测或强制声明 SQLite；
3. 使用 AppHub 返回的真实 `app_id` 生成或同步 `app.yaml`；适配状态为 `ready` 后才调用 Git init，建立目标项目自己的 `.git` 和远端绑定。

`origin_type` 和 `migration_id` 是本地编排元数据，只保存在 `.opscli/project.json` 与 `.opscli/migration/<migration-id>/migration.json`，不得加入 AppHub 服务端合同。迁移状态由 `.opscli/migration/current.json` 指向当前任务，至少包括 `migration.json`、`copy-manifest.json`、`startup-manifest.json` 和 `adaptation-manifest.json`。

复制清单只描述来自源项目的文件；适配清单单独记录 `.gitignore`、`scripts/start_app.py`、`app.yaml` 等受管、生成或修改文件。适配层的确定性修改不得导致 `copy_verified=false`，但其他复制文件的缺失或漂移必须阻断交付。迁移实现不能改变普通新建项目行为。

## 启动脚本

迁移时扫描前端和后端启动证据，生成 `scripts/start_app.py`，统一启动已识别的进程并在退出时回收子进程。

- 前后端均识别成功：`startup_status=ready`。
- 任一必要入口无法可靠识别：保留目标副本并标记 `startup_status=startup_manual_required`、`adaptation_status=adaptation_manual_required`、`delivery_ready=false`，停止 AppHub create、Git init 和 push。
- 重新补充或变更启动方式后运行 `opscli app migrate scan-startup --target <target>`，不得手工伪造状态。

## 最小适配层

通用迁移只自动处理能由仓库证据确定的内容：本地忽略规则、启动包装器和 AppHub 应用身份。推送前至少确认 `backend/app.py`、`frontend/package.json`、`Dockerfile` 和 `nixpacks.toml` 存在；缺少时转人工适配。不得猜测业务运行时、数据库、依赖或生产构建方式，不得生成通用 Dockerfile 或重写业务源码来伪造兼容。

当 `frontend/package.json` 声明 pnpm 且 Dockerfile 启用 Corepack 时，迁移门禁还要确认 Corepack 能从该 manifest 所在目录解析 `packageManager`。若 Dockerfile 只把 manifest 复制到 `frontend/`，却从父目录通过 `pnpm --dir frontend` 启动，且没有显式使用相同 pnpm 版本，则转人工适配并阻止推送；不得使用 `pmOnFail=ignore` 绕过版本合同。该检查只属于源码复制迁移，不改变普通新建项目行为。

迁移项目若在运行时代码中引用 `public/**/data` 作为空运行卷的只读快照，迁移门禁必须确认 Dockerfile 最终运行阶段会复制 `public`，且 `.gitignore`、`.dockerignore` 不会排除该快照。只在构建阶段复制、最终镜像遗漏，或使用未锚定的 `data/` 忽略嵌套公开数据目录时，标记 `runtime_asset_contract=false` 并阻止推送。自动生成的本地忽略规则只排除根目录 `/data/`，保留嵌套公开快照；该检查只作用于源码复制迁移项目。

`adaptation-manifest.json` 必须包含 `status`、检查项、受管文件、生成或修改文件和本地专用状态文件。只有启动证据明确、`app.yaml` 使用真实 `app_id`、本地迁移状态完整时，`adaptation_status=ready`。未完成时标记 `adaptation_manual_required`，人工补齐后使用 `opscli app migrate resume` 继续。

## 推送门禁

迁移项目沿用 `opscli app push`。推送前先校验迁移标识、源/目标隔离、复制/启动/适配清单、`adaptation_status=ready` 和 `delivery_ready=true`，随后继续执行普通项目相同的 `app.yaml` 身份与 AppHub 生产门禁。迁移门禁只验证迁移过程和适配状态，不能放宽服务端构建、发布或安全合同。

`.env`、`.env.*`、`*.db`、`*.sqlite`、`*.sqlite3` 和根目录 `/data/` 默认不进入 Git 提交。运行时代码明确引用的 `public/**/data` 只读快照必须进入源码和最终运行镜像。用户如需提交其他运行时文件，必须显式修改目标项目的 Git 规则并自行承担敏感信息和本地数据风险。

## 状态与旧状态转换

- 查看：`opscli app migrate status --target <target> --json`
- 校验：`opscli app migrate verify --target <target> --json`
- 重扫启动：`opscli app migrate scan-startup --target <target> --json`
- 恢复：`opscli app migrate resume --target <target> --json`
- 一次性转换旧的模板重构状态：`opscli app migrate convert-legacy --target <target> --json`

每个成功阶段都写入 `migration.json`。失败保留最后成功阶段和结构化错误；`resume` 不重新复制源目录，已有 `app_id` 时不重复创建应用，已有 Git 仓库时不重复初始化。

发现旧迁移状态时，普通 status/verify 不得静默继续；`convert-legacy` 先把旧状态移入 `.opscli/migration-legacy/` 备份，再允许新源码复制迁移状态继续工作。该转换命令不修改业务源码。

## 验收边界

迁移命令完成只表示复制、标识、最小适配、AppHub create、Git init 和本地门禁已完成，不等于业务重构、数据合同验证或生产发布完成。只有 `delivery_ready=true` 才能进入 push；未知启动方式、未完成的线上配置和需要人工确认的发布步骤必须如实标记，不得伪造为通过。
