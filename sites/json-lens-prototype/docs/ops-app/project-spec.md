# test-keepa 项目规格

## 技术栈与目录

- 前端：原生 JavaScript、Vite 8、Playwright，位于 `frontend/`。
- 后端：Python 3.12、FastAPI、Pydantic、Uvicorn，入口为 `backend/app.py`。
- 发布：根目录 `app.yaml`、`compose.apphub.yaml`、`nixpacks.toml`、`Dockerfile`。
- Python 依赖：`requirements-app.txt` 为业务依赖，`requirements.txt` 在本地与 Nixpacks 额外安装正式 `aukeys-opscli`。
- 测试：前端测试位于 `frontend/tests/`，后端与部署合同测试位于 `tests/`。

## 业务能力

- 构造并提交 Keepa 场景查询。
- 展示、筛选、排序和分页浏览 JSON 结果。
- 导出当前筛选和排序后的 CSV。
- 支持桌面、移动端、暗色主题和多种布局变体。

## 接口

- `GET /__apphub_healthz`：平台健康检查。
- `POST /api/v1/keepa/run`：执行 Keepa 查询。
- 其他 `/api/*`：JSON 404。
- 其他 GET：静态文件或 SPA fallback。

## 约束

- 单 FastAPI 进程托管 API 和 `frontend/dist`。
- API、静态资源和前端路由均使用相对地址。
- 平台登记为 SQLite并分配托管卷，当前业务无数据库读写和持久化需求。
- Keepa 凭证和 Viewer 身份只在后端请求生命周期中使用。
