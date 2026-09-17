# `opscli app dev` 本地开发预览需求

## 1. 背景

通过统一模板创建或迁移重构的 AppHub 看板，已经具备 `.env.example`、`scripts/init_env.py`、FastAPI 后端和 Vite 前端开发能力。但用户在 Codex Desktop 中提出“本地启动当前项目”时，Codex 有时会绕过项目环境准备，直接执行 `uvicorn` 或前端开发命令，导致 `.env` 缺失、运行配置不完整或前后端只启动一侧。

当前可以通过“请先自动生成并检查 `.env` 配置，完成编译后在本地启动当前项目”等长提示词规避问题，但普通用户不应理解 `.env`、`uvicorn`、`pnpm` 等专业概念。系统需要提供一个稳定、确定性的本地开发入口，让简短自然语言请求也能可靠进入边编辑边预览的开发模式。

## 2. 目标

1. 新增唯一标准命令 `opscli app dev <project-root>`。
2. 用户提出“本地启动当前项目”“本地预览”“启动开发环境”或“边改边看”时，Codex 统一调用该命令。
3. 启动前自动生成并检查本地环境配置，不允许绕过失败直接启动底层服务。
4. 同时启动 FastAPI reload 和 Vite dev server，支持前后端热更新。
5. 任一进程退出或用户按 `Ctrl+C` 时，可靠清理另一进程。
6. 保持 AppHub 线上构建、发布和运行合同不变。

## 3. 命令合同

```bash
opscli app dev <project-root>
```

- `project-root` 默认为当前目录。
- 后端默认使用 `127.0.0.1:8035`。
- 前端默认使用 `127.0.0.1:5173`。
- 可通过 `--backend-port` 和 `--frontend-port` 覆盖端口。
- 本次不新增 `opscli app start` 或 `opscli app preview`。

## 4. 执行流程

1. 校验目标目录属于受支持的 AppHub 看板模板项目。
2. 校验后端和前端端口合法且未被占用。
3. 执行项目的 `scripts/init_env.py`；`.env` 缺失时自动生成，已存在时不覆盖。
4. 对照 `.env.example` 检查配置键、重复键和 `INTERNAL_API_TOKEN` 有效性。
5. 根据 `.python-version` 准备项目 `.venv`。
6. 检查项目声明的 Python、Node、`uv` 和 `corepack` 环境。
7. 安装或校验后端依赖与前端锁定依赖。
8. 启动 `uvicorn backend.app:app --reload`。
9. 等待后端 `/__apphub_healthz` 返回成功后，启动 Vite dev server。
10. 任一子进程退出时停止另一进程；用户中断时清理全部子进程。

开发模式使用 Vite 按需编译和热更新，不要求先执行生产版 `pnpm build`。一次构建后启动继续由项目现有的 `scripts/start.ps1` 或 `scripts/start.sh` 负责。

## 5. 项目合同

受支持的看板项目必须提供：

- `.env.example`
- `.python-version`
- `scripts/init_env.py`
- `scripts/check_startup.py`
- `requirements.txt`
- `frontend/package.json`
- `frontend/pnpm-lock.yaml`
- `frontend/vite.config.js`
- `backend/app.py`

Vite 的 `/api` 代理继续指向本地后端 `127.0.0.1:8035`。项目特定的环境变量定义和默认值仍由模板的 `.env.example`、`scripts/init_env.py` 和后端 Settings 维护，`opscli` 不复制第二套业务配置权威源。

## 6. 改动范围

### 6.1 `open-opscli`

- `opscli/app/commands/cli.py`：注册 `app dev`。
- `opscli/app/services/dev.py`：实现纯本地环境准备和双进程编排。
- `tests/app/`：覆盖命令注册、参数转发、模板结构和 `.env` 校验。
- `opscli/skills/templates/ops-app-build-spec/SKILL.md`：增加自然语言到 `app dev` 的强制映射和禁止绕过规则。

### 6.2 统一模板

- 更新 `AGENTS.md`、`README.md`、`backend/CLAUDE.md` 和 `docs/apphub-contract.md`。
- 新增 `docs/ops-app/development.md`，声明本地开发标准入口和线上边界。
- 复用现有 `.env.example`、`scripts/init_env.py`、`scripts/check_startup.py` 和 Vite `/api` 代理，不重建第二套启动脚本。

### 6.3 已生成看板

- `prod-105` 同步新的开发入口和文档，用于验证现有模板看板可以被 `opscli app dev` 识别。
- 不修改业务页面、API、数据库结构和生产部署配置。

## 7. 不在本次范围

- 不新增 `opscli app start`。
- 不新增 `opscli app preview`。
- 不修改 `opscli app init` 或 `opscli app push`。
- 不调用 AppHub 远端 API或修改远端环境变量。
- 不修改 Dockerfile、Nixpacks、`app.yaml` 或生产端口 `8000`。
- 不改变数据库迁移、线上鉴权、数据查询或发布流程。
- 不把 `.env`、本地数据库或其他敏感配置提交到 Git 或打入生产镜像。

## 8. 线上运行边界

`opscli app dev` 是纯本地开发命令，不参与源码推送后的 AppHub 构建和启动。生产环境继续使用现有 Dockerfile、Nixpacks、AppHub 环境变量注入和 `uvicorn backend.app:app --host 0.0.0.0 --port 8000` 合同。

模板文档和本地编排能力的增加不得改变线上代码路径、容器入口、健康检查、数据库路径或前端生产构建行为。

## 9. 验收标准

1. `opscli app` 命令树包含 `dev`，且不包含新增的 `start` 或 `preview`。
2. `.env` 缺失时自动生成，已有 `.env` 不被覆盖。
3. `.env` 缺少模板声明的键、存在重复键或令牌仍为占位值时，服务启动前失败。
4. 后端使用 reload 模式，前端使用 Vite 热更新模式。
5. 后端健康检查通过后才启动并报告前端预览地址。
6. 端口冲突、依赖准备失败或任一子进程异常退出时返回明确错误。
7. 用户中断后不遗留前后端子进程。
8. `ops-app-build-spec` 明确将简短本地启动请求映射到 `opscli app dev`。
9. 模板和 `prod-105` 文档使用同一标准入口。
10. Dockerfile、Nixpacks、`app.yaml` 和线上生产运行行为保持不变。
