---
name: ops-app-build-spec
description: AppHub 模板业务项目的开发规范。创建、开发、排错、评审、迁移或推送源码时使用，约束前端维护、项目边界和源码交付；按任务读取相关后端与数据规范。
---

# OPS 应用模板开发

统一模板仓库：`http://10.1.13.143:3000/aukeys-admin/template`，分支：`master`。模板提供应用代码和发布资产，Skill 维护跨项目开发规则；不另建脚手架。

## 规范归属与读取

- 具体应用以后端实现为事实源：目标项目的 `backend/CLAUDE.md`、`docs/apphub-contract.md`、生成的 OpenAPI 和实际路由共同定义前后端合同。前端不得另行定义协议。
- 目录、依赖、命令和辅助函数以目标项目实际代码为准。发现 Skill、项目文档与代码冲突时列出证据和影响，不静默覆盖配置或用兼容分支掩盖漂移。
- 项目可补充业务约定；通用规则只在 Skill 维护，平台运行合同只在项目合同维护，避免多份文档重复。

| 本轮任务                                   | 读取                                                                                     |
| ------------------------------------------ | ---------------------------------------------------------------------------------------- |
| 前端页面、组件、样式或状态                 | [前端规范](references/frontend-standard.md)                                              |
| 修改前端请求、错误处理或前后端共享类型     | [前端规范](references/frontend-standard.md)、[后端红线](references/backend-redlines.md)  |
| 修改 FastAPI API、服务、任务或配置         | [后端红线](references/backend-redlines.md)                                               |
| SQLite 模型、事务、迁移或备份              | [SQLite 规范](references/sqlite-standard.md)                                             |
| 后端调用 opscli SDK 或 REST                | [opscli 接入规范](references/opscli-integration-standard.md)                             |
| 页面需要真实业务数据                       | [数据访问规范](references/data-access-standard.md)，按其要求使用 `$ops-app-data-builder` |
| 项目迁移或补齐后端规范                     | [迁移规范](references/migration-standard.md)                                             |
| 创建应用、绑定仓库、提交源码或检查交付条件 | [源码交付规范](references/deployment-standard.md)                                        |

首次接手或相关文件变化时，读取项目 `AGENTS.md`、`README.md` 和 `docs/apphub-contract.md`；进入子目录时读取适用的项目规则。后端改动与接口变化再核对 `backend/CLAUDE.md`、受影响路由、Pydantic Schema 和 OpenAPI；纯样式改动不额外读取后端全文。普通开发不读取 `assets/backend/` 中的全文规范。

## 新项目

1. 确认应用展示名称，并确认目标目录不存在或为空。
2. 使用当前 Skill 的安全脚本；`<skill-directory>` 为当前 Skill 绝对路径，`<project-directory>` 为目标项目目录：

   ```bash
   python "<skill-directory>/scripts/clone_template.py" "<project-directory>"
   ```

   脚本直接 clone 到目标目录，成功后立即删除项目根目录 `.git` 并验证其不存在；保留 `.gitignore` 和原有项目说明，不使用临时目录。任一步失败都停止，禁止手动跳过清理继续开发。

3. 模板准备成功后立即创建 AppHub 应用并写入本地 binding：

   ```bash
   opscli app create "<app-name>" --path "<project-directory>" --json
   ```

4. `create` 成功后立即初始化全新 Git 仓库并绑定业务仓库：

   ```bash
   opscli app init "<project-directory>" --json
   ```

5. 核对独立 Git 根、`master` 分支和 `origin`，确认 `origin` 不指向统一模板仓库；空远端首次初始化可以尚无 HEAD。确认 `.opscli/app.json.slug == app.yaml.name`，并按部署规范检查 binding。
6. 开发前读取目标项目的规则与本轮参考文件，再实现业务需求。

clone 并脱离模板 Git 元数据、`create` 和 `init` 是开始开发前连续执行的必需步骤。`create/init` 不负责获取模板。任何一步失败都停止后续开发，业务代码不得推回模板仓库。不得运行项目生成器、手写替代脚手架，或从 Skill 复制应用代码与发布资产。

## 已有项目与项目约定

业务项目绑定自己的远端后，不能只根据 remote 判断模板身份。根目录应有 `app.yaml`、`AGENTS.md`、`docs/apphub-contract.md`、`frontend/`、`backend/app.py` 和 `backend/CLAUDE.md`，运行入口与项目合同一致。合同缺失时读取迁移规范，不在原目录重新初始化或批量覆盖。

无论新项目还是已绑定项目，都沿用实际项目规则：

- Skill 的安装和调用入口由模板项目维护，本 Skill 不注入项目规则或宿主钩子。
- `AGENTS.md` 保持简短，只放项目约束和规范入口；保留原有业务说明与其他工具规则。开发命令继续维护在 `README.md`，不为普通需求强制生成另一套 `project-spec/development/deployment` 文档。
- 只有新增长期有效的业务约定、维护限制或验证方式时，才更新对应项目文档，并引用实际源码或测试。数据层需要的 `docs/ops-app/data-spec.md` 等文档仍按数据访问规范维护。
- 迁移项目缺少后端规范时，可按迁移规范从 `assets/backend/` 补齐；这些资产只有规范，不含构建或发布脚手架。

## 开发纪律

- 动手前查现有实现和调用方。较大改动简要说明目标、涉及模块及可观察的验收结果；小改动直接处理，不强制任务目录、PRD、多 Agent 或重复确认。
- 技术事实从代码、测试和配置查证；只向用户确认项目无法回答的业务口径、范围或验收行为。不让非开发用户选择实现框架。
- 优先复用项目已有能力和依赖。仅实现当前需求；不提前设计插件系统、万能组件、配置驱动框架或未使用的扩展点。
- 同一业务概念需要一起变化时再抽取公共能力；外观相似或字面量相同不构成抽象理由。文件按职责拆分，不追求最少文件或固定行数。
- 只修改当前需求相关代码，保留用户已有修改；清理本次产生的无用代码，不顺手格式化或重构无关模块。简短注释说明业务规则与特殊处理的原因。
- 改公共组件、请求函数或状态字段时搜索全部调用方，检查影响；修复行为实际所属位置，避免调用处层层补丁。不得用前端兼容分支掩盖后端合同漂移。
- 页面涉及真实数据时按数据规范交给数据 Skill；本 Skill 不选择或猜测数据集、字段、聚合、筛选、第三方场景或运行时签名。前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 不读取、输出或提交真实密钥、本地运行数据库和业务数据文件。已初始化的空白模板库按项目合同保留。
- 执行沿用用户已明确授权的范围和宿主权限。范围内的检查、修复不重复求确认；提交、推送、部署和真实数据写入须有相应授权，加载本 Skill 不授予这些权限。

## 验证与源码交付

- 完成后检查实际 diff，包括新增文件和已有暂存改动，确认没有无关重构、重复基础设施、调试残留或通过关闭规则绕过检查。
- 按改动运行相关行为测试；Bug 修复应有能复现问题的验证。文案、间距等低风险改动不机械新增测试。已有无关失败要说明，不删测试以换取通过。
- 源码交付前按部署规范执行前端测试、生产构建及项目合同要求的检查；命令取实际项目，不能编造尚不存在的 `lint/typecheck`。
- 页面主流程、布局、真实联调、平台环境分别需要对应证据；构建通过不能代替浏览器或线上验收。
- 提交前重新读取部署规范，确认本次完整文件范围、binding 与目标仓库。用户明确授权后执行 `opscli app push "<project-directory>" --message "<summary>"`；不绕过它直接 Push，不创建第二条 release。
- push 成功只表示源码到达远端。线上构建、发布、健康状态和回滚由 AppHub 处理，没有平台证据时不得报告已部署。

## 错误与输出

模板克隆或 Git 清理失败时保留原始错误并停止后续初始化；合同无法核实时保留已验证部分，不伪造实现。迁移无法保持业务行为时保留源项目。

`opscli` CLI 或相关 MCP 工具失败时，立即按 `ops-feedback` 规范提交结构化反馈并返回 `feedback_uuid`；认证未授权、用户取消和五分钟内已反馈的同一错误除外。

简要报告修改文件、实际验证、交付状态和阻塞项。未执行的测试、构建、浏览器验收或线上部署不得写成通过。
