# AppHub 部署

## 前置条件

- 当前分支为 `master`，`origin` 指向 `apps/test-keepa.git`。
- `.opscli/app.json` 存在但未被 Git 跟踪，binding slug 与 `app.yaml.name` 均为 `test-keepa`。
- `app.yaml`、`compose.apphub.yaml`、`Dockerfile`、`nixpacks.toml`、`requirements.txt`、`requirements-app.txt`、`frontend/` 和 `backend/app.py` 存在。
- 前端测试、生产构建、后端测试和部署合同通过。

## 运行方式

AppHub 构建 `frontend/dist` 后，以单进程启动：

```text
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

健康检查路径为 `/__apphub_healthz`。AppHub 按 SQLite 应用部署，使用 `compose.apphub.yaml` 创建应用专属托管卷子目录并注入 `SQLITE_PATH=/data/app.db`；当前业务代码不访问该数据库。

Docker 只安装 `requirements-app.txt`，避免覆盖 AppHub 基础镜像内的 opscli SDK；Nixpacks 和本地隔离环境通过 `requirements.txt` 安装正式 SDK，并验证 Keepa 运行模块可导入。

## 源码交付与回滚

获得明确确认后使用 `opscli app push` 将当前工作区整体提交并普通推送到远端 `master`。推送成功只代表源码已到达远端；构建、release 和线上发布结果以 AppHub 页面为准。

代码回滚使用 Git 回退到迁移前提交后重新推送。平台发布回滚在 AppHub 中选择上一成功版本；当前业务不写数据库，托管卷无需数据迁移。
