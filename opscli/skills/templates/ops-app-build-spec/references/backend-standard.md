# 后端项目规范

自动初始化和改造范围限定为 FastAPI + SQLite。发现其他后端框架或任何非 SQLite 数据库时停止并联系 IT，不做自动框架或数据库转换。

补充文档：SQLite 专项细则见 `sqlite-standard.md`，调用 opscli SDK/REST 见 `opscli-integration-standard.md`，红线总表见 `backend-redlines.md`，全文规范与项目级 `CLAUDE.md`/`AGENTS.md` 模板见 `assets/backend/`。这些补充文档中关于 uv、Alembic、Compose 或 `/health`、`/ready` 探针的描述，与本文及 `deployment-standard.md` 的 AppHub 运行合同冲突时，以本文与 `deployment-standard.md` 为准。

## 目录

```text
backend/
├── __init__.py
├── app.py
├── api/
├── db/
├── models/
├── schemas/
└── services/
migrations/
tests/
requirements.txt
```

只创建有实际职责的模块。简单项目可以合并空层，避免为了目录结构拆分一次性函数。Python 依赖清单固定在仓库根目录 `requirements.txt`。

## FastAPI 入口

`app.yaml` 的 `entrypoint` 固定指向 `backend/app.py`。模块必须导出 `app = FastAPI(...)`，并按以下顺序注册：

1. `/__apphub_healthz`。
2. `/api/*` 业务路由。
3. WebSocket 路由。
4. `/assets` 静态目录。
5. SPA fallback。

健康检查必须快速返回 200，不执行迁移、外部请求或业务查询。业务路由只处理协议转换、参数校验和响应；业务逻辑放在 service，持久化放在 db/repository 边界。

FastAPI 直接处理根路径，不读取平台公开前缀，不设置框架子路径参数。错误响应保持稳定结构和合适 HTTP 状态码，不向客户端暴露堆栈、SQL、文件路径或密钥。

## Vite 产物托管

- 构建目录固定为 `frontend/dist`。
- 使用 `StaticFiles` 托管 `frontend/dist/assets`。
- 根页面和 SPA fallback 使用 `FileResponse` 返回 `frontend/dist/index.html`。
- fallback 不得吞掉 `/api/*`、`/__apphub_healthz` 或 WebSocket。
- 生产只运行当前 FastAPI 进程，不再启动额外 Web 服务。

## SQLite

- 数据库路径只从 `APP_DB_PATH` 读取；本地开发默认指向仓库内已忽略的 `.data/app.db`，平台在启用 SQLite 时注入 `/data/app.db`。
- 测试必须指向 `tmp_path` 或其他临时目录，不复用本地开发数据库。
- 优先复用 `opscli.app.get_engine()`；启用外键约束和合理的 busy timeout。
- `.data/` 和数据库文件不得提交、复制到镜像或写入前端目录。
- 已有数据的表结构变化放在 `migrations/*.sql`，启动前由 `python -m opscli.app.migrate` 顺序执行。
- 需要多副本、高写入并发、跨服务共享数据库时停止并联系 IT 评估数据库迁移。

## 依赖与安全

根目录 `requirements.txt` 中的普通第三方依赖使用 `==` 精确锁定，平台 SDK 使用最低兼容版本，至少包含：

```text
fastapi==0.141.1
uvicorn==0.46.0
aukeys-opscli>=0.0.129
```

`aukeys-opscli` 必须从正式包源安装，构建阶段执行 `python -c "import opscli.app"`。若当前最低版本尚未包含该模块，先发布兼容正式版本并更新最低版本，再发布应用。禁止在项目中创建本地 `opscli/` 包、同名模块或可编辑路径依赖。

密钥、Token、真实账号和生产地址不得进入源码、镜像或文档。文件上传限制大小和类型；所有外部输入在信任边界校验，SQL 使用参数化查询或 ORM 表达式。

## 启动与验收

平台启动命令固定为：

```text
python -m opscli.app.migrate && uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

验收项：

- 依赖安装、静态检查和测试通过。
- `/__apphub_healthz`、核心 API、校验错误和异常响应通过测试。
- 根页面、静态资源和 SPA fallback 由 FastAPI 返回。
- API 与 WebSocket 路由不被 fallback 吞掉。
- `APP_DB_PATH` 指向临时文件时，迁移和 SQLite 读写通过。
- 日志中不出现密钥、完整鉴权头或敏感请求体。
