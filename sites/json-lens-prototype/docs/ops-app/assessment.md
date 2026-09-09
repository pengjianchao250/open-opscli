# 存量项目迁移评估

## 迁移前状态

- 项目已经绑定 AppHub 应用 `test-keepa`，独立 Git 仓库使用 `master` 分支。
- 页面为原生 JavaScript + Vite，包含 Keepa 场景表单、结果浏览、筛选、排序、CSV 导出和视觉回归测试。
- 后端为 FastAPI，提供健康检查、Keepa 查询接口和静态资源托管。
- 浏览器只调用当前站点 `./api/v1/keepa/run`，未发现前端密钥或第三方直连。
- 项目无业务持久化、定时任务和 SellerSprite 数据需求；AppHub 平台登记为 SQLite，发布层必须保留数据库声明和托管 Compose 合同。

## 不符合项

- 前端文件和 npm 清单位于仓库根目录，缺少模板合同要求的 `frontend/`。
- 缺少根 `AGENTS.md`、`backend/CLAUDE.md`、`docs/apphub-contract.md` 和 `docs/ops-app/` 项目文档。
- Dockerfile、Nixpacks 和 FastAPI 静态目录仍指向根级前端构建产物。

## 支持结论

本项目可按存量应用原地迁移。迁移仅移动前端目录并同步构建、测试和文档路径，不更换前端框架，不改变页面、接口、身份或数据行为。业务不复制 SQLite 模型、Alembic 或任务调度；发布层保留 AppHub 登记所需的 SQLite 声明和平台 Compose。
