# 前端项目规范

本规范适用于 Vite + React 和 Vite + Vue 3。普通 HTML/CSS/JS 的固定迁移目标为 Vite + Vue 3 + Element Plus；发现 Vue 2 或 Vue 2 专用插件时停止并联系 IT，不做隐式主版本升级。

## 技术栈

| 场景 | 标准 |
| --- | --- |
| 空项目 | Vite + Vue 3 + Element Plus + Axios + Vue Router + Pinia |
| 现有 React 或 Next.js | Vite + React，保留原语言和已验证工具链 |
| 现有 Vue 3 | Vite + Vue 3，保留原语言和已验证工具链 |
| 普通 HTML/CSS/JS | Vite + Vue 3 + Element Plus，默认保留 JavaScript |

已有 Vite 项目保留当前 React/Vue 方向和组件生态。保留现有包管理器，只保留匹配的一个锁文件；不得无依据升级全部依赖。

## 目录

```text
frontend/
├── public/
├── src/
│   ├── api/
│   ├── assets/
│   ├── components/
│   ├── pages/ | views/
│   ├── router/
│   ├── styles/
│   ├── App.tsx | App.vue
│   └── main.tsx | main.ts | main.js
├── index.html
├── package.json
├── pnpm-lock.yaml | package-lock.json | yarn.lock
└── vite.config.ts | vite.config.js
```

只创建实际需要的目录和组件。迁移必须保持页面、路由、表单、上传下载、错误状态和权限表现，不以构建成功代替行为等价。

## 相对路径合同

当前 AppHub 路由合同为 `root-v1`。平台移除公开前缀后，应用只处理根路径请求。

Vite 配置固定：

```js
import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
  build: {
    outDir: 'dist',
  },
})
```

- React Router 或 Vue Router 使用 `import.meta.env.BASE_URL`，不得写死平台公开路径。
- Axios 基础地址使用 `./api`；业务调用继续使用相对端点。
- WebSocket 从 `window.location` 派生相对 `./ws`，并按页面协议选择 `ws:` 或 `wss:`。
- 动态资源优先使用模块 import 或 `new URL(..., import.meta.url)`，不要从域名根拼接 `/assets`。
- 禁止读取平台身份、公开前缀或转发头来二次改写浏览器地址。

## FastAPI 托管边界

生产环境不启动独立前端服务器。Vite 只负责构建，`frontend/dist` 由 FastAPI 托管：

- API、WebSocket 与 `/__apphub_healthz` 路由先注册。
- `/assets` 静态目录在 API 之后挂载。
- SPA fallback 最后注册，只响应非 API 的页面路径。
- 缺少 `frontend/dist/index.html` 时启动或请求必须返回明确错误，不静默返回空页面。
- 开发期可分别启动 Vite 与 FastAPI，但联调请求仍使用相对 URL，并通过 Vite proxy 指向后端。

## 构建与验收

- 使用锁文件对应的冻结安装命令。
- 生产构建输出必须位于 `frontend/dist`。
- HTML、JS、CSS、图片和字体引用均为相对 URL。
- 根页面、嵌套路由刷新、404、加载、空、错误状态通过测试。
- 相对 API 与 WebSocket 在本地代理和 FastAPI 托管产物下行为一致。
- 不把 Token、真实账号、内部地址或数据集结果写入静态产物。
