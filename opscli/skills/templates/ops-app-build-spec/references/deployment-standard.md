# 发布规范

当前 AppHub 发布目标是一个 FastAPI 应用。Vite 只生成静态产物，FastAPI 同时承载页面、API、WebSocket 和平台健康检查。

## 固定根级产物

```text
app.yaml
requirements.txt
nixpacks.toml
Dockerfile
.dockerignore
frontend/
backend/
migrations/
```

`app.yaml` 是唯一发布声明。入口固定为 `backend/app.py`，运行时固定为 `fastapi`。发布目录必须是独立 Git 仓库根目录，当前分支必须为 `main`。

## Nixpacks 主路径

AppHub 首次创建应用和后续发布均使用 Nixpacks。根目录 `nixpacks.toml` 必须：

- 同时准备 Node 与 Python 构建环境。
- 使用前端锁文件执行冻结安装。
- 在 `install` 与 `python:install` 分别使用 `...` 保留 Node/Python provider 的安装命令。
- 将 `python -c "import opscli.app"` 追加到 `python:install`，前端冻结安装追加到 `install`；Vite 构建同时依赖两个阶段。
- 执行 Vite 生产构建，产物输出到 `frontend/dist`。
- 使用平台同款命令启动 FastAPI：

```text
python -m opscli.app.migrate && uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

当前 Coolify 环境中 Node 与 Python setup 必须使用同一个已验证的 nixpkgs archive，避免运行库版本漂移。项目切换前端包管理器时，只调整冻结安装和构建命令，不改变 Python 安装、启动模块、端口或健康路径。

## Python 依赖

根目录 `requirements.txt` 是发布构建读取的唯一 Python 依赖清单：

- 普通第三方依赖使用 `package==version`。
- 必须包含真实包 `aukeys-opscli>=0.0.129`，并把最低版本更新到首个包含 `opscli.app` 的正式版本。
- 不允许本地 `opscli/` 包、同名模块、`-e`、相对路径或未固定版本的 Git 依赖。
- `app.yaml` 声明的入口所需依赖必须全部在该文件中。

## Dockerfile 次级路径

根目录 `Dockerfile` 只用于本地、CI 和可复现构建，不改变 AppHub 的 Nixpacks 发布方式。

- Node 构建阶段先复制 `frontend/package.json` 和锁文件，再冻结安装；随后复制前端源码并构建。
- Python 运行阶段先复制 `requirements.txt`、安装并验证 `opscli.app`，再复制 `backend/`、`migrations/`、`app.yaml` 和 Vite 产物。
- 禁止无边界 `COPY . .`。
- 使用明确版本的官方 Node 与 Python 基础镜像。
- 运行阶段使用非 root 用户，监听 `0.0.0.0:8000`。
- 应用源码保持 root 只读所有权，只把 `/data` 授权给运行用户。
- 不把 SQLite 文件、环境文件、密钥、前端依赖目录或测试缓存复制到镜像。
- 启动命令与 Nixpacks 保持一致。

## `.dockerignore`

必须排除 `.git`、编辑器目录、前端依赖和构建缓存、Python 虚拟环境和缓存、SQLite 文件、日志、环境文件、私钥和包管理器认证文件。不得排除：

- `app.yaml`
- `requirements.txt`
- `nixpacks.toml`
- `frontend/package.json` 与锁文件
- `frontend/src/`、`frontend/public/`
- `backend/`
- `migrations/`

## `root-v1` 路由

平台完成鉴权后移除公开前缀，应用只处理根路径：

```text
页面与 SPA: /
静态资源: /assets/*
业务 API: /api/*
WebSocket: /ws
平台健康: /__apphub_healthz
```

- Vite `base` 固定为 `./`。
- Axios 和 WebSocket 使用相对 URL。
- FastAPI 不读取公开前缀，不设置框架子路径参数。
- API、WebSocket 和健康路由必须先于静态挂载与 SPA fallback 注册。
- `/__apphub_healthz` 不访问业务数据或外部系统。

## SQLite 持久化

`app.yaml` 声明 `services.sqlite: true` 时，平台注入 `APP_DB_PATH=/data/app.db` 并在启动前运行迁移。应用不得硬编码线上数据库路径，也不得提交数据库文件。

本地开发默认将 `APP_DB_PATH` 指向仓库内已忽略的 `.data/app.db`；本地测试必须指向临时目录。`.data/` 必须同时从 Git 和构建上下文排除。

## 发布检查

按顺序检查：

1. 确认目标目录是独立 Git 根，当前分支为 `main`。
2. 校验 `app.yaml`，确认 `runtime: fastapi`、`entrypoint: backend/app.py` 和实际入口一致。
3. 检查普通依赖全部精确锁定，真实 `aukeys-opscli` 已发布兼容版本且通过模块导入检查。
4. 执行前端测试与生产构建。
5. 执行后端测试，覆盖健康、API、静态资源、SPA fallback 和 SQLite 临时路径。
6. 静态核对 Nixpacks 与 Dockerfile 的构建产物、启动命令、端口和健康路径一致。
7. 获得许可后再执行镜像构建、启动或真实发布。

## 完成标准

- Nixpacks 是 AppHub 发布主路径，Dockerfile 只承担本地和 CI 验证。
- 单个 FastAPI 进程可返回页面、静态资源、API、WebSocket 和健康响应。
- Vite 产物只包含相对 URL，在完整公开地址下正常加载。
- `/__apphub_healthz` 返回 200，应用侧路径不含平台公开前缀。
- SQLite 只通过 `APP_DB_PATH` 使用平台数据盘，迁移可重复执行。
- Git 根、`main` 分支、依赖锁定和发布声明均通过检查。
