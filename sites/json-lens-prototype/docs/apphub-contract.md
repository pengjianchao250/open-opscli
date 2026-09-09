# AppHub 应用合同

## 发布结构

- 发布声明唯一来源是根目录 `app.yaml`，应用身份为 `test-keepa`。
- 前端源码位于 `frontend/`，构建产物为 `frontend/dist/`。
- 后端入口为 `backend/app.py`，生产命令为 `uvicorn backend.app:app --host 0.0.0.0 --port 8000`。
- Dockerfile 与 Nixpacks 必须构建同一份前端产物，并由同一个 FastAPI 进程托管。
- AppHub 应用登记为 SQLite，`app.yaml` 固定声明 `database.kind: sqlite` 与 `database.path: /data/app.db`，并使用模板提供的 `compose.apphub.yaml` 创建托管卷、路由和健康检查任务。
- 当前业务不读写 SQLite，不包含数据库模型或迁移；数据库声明仅用于保持仓库发布合同与平台元数据一致。

## 路由合同

- AppHub 公开前缀由平台处理，应用只接收根路径请求，不读取或拼接 app ID、slug、公开域名。
- Vite 固定 `base: './'`；页面资源和 API 使用相对路径。
- `GET /__apphub_healthz` 返回 `{"status":"ok"}`。
- `POST /api/v1/keepa/run` 执行 Keepa 场景查询。
- 未知 `/api/*` 返回 JSON 404，不进入 SPA fallback。
- 其余 GET 路由优先返回静态文件，找不到无扩展名路径时返回 `frontend/dist/index.html`。

## 身份合同

- `app.yaml.opscli.auth_mode` 为 `viewer`。
- 线上优先使用 AppHub 注入的 `X-Ops-Token` 和 `X-User-Email`；本地联调可使用 `polarisUserToken` Cookie 或 `X-Session-Id`。
- 前端不读取、保存或提交身份凭证，不直连 Keepa 或 opscli 服务。

## 构建合同

- Python 版本为 3.12，Node.js 构建镜像使用 Node 24。
- 前端包管理器保持 npm，唯一锁文件为 `frontend/package-lock.json`。
- 普通 Python 依赖精确锁定在 `requirements-app.txt`；Docker 使用基础镜像内的 SDK，本地与 Nixpacks 使用正式 `aukeys-opscli` 包，并检查本应用实际依赖的 Keepa 模块可导入。
