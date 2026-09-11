# 变更记录

## 2026-09-09 AppHub - 同步最新安全 Compose 模板

**变更原因**：提交 `4620206` 的 release #106 在服务端校验阶段返回 `YAML-INVALID`，明确指出 `compose.apphub.yaml` 与平台安全模板不一致。最新模板已使用 `APPHUB_RESOURCE_ID` 隔离 Traefik 路由资源，站点仍使用旧版 `APP_SLUG` 资源名。

**改动点**：将 `compose.apphub.yaml` 原样同步到统一模板提交 `ac18605`，路由 middleware、router 和 service 名称改用 `APPHUB_RESOURCE_ID`；部署合同增加模板字段及旧资源名回归检查，并同步部署说明。

**验证结果**：站点 Compose 与统一模板 SHA-256 均为 `5BCD79FB852C676D7C84DAC47CC59F4C544844443A62EA4DDBF26C4EC8EA1E72`；YAML 解析、部署合同、后端冒烟、前端单元测试 6 项、Vite 生产构建和 `git diff --check` 均通过。

**影响范围**：AppHub Compose 安全校验与 Traefik 路由资源命名；应用 URL、FastAPI 路由、页面及 Keepa 数据行为不变。

**回滚方式**：回退本次修改会恢复平台已拒绝的旧版 Compose 模板，不建议回滚。

## 2026-09-09 AppHub - 恢复 test-keepa 应用身份

**变更原因**：项目本地 binding 和远端仓库均属于 `test-keepa`，但发布清单曾被临时切换到 `test-keepa-2`，会把源码身份指向错误的 AppHub 应用。

**改动点**：将 `app.yaml` 恢复为 `app_id: 1kKLO`、`title: test-keepa`，同步部署合同断言和部署文档，并禁止本地旧版 opscli 再注入模板已移除的 `name` 字段；不修改本地 binding、业务接口或页面行为。

**验证结果**：YAML 与 `.opscli/app.json` 身份核对通过，前端单元测试 6 项通过，Vite 生产构建通过，部署合同与后端冒烟通过，`git diff --check` 通过。

**影响范围**：仅 AppHub 应用身份声明、部署测试和交付文档。

**回滚方式**：回退本次修改会重新将发布清单指向 `test-keepa-2`，不建议回滚。

## 2026-09-09 Keepa - 修复 AppHub Viewer 被误判为 MCP 会话

**变更原因**：AppHub 已完成 Cookie 校验并向应用注入 Viewer JWT 与用户身份，但站点 FastAPI 在调用 Keepa 共享内核时只传递了 JWT、邮箱和 Session，遗漏 `apphub_viewer` 认证模式，导致共享凭证层误走普通 MCP 登录流程并错误提示缺少 `session_id`。

**改动点**：站点后端按请求凭证将 MCP 请求上下文标记为 `apphub_viewer` 或 `apphub_session`，同时明确该请求不携带 MCP API Key；保持浏览器相对 API、AppHub Cookie 校验和 Keepa 业务接口不变。

**验证结果**：部署冒烟新增 Viewer JWT 无 Session 回归，确认 Keepa 调用期间可读取 `apphub_viewer`、用户邮箱和 JWT，且不会把用户身份字段混入业务参数。

**影响范围**：仅 `POST /api/v1/keepa/run` 调用 Keepa 共享内核时的请求级认证上下文。

**回滚方式**：回退本次提交会恢复线上“无 session_id”错误，不建议回滚。

## 2026-09-09 AppHub - 重新触发发布验证

**变更原因**：AppHub 发布链路已由平台同事处理，重新提交当前已验证的站点源码，确认自动构建与发布流程恢复正常。

**改动点**：仅增加本次重新发布记录，不修改应用配置、业务接口或页面行为。

**验证结果**：提交前重新执行部署合同与后端冒烟检查。

**影响范围**：仅触发 AppHub 对新提交执行自动发布。

**回滚方式**：无需业务回滚；可删除本条记录。

## 2026-09-09 AppHub - 对齐平台 SQLite 与 Compose 发布合同

**变更原因**：AppHub 控制面确认应用元数据登记为 SQLite、部署类型为 Docker Compose，但仓库 `app.yaml` 未声明 `database`，导致控制面无法生成实际构建任务并返回 `UPSTREAM_ERROR`。

**改动点**：恢复 `database.kind: sqlite` 和 `database.path: /data/app.db`；加入当前统一模板的 `compose.apphub.yaml`，同步项目合同和部署回归测试。业务后端仍不读写数据库，不增加模型或迁移。

**验证结果**：`compose.apphub.yaml` 与统一模板内容一致并通过 PyYAML 解析；Python 3.12 部署合同与后端冒烟通过，Vite 8.2.2 生产构建通过，`git diff --check` 通过。

**影响范围**：AppHub 发布编排、托管卷和路由声明；Keepa API 与页面行为不变。

**回滚方式**：回退本次提交会重新造成平台 SQLite 元数据与项目声明不一致，不建议回滚。

## 2026-09-08 AppHub - 删除平台不支持的 YAML 字段

**变更原因**：AppHub release #77 明确返回 `runtime`、`python`、`entrypoint` 为不允许的额外输入，导致提交 `1184788` 在服务端校验阶段报 `YAML-INVALID`。

**改动点**：从 `app.yaml` 删除三个不支持字段；部署合同增加字段黑名单回归检查。Python 版本、FastAPI 入口和启动命令继续分别由 `.python-version`、Dockerfile 与 Nixpacks 管理。

**验证结果**：Python 3.12 部署合同与后端冒烟通过，前端部署测试通过，Vite 8.2.2 生产构建通过。

**影响范围**：仅 AppHub YAML 声明；前端目录、FastAPI 入口和运行方式不变。

**回滚方式**：回退本次提交会重新引入平台已确认不支持的字段，不建议回滚。

## 2026-09-08 AppHub - 按统一规范迁移前端目录

**变更原因**：现有站点虽可构建，但缺少 `ops-app-build-spec` 要求的 `frontend/` 与项目运行合同，发布结构与统一模板不一致。

**改动点**：将原生 Vite 页面、npm 清单、Playwright 配置和前端测试迁入 `frontend/`；同步 Dockerfile、Nixpacks、FastAPI 静态目录和部署测试；Docker 只安装业务依赖并复用基础镜像 SDK，Nixpacks 校验实际使用的 Keepa 模块；补齐 AppHub、项目、数据、开发和部署文档。

**验证结果**：本地隔离环境中，Node 单元测试 6 项通过，Playwright 36 项通过，Vite 8.2.2 生产构建通过；Python 3.12 部署合同与后端冒烟通过，真实 `frontend/dist` 静态托管冒烟通过，`aukeys-opscli 0.0.132` 的 Keepa 模块导入通过，Python compileall 与 `git diff --check` 通过。本机未安装 Docker，未执行镜像构建。

**影响范围**：仅项目目录、构建路径和开发文档；页面行为、Keepa API、身份模式和数据语义保持不变。

**回滚方式**：回退本次迁移提交，恢复根级 Vite 文件及原构建路径。
