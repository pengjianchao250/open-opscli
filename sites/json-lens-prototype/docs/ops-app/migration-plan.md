# 迁移计划

1. 将根级 Vite、npm、Playwright 和前端测试文件移动到 `frontend/`。
2. 修改 Dockerfile、Nixpacks 和 FastAPI 静态目录，统一使用 `frontend/dist`。
3. 补齐 AppHub 运行合同、项目规格、数据合同、开发和部署文档。
4. 加强部署合同测试，验证目录、声明和构建路径。
5. 运行前端单元测试、端到端测试、生产构建和后端部署测试。

迁移不更换前端框架、不修改 Keepa 接口、不引入数据库。Git 历史可用于整体回滚本次目录迁移。
