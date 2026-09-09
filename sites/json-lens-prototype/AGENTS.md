# AI 协作规则

- 修改前先阅读 `docs/apphub-contract.md`、`backend/CLAUDE.md` 和 `docs/ops-app/project-spec.md`。
- 前端位于 `frontend/`，后端入口为 `backend/app.py`，生产环境只运行一个 FastAPI 进程。
- 浏览器只请求当前站点的相对 `/api` 地址，不得保存或输出 JWT、Cookie、API Key。
- AppHub 将应用登记为 SQLite，发布声明和 `compose.apphub.yaml` 必须保留平台托管存储合同；业务代码当前不读写数据库，也不添加迁移或持久化逻辑。
- 修改后运行前端测试、生产构建、后端测试和部署合同检查。
- 未经用户明确确认，不提交、推送或触发线上发布。
