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
2. 调用 AppHub create，并在请求中带上 `origin_type=migration_copy`、`migration_id`；
3. 调用 Git init，建立目标项目自己的 `.git` 和远端绑定。

迁移状态位于 `.opscli/migration/<migration-id>/`，并由 `.opscli/migration/current.json` 指向当前任务，至少包括 `migration.json`、`copy-manifest.json` 和 `startup-manifest.json`。迁移项目的 `create/init/push` 行为只能通过迁移标识选择专用分支，不能改变普通新建项目行为。

## 启动脚本

迁移时扫描前端和后端启动证据，生成 `scripts/start_app.py`，统一启动已识别的进程并在退出时回收子进程。

- 前后端均识别成功：`startup_status=ready`。
- 任一端无法可靠识别：仍允许迁移完成，但标记 `startup_status=startup_manual_required`，并把识别结果和人工补充位置写入 `startup-manifest.json`。
- 重新补充或变更启动方式后运行 `opscli app migrate scan-startup --target <target>`，不得手工伪造状态。

## 推送门禁

迁移项目允许沿用 `opscli app push`，但使用迁移专用校验：校验迁移标识、源/目标隔离、复制清单和启动清单；不要求源项目具备新建模板的 `app.yaml` 身份声明，不要求把迁移源码改造成模板结构。

`.env`、`.env.*`、`*.db`、`*.sqlite`、`*.sqlite3` 和 `data/` 默认不进入 Git 提交。用户如需提交这些文件，必须显式修改目标项目的 Git 规则并自行承担敏感信息和本地数据风险。

## 状态与旧状态转换

- 查看：`opscli app migrate status --target <target> --json`
- 校验：`opscli app migrate verify --target <target> --json`
- 重扫启动：`opscli app migrate scan-startup --target <target> --json`
- 一次性转换旧的模板重构状态：`opscli app migrate convert-legacy --target <target> --json`

发现旧迁移状态时，普通 status/verify 不得静默继续；`convert-legacy` 先把旧状态移入 `.opscli/migration-legacy/` 备份，再允许新源码复制迁移状态继续工作。该转换命令不修改业务源码。

## 验收边界

迁移完成只表示复制、标识、AppHub create、Git init 和启动扫描已完成，不等于业务重构、数据合同验证或生产发布完成。未知启动方式、未完成的线上配置和需要人工确认的发布步骤必须如实标记，不得伪造为通过。
