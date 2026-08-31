# 空项目初始化规范

本规范适用于空目录、只有 README/需求文档的仓库，或没有可识别前端入口的项目。初始化目标是生成可运行的前端基础项目；后端由其他人员负责时，不得创建 FastAPI 占位服务、业务实现或假健康检查。

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
```

使用初始化当日 npm registry 的最新稳定版本，写入 `package.json` 和 `pnpm-lock.yaml`。Skill 不在文档中长期固定具体版本号；安装后把实际解析版本记录到 `docs/ops-app/project-spec.md`。只允许稳定版，禁止 beta、alpha、rc 和 `next` 标签。

Node.js 只要求主版本大于 22。初始化前检查 `node --version`；不因补丁版本差异强制切换运行时。依赖安装或构建产生的 engine 警告允许记录到 `docs/ops-app/assessment.md`，不作为初始化、构建或测试的阻断条件。

初始化时允许联网查询版本；网络不可用时停止依赖初始化并说明原因，不猜测版本号。

不默认加入 TypeScript、Vitest、ESLint、Prettier、E2E 测试或其他工具链。已有项目已经使用这些工具时保留；用户单独要求时再加入。

## 初始化命令示例

```bash
pnpm create vue@latest frontend
cd frontend
pnpm install
pnpm add element-plus axios vue-router pinia
pnpm run dev
```

`create-vue` 选项固定为：TypeScript=No、Vue Router=Yes、Pinia=Yes；其他测试和代码质量工具=No。官方 Vue 文档将 `create-vue` 作为 Vite 项目脚手架，并提供 Router、Pinia 等选项。[Vue Quick Start](https://vuejs.org/guide/quick-start)

## 初始化后的最小结构

```text
frontend/
├── public/
├── src/
│   ├── api/http.js
│   ├── assets/
│   ├── components/
│   ├── layouts/
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
```

只创建实际使用的目录。`HomeView.vue` 作为最小示例页面，至少展示一个 Element Plus 组件、一个加载状态和一个错误状态；不得写入虚假的业务数据或业务接口。

`src/api/http.js` 只创建统一 Axios 实例，默认基础地址为 `/api`、配置超时和统一错误入口。后端尚未交付时不调用不存在的业务接口。

Vite 开发服务器必须监听 `0.0.0.0`，端口使用 Vite 默认或自动递增策略，保证局域网可访问。

`src/stores/app.js` 只放应用级状态，例如侧栏展开状态或用户界面偏好；不得预先生成业务实体、数据库字段或权限模型。

## 必须生成的配置

- 根目录 `ops-app.config`，作为应用 ID、应用名和部署前缀的唯一来源。
- `frontend/vite.config.js`，开发 `base` 为 `/`，生产构建使用共享配置派生部署前缀。
- `frontend/src/router/index.js`，使用 `createWebHistory(import.meta.env.BASE_URL)`。
- `frontend/src/main.js`，注册 Vue Router、Pinia 和 Element Plus。
- `frontend/.env.example`，只声明 `VITE_API_BASE_URL=/api` 等非敏感变量。
- 根目录 `.dockerignore`。
- `docs/ops-app/assessment.md`、`project-spec.md`、`development.md`。

应用 ID 为空时允许本地开发；生产构建必须在第一次发布前补齐应用 ID。Vite 配置、Axios 基础地址和路由基路径不得各自维护一份部署路径。

## 后端交接边界

后端由其他人员负责时，Skill 只记录交接要求，不生成后端代码：

- 服务名：`backend`。
- 容器端口：`8000`。
- 健康检查：`/health`。
- 业务 API 前缀：`/api`。
- 启动命令、`pyproject.toml`、`uv.lock`、Dockerfile target 和数据库配置由后端人员提供。
- 若使用 SQLite，数据库路径固定为 `/data/app.db`，卷由 Compose 管理。

后端交付前，项目状态为“前端初始化完成，等待后端交付”，不得宣称 Compose、Dockerfile 或生产发布已完成。不得用空 FastAPI 容器、假健康检查或占位数据库绕过交接。

## 初始化验收

```text
pnpm install --frozen-lockfile
pnpm run dev
pnpm run build
```

验收项目：

- 根路径开发页面可以打开。
- Vue Router 路由可以切换，刷新策略已记录。
- Element Plus 组件正常渲染。
- Pinia 已注册且只有最小应用状态。
- Axios 实例可被业务模块导入，但不调用未交付接口。
- 构建产物位于 `frontend/dist`。
- 生产构建缺少应用 ID 时按约定失败。
- 没有生成后端占位代码、真实密钥或业务数据库。
