# 空项目初始化规范

本规范适用于空目录、只有 README/需求文档的仓库，或没有可识别前端入口的项目。初始化目标是生成最小、真实、可发布的 Vue 3 + FastAPI 单应用；不得虚构业务接口、业务数据或权限结果。

## 仓库前置

- 目标目录必须是独立 Git 仓库根目录，不能嵌套在其他仓库中。
- 初始化分支固定为 `main`。
- 根目录放置 `app.yaml`，它是唯一发布声明。
- 不创建提交、不配置远端、不执行发布，除非用户明确要求。

## 默认技术栈

```text
pnpm + create-vue
Vue 3
Vite
Element Plus
Axios
Vue Router
Pinia
JavaScript
FastAPI
SQLite
```

使用初始化当日 registry 的稳定版本，前端实际解析版本写入 `package.json` 和 `pnpm-lock.yaml`。Python 普通依赖写入根目录 `requirements.txt` 并使用 `==` 精确锁定；平台 SDK 使用真实包 `aukeys-opscli>=0.0.129`，构建阶段必须验证 `import opscli.app`。若索引尚无兼容正式版本，停止发布并联系 IT。

不得创建本地 `opscli/` 包、同名模块或路径依赖。网络不可用时停止依赖初始化并说明原因，不猜测版本号。

不默认加入 TypeScript、E2E 或额外代码质量工具。已有项目已经使用这些工具时保留；用户单独要求时再加入。

## 初始化结构

```text
frontend/
├── public/
├── src/
│   ├── api/http.js
│   ├── assets/
│   ├── components/
│   ├── router/index.js
│   ├── stores/app.js
│   ├── styles/index.css
│   ├── views/HomeView.vue
│   ├── App.vue
│   └── main.js
├── index.html
├── package.json
├── pnpm-lock.yaml
└── vite.config.js
backend/
├── __init__.py
└── app.py
migrations/
tests/
docs/ops-app/
app.yaml
requirements.txt
nixpacks.toml
Dockerfile
.dockerignore
.gitignore
.data/                  # 本地运行生成，必须忽略
```

只创建实际使用的目录。`HomeView.vue` 至少展示一个 Element Plus 组件、加载状态、空状态和错误状态，不写虚假业务数据。`backend/app.py` 只负责平台健康路由、已有业务 API 和 Vite 产物托管；没有业务需求时不创建占位 CRUD。

## 前端初始化

```bash
pnpm create vue@latest frontend
pnpm --dir frontend install
pnpm --dir frontend add element-plus axios vue-router pinia
```

`create-vue` 选项固定为：TypeScript=No、Vue Router=Yes、Pinia=Yes；其他测试和代码质量工具按项目需要选择。

- `frontend/vite.config.js` 固定 `base: './'`，生产输出 `frontend/dist`。
- `frontend/src/api/http.js` 创建统一 Axios 实例，基础地址使用 `./api`。
- WebSocket 从当前页面 URL 派生相对 `./ws`，不拼接平台公开前缀。
- `frontend/src/router/index.js` 使用 `import.meta.env.BASE_URL`，并验证 SPA 刷新。
- Vite 开发服务器可监听 `0.0.0.0`；启动前仍需遵守宿主授权。

## 根级配置

从 Skill 复制并按项目调整：

- `assets/app.yaml`
- `assets/nixpacks.toml`
- `assets/Dockerfile`
- `assets/requirements.txt`
- `assets/.dockerignore`

`app.yaml` 保持 `runtime: fastapi`、`entrypoint: backend/app.py`。若使用 SQLite，保持 `services.sqlite: true`；本地默认使用已忽略的 `.data/app.db`，生产通过 `APP_DB_PATH=/data/app.db` 使用平台数据盘。

## 初始化验收

```text
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run build
python -m pytest tests -q
```

验收项目：

- Git 根独立，当前分支为 `main`。
- `app.yaml` 能通过当前 schema，且入口文件存在。
- Vite 产物使用相对静态资源 URL。
- FastAPI 能托管根页面、静态资源和 SPA fallback。
- `/__apphub_healthz` 返回 200，且不依赖业务数据。
- 相对 API 与 WebSocket 请求在 `root-v1` 下可用。
- `requirements.txt` 的普通依赖精确锁定，真实 `aukeys-opscli` 已通过兼容模块导入检查。
- 没有生成真实密钥、本地数据库文件或虚假业务实现。
