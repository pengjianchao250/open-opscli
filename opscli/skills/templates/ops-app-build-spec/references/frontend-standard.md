# 前端项目规范

本规范适用于 Vite + React 和 Vite + Vue 3。普通 HTML/CSS/JS 的固定迁移目标为 Vite + Vue 3 + Element Plus；`element-ui` 属于 Vue 2 生态，不作为新项目依赖。发现 Vue 2 或 Vue 2 专用 Vite 插件时停止并联系 IT，不做隐式主版本升级。

## 技术栈

| 场景 | 标准 |
| --- | --- |
| 现有 React 或 Next.js | Vite + React + TypeScript |
| 现有 Vue 3 | Vite + Vue 3 + TypeScript |
| 普通 HTML/CSS/JS | Vite + Vue 3 + TypeScript + Element Plus |

已有 Vite 项目保留当前 React/Vue 方向和已使用的组件库；不得为了统一外观而重写无关页面。普通 HTML 迁移使用 Element Plus 实现表单、表格、对话框、反馈和导航等通用组件，业务布局与展示样式可保留原 CSS。

保留现有包管理器，只保留与它匹配的一个锁文件。不得无依据升级全部依赖或切换包管理器。

## 目录

```text
frontend/
├── public/
├── src/
│   ├── api/
│   ├── assets/
│   ├── components/
│   ├── pages/
│   ├── router/
│   ├── styles/
│   ├── App.tsx | App.vue
│   └── main.tsx | main.ts
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

只创建实际使用的目录。页面负责路由级组合，组件负责可复用界面，`api/` 统一封装后端请求。

## 部署基路径

项目必须把 Skill 的 `assets/ops-app-config.mjs` 和 `assets/ops-app-config.d.mts` 复制到 `deployment/`。`vite.config.ts` 必须导入该共享模块读取根目录 `ops-app.config`，并按命令区分路径：

- 开发服务器：`/`
- 构建：`/ops-app/{projectId}/{appName}/`

构建时 `projectId` 为空、`appName` 非法或配置无法解析，立即失败。不要提供无 ID 的部署兜底路径。

```ts
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import {
  getOpsAppDeployBase,
  loadOpsAppConfig,
} from '../deployment/ops-app-config.mjs'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const configPath = resolve(projectRoot, 'ops-app.config')

export default defineConfig(({ command }) => ({
  base:
    command === 'build'
      ? getOpsAppDeployBase(
          loadOpsAppConfig(configPath, { requireProjectId: true }),
        )
      : '/',
}))
```

已有 Vite 插件和其他配置必须保留并合并到返回对象，不能用示例覆盖。禁止从 `.env`、Compose 或 Docker build args 再读取项目 ID和应用名称。

React Router 的 `basename`、Vue Router 的 history base 使用 `import.meta.env.BASE_URL`。代码动态拼接静态资源时同样使用 `import.meta.env.BASE_URL`；普通 import、CSS `url()` 和 HTML 资源交给 Vite 改写。

前端 API 默认访问 `/api` 或部署环境明确提供的 API 地址。静态资源前缀只服务前端文件，不得生成 `/ops-app/{id}/{name}/api`。

## React 约束

- 使用函数组件和 Hooks，保持现有状态管理方案。
- Next.js 路由迁移为显式客户端路由；页面参数、查询参数和 404 行为必须逐项核验。
- `next/image`、`next/link` 等框架组件替换为 Vite/React 可用实现，并保留可访问性和资源路径。
- Next.js 服务端能力按迁移规范处理，不得在浏览器端复制服务端密钥或逻辑。

## Vue 与 Element Plus 约束

- 使用 Vue 3 Composition API 和 `<script setup lang="ts">`。
- 普通 HTML 迁移默认使用 Vue Router；只有单页且没有导航状态时可不引入路由。
- Element Plus 优先使用直接组件导入；只有组件数量足以产生明确收益时才增加自动导入插件。
- 使用 `@element-plus/icons-vue` 中的图标，不用 emoji 代替功能图标。
- 将原 DOM 事件、全局变量和手工选择器转换为响应式状态、组件属性和事件；不得把整页 HTML 原样塞入一个组件。

## 接口与环境变量

- 只有 `VITE_` 前缀变量能进入浏览器，禁止存放密钥。
- 提供 `.env.example`，只写变量名和安全示例。
- 请求封装统一处理基础地址、JSON、超时和业务错误；鉴权方式以现有项目或平台契约为准，不自行发明。
- 前后端数据结构变化时同步 TypeScript 类型和 FastAPI schema。

## 验收

- 安装、类型检查、测试和 `vite build` 通过。
- 开发环境根路径可用，构建资源路径包含完整部署前缀。
- 直接访问和刷新嵌套路由不返回 404。
- 页面、表单、交互、错误状态和响应式布局与迁移前业务行为一致。
- 浏览器中无资源 404、路由基路径错误、密钥泄漏或阻断性控制台错误。
