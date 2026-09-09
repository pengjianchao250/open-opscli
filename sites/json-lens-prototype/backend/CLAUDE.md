# test-keepa 后端开发约定

## 项目边界

- 本服务为 AppHub 单进程应用：FastAPI 托管 `frontend/dist`、Keepa API 和健康检查。
- 唯一生产入口是 `backend.app:app`，容器端口为 `8000`。
- AppHub 发布层分配 SQLite 托管卷，但当前业务代码不读写数据库；不添加虚假迁移、模型、后台任务或持久化能力。

## HTTP 合同

- `GET /__apphub_healthz` 必须快速返回裸 JSON `{"status":"ok"}`，不得依赖 Keepa 或其他上游。
- `POST /api/v1/keepa/run` 是唯一业务接口，请求和响应以 `backend/app.py` 的 Pydantic 模型与实际路由为准。
- 未知 `/api/*` 返回 JSON 404；其余 GET 请求由 SPA fallback 处理。
- 前端构建产物固定读取仓库根 `frontend/dist`。

## 身份与安全

- 线上 Viewer 身份由 AppHub 网关注入；后端只在请求生命周期内使用 `X-Ops-Token`、用户头或会话信息。
- 凭证不得落盘、写日志、进入异常文本或返回浏览器。
- Keepa 调用必须走受治理的 opscli 实现，浏览器不得直连 Keepa 或 opscli 服务。

## 验证

- 后端与部署合同：`npm --prefix frontend run test:deployment`
- 前端测试：`npm --prefix frontend run test:unit` 与 `npm --prefix frontend run test:e2e`
- 前端构建：`npm --prefix frontend run build`
