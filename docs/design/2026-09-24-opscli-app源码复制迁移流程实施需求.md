# opscli app 源码复制迁移流程实施需求

## 0. 文档状态

- **状态**：待用户确认。
- **编写日期**：2026-09-24。
- **实施约束**：确认前只沉淀和修订本文档，不修改业务代码、Skill、测试或已有迁移状态。
- **替代方向**：确认后，本需求替代当前“模板基础上的迁移重构”作为 `opscli app migrate` 主流程。

## 1. 需求结论

AppHub 项目的“迁移”统一定义为：

> 将旧项目完整复制到独立目标目录，在目标副本上完成 AppHub 身份绑定、Git 初始化、启动方式适配和后续推送；源项目始终只读，迁移工具不主动重写业务源码。

迁移不再表示模板内重构、逐页面重做、数据合同重建或强制目标项目满足统一模板结构。

## 2. 必须实现

1. 用户表达“迁移、搬迁、复制到新项目”等意图时，必须进入迁移流程。
2. 迁移流程不复制统一模板、不调用模板克隆流程。
3. 用户可以指定迁移后的目标项目根目录；未指定时按默认规则生成。
4. 源项目完整复制到目标副本，源项目保持只读。
5. 复制时排除 Git、依赖安装目录、构建产物和运行时临时信息。
6. `.env`、本地 `data`、SQLite 数据和其他本地运行配置按规则复制。
7. 目标项目写入可机器读取的迁移标识。
8. `create`、`init`、`push` 继续复用新建看板服务，但迁移项目采用独立轻量门禁。
9. 扫描原项目已有前后端启动方式，生成一个统一启动入口。
10. 用户确认前不修改代码。

## 3. 必须清除的旧迁移重构逻辑

以下内容不再属于迁移主流程，不通过兼容分支继续保留为默认路径：

- `audit -> ui_blueprint -> ui_skeleton -> data_integration -> behavior_verification -> release_verification` 阶段链；
- `coverage-matrix.json`、`ui-blueprint.json`、`data-contracts.json`；
- `verify-ui`、`verify-data`、`verify-release` 等完整重构门禁；
- 目标目录必须包含统一模板关键文件；
- 禁止复制旧项目源码；
- 在模板内重新实现前端、后端、数据层和鉴权；
- 以页面覆盖、真实数据合同或重构验收衡量迁移完成度。

需要重新定义的主要文件：

- `opscli/app/services/migration.py`；
- `opscli/app/commands/cli.py`；
- `opscli/skills/templates/ops-app-build-spec/SKILL.md`；
- `opscli/skills/templates/ops-app-build-spec/references/migration-standard.md`；
- `tests/app/test_migration.py`。

## 4. 修改边界

### 4.1 目标副本允许的最小修改

- 删除复制过程中的 `.git`；
- 创建新的 `.git`；
- 创建新的 `.opscli` 状态和 AppHub binding；
- 创建迁移标识、复制清单和启动清单；
- 创建统一启动脚本或外层启动包装器；
- 必要时调整 AppHub 身份字段、端口和平台启动配置；
- 补充 `.gitignore`，避免敏感本地文件被推送。

### 4.2 禁止自动重写

- 前端页面、组件、Store、路由和样式；
- 后端接口、服务、数据处理和鉴权逻辑；
- 数据库模型和业务数据结构；
- 原有配置语义、测试行为和目录结构；
- 原项目任何文件。

迁移工具不得主动重构业务源码；只有 AppHub 接入、Git、启动和平台运行所需的新增或最小适配可以写入目标副本。

## 5. 迁移流程

### 5.1 意图分流

“迁移项目、搬迁项目、保留原代码迁移、复制旧看板到新目录、基于现有项目创建新的 AppHub 项目”等表达必须进入迁移流程。

识别后不得自动进入 `clone-template`、普通 `app create` 新建模板项目或旧的完整迁移重构流程。交互式流程必须确认源目录、目标目录和应用名称；用户明确不指定目标目录时，允许采用默认规则继续执行。

### 5.2 路径校验

- 源目录必须存在且为真实目录；
- 源目录和目标目录解析为绝对路径；
- 两者不能相同，也不能互相包含；
- 目标不能是文件；
- 不跟随越界符号链接或 Windows junction；
- 源目录只读，状态只写入目标目录。

### 5.3 目标目录解析

用户指定目标目录时：不存在则创建并使用，存在且为空则直接使用；存在且非空时提示但不阻塞，在其下创建：

```text
app-hub-source-YYYYMMDD-HHmmss
```

用户未指定目标目录时，在 Codex 当前对话目录下创建同名时间戳目录。发生冲突时追加短随机后缀，例如 `app-hub-source-20260924-164500-a7f2`。结果必须返回最终目标项目根目录，而不是只返回请求的父目录。

### 5.4 源码复制

复制必须先写入临时目录，完成校验后再切换为最终目录：创建临时目标目录、按策略复制、记录包含/排除/敏感文件、计算指纹、校验、创建标识和启动清单、原子重命名；失败时清理临时目录，不留下半成品。

## 6. 文件复制策略

### 6.1 必须复制

前后端源码、普通配置、文档、测试、脚本、依赖声明、lock 文件、Docker/部署配置、`.env`、`.env.local`、`data/`、本地 SQLite、种子数据和本地资源。

依赖声明和 lock 文件必须保留，只排除已经安装的依赖目录。

### 6.2 默认不复制

```text
.git/       .opscli/       node_modules/       .venv/       venv/
__pycache__/ .pytest_cache/ .mypy_cache/       .ruff_cache/
.coverage   coverage/      dist/                build/
.next/      .nuxt/         .cache/              tmp/
temp/       logs/
```

`.opscli/` 必须排除，防止旧 `app_id`、Git remote、binding 和旧迁移状态进入新项目。

### 6.3 复制与推送分离

`.env` 和本地数据可以复制到目标目录，但默认不得进入远端 Git。目标 `.gitignore` 必须屏蔽 `.env`、本地数据库、日志和运行时数据；复制清单只记录敏感文件路径、大小和哈希，不记录内容。种子数据如需推送必须使用单独的显式选项，不提供笼统的 `--force` 绕过检查。

## 7. 迁移标识与状态

目标项目至少保存：

```text
.opscli/project.json
.opscli/migration/current.json
.opscli/migration/<migration-id>/migration.json
.opscli/migration/<migration-id>/copy-manifest.json
.opscli/migration/<migration-id>/startup-manifest.json
```

项目标识示例：

```json
{
  "schema_version": 1,
  "project_type": "apphub",
  "origin_type": "migration_copy",
  "migration_id": "migration-20260924-164500-a7f2",
  "source_root": "E:\\source-project",
  "target_root": "E:\\app-hub-source-20260924-164500",
  "source_readonly": true,
  "template_cloned": false,
  "business_source_rewritten": false
}
```

建议状态：`intent_detected`、`source_validated`、`target_resolved`、`source_copied`、`copy_verified`、`startup_ready`、`registered`、`initialized`、`push_ready`、`pushed`、`failed`。

## 8. 启动方式扫描

扫描 `README.md`、`package.json`、lock 文件、`pyproject.toml`、`requirements.txt`、现有 `scripts/`、Docker/Compose/Procfile/Nixpacks、实际后端入口、前端 `dev/start/preview/build` 命令、端口和健康检查配置，但不重构原有启动实现。

原则：已有统一脚本时优先复用；前后端分开启动时只增加外层包装器；多候选命令必须人工确认；脚本支持端口环境变量、子进程清理、退出信号和健康检查；线上生产模式不得默认使用前端开发服务器。

推荐新增：

```text
scripts/start_app.py
.opscli/migration/<migration-id>/startup-manifest.json
```

`start_app.py` 只调用原项目已有命令，建议支持 `--mode local` 和 `--mode production`。线上方式无法确认时标记 `startup_manual_required`，不能宣称线上可直接启动。

## 9. AppHub create、Git init 和 push

迁移项目继续复用普通新建项目服务：`create` 复用 `AppManager.create_app`，`init` 复用 `AppManager.init_git`，`push` 复用 `AppManager.push`。这些操作只针对目标目录，不调用模板克隆服务，不要求目标副本符合模板结构。

创建和初始化要求：

- 使用新的 `app_id`、Git 仓库和 binding；
- 记录 `origin_type=migration_copy` 和 `migration_id`；
- 应用标题和 slug 分开处理；
- `init` 不拉取模板、不覆盖业务源码、不合并无关远端历史；
- 重试保持目录级和服务端幂等。

迁移项目使用轻量“迁移交付门禁”，推送前检查：有效迁移标识、源/目标独立、独立 Git、正确 remote 和 binding、复制清单、启动清单、启动命令歧义、敏感文件范围、完整推送范围展示和用户授权。

不得检查或要求统一模板固定目录、UI 覆盖矩阵、数据合同完成或迁移重构阶段为 `complete`。

## 10. 建议命令

```text
app migrate start
app migrate status
app migrate scan-startup
app migrate verify
```

- `start`：路径解析、复制、校验、迁移标识、启动扫描和包装器生成。
- `status`：输出目录、迁移 ID、复制、启动、AppHub、Git 和推送状态。
- `scan-startup`：重新扫描目标副本，不修改源目录和业务源码。
- `verify`：检查复制完整性、源目录未修改、目标独立、启动入口、身份、remote 和敏感文件。

旧的 `audit`、`plan`、`verify-ui`、`verify-data`、`verify-release`、`export` 不再作为主流程命令。

## 11. 分阶段实施计划

1. **规范与命令契约**：重写 Skill 迁移定义，清理旧规则，固定新命令、状态和文件格式。
2. **复制服务**：实现路径解析、排除策略、临时目录、复制校验、失败清理和复制清单。
3. **身份与服务编排**：增加 `origin_type=migration_copy`，复用 create/init，确保不调用模板服务，支持幂等恢复。
4. **启动入口**：扫描命令，生成启动清单和外层包装器，支持本地/生产模式和人工确认。
5. **推送门禁与清理**：增加轻量门禁，清除旧重构命令、状态模型、模板门禁和对应测试，保持普通新建流程不变。

## 12. 测试要求

至少覆盖：迁移意图分流；指定空目录、非空目录、未指定目录和冲突；相同/嵌套路径拒绝；源目录前后文件列表和哈希不变；排除 `.git`、`.opscli`、依赖目录、缓存和构建产物；复制 `.env`、`data/` 和本地数据库；链接不越界；失败清理；标识、复制清单、启动清单；create/init 不调用模板服务；非模板结构可推送；敏感文件不默认推送；启动包装器清理子进程；歧义命令人工确认；中断后恢复。

## 13. 验收标准

- 迁移意图进入源码复制流程，全流程不调用模板克隆；
- 源目录始终只读，目标目录解析符合指定、非空回退和默认规则；
- 目标副本不含 `.git`、`.opscli`、依赖安装目录和运行时产物；
- `.env` 和本地数据按规则保留；
- 目标项目包含迁移标识；
- 业务源码没有被自动重构；
- create/init/push 复用现有服务，push 不要求模板目录完整；
- push 前识别敏感文件和运行时文件；
- 目标项目具备统一启动入口，或明确标记为需人工确认；
- 旧完整重构迁移命令和门禁不再被主流程调用；
- 相关单元测试和 Skill 契约测试通过。

## 14. 已确认决策

1. `migrate start` 只完成本地复制，还是复制成功后自动执行 AppHub `create` 和 Git `init`。
2. AppHub `create` 是否新增 `origin_type`、`migration_id`，还是仅保存在本地标识中。
3. `.env` 是否始终复制；本文档默认复制但默认不推送。
4. `data/` 是否全部复制，还是区分种子数据、运行时数据库和缓存数据。
5. 生产启动方式无法识别时，是否允许完成迁移但标记为 `startup_manual_required`。
6. 发现旧迁移状态时，是直接拒绝，还是提供一次性清理/转换命令。

## 15. 确认门槛

用户确认本需求后，才允许进入代码实施。实施前必须先固化第 14 节决策，再更新迁移服务、CLI、AppManager 推送门禁、相关 Skill 和测试。

确认前不得删除旧迁移实现，不得修改代码和测试。
