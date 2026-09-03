# 项目迁移规范

迁移目标是保持业务行为，并落到当前 AppHub 的 `root-v1` 单应用合同。不得用“能构建”代替功能等价证明。

## 迁移前证据

记录以下内容到 `docs/ops-app/assessment.md`：

- Git 根、当前分支和用户已有修改。
- 页面、路由、导航守卫和 404 行为。
- 表单、校验、上传、下载和用户反馈。
- API、WebSocket、鉴权、环境变量和第三方依赖。
- 数据模型、数据库位置、迁移方式和现有数据。
- 构建、测试、静态资源和运行入口。

迁移计划必须给出旧文件到新文件的映射、功能核验清单和无法自动处理的项目。大范围移动、覆盖或删除前等待明确确认。

## Next.js + React 到 Vite + React

可以迁移：

- 客户端页面、组件、样式和静态资源。
- 普通文件路由到显式 React Router 路由。
- 浏览器端数据请求和状态管理。
- 能直接替换的 `next/link`、`next/image`、环境变量和元数据。

按以下方式映射：

| Next.js | Vite + React |
| --- | --- |
| `pages/` 或 `app/` 客户端页面 | `frontend/src/pages/` 与路由配置 |
| `next/link` | 客户端路由链接 |
| `next/image` | 普通图片组件或现有图片库 |
| `NEXT_PUBLIC_*` | 经审查的 `VITE_*` |
| API Routes | FastAPI `/api` 路由 |

发现 SSR、RSC、ISR、Server Actions、Edge Runtime、Middleware、服务端鉴权或服务端密钥时停止。列出依赖这些能力的文件和业务影响，提示联系 IT，不把逻辑搬到浏览器。

## 普通 HTML/CSS/JS 到 Vite + Vue

固定目标为 Vite + Vue 3 + Element Plus；默认保留 JavaScript：

1. 识别页面、共享区域、表单、表格、弹窗和导航。
2. 每个路由页面转换为 Vue 页面组件，共享区域转换为组件。
3. 全局变量转换为响应式状态；DOM 查询和手工事件绑定转换为模板绑定。
4. 表单、表格、弹窗、反馈和导航优先映射到 Element Plus。
5. 业务样式和品牌视觉迁移到受控样式文件，不照搬无效选择器。
6. 网络请求迁移到 `frontend/src/api/`，并使用相对 URL。

原项目只有一个简单页面时保持组件数量精简。不得为每个 HTML 标签创建组件。

## FastAPI 与 SQLite

- 新入口固定为 `backend/app.py`，由 `app.yaml` 声明。
- Vite `dist`、API、WebSocket 和 `/__apphub_healthz` 由同一个 FastAPI 进程提供。
- 路由顺序必须防止 SPA fallback 吞掉 API、健康检查和 WebSocket。
- SQLite 路径迁移为 `APP_DB_PATH` 或 `opscli.app.get_engine()`。
- 结构变化写入 `migrations/*.sql`，不得通过删除数据库重新初始化。
- 其他后端或任何非 SQLite 数据库均停止，只生成评估和 IT 交接清单。

## 发布合同迁移

- 根目录新增并校验 `app.yaml`，作为唯一发布声明。
- 根目录 `requirements.txt` 精确锁定普通依赖，并包含通过 `import opscli.app` 校验的真实 `aukeys-opscli>=0.0.129`。
- 新增 `nixpacks.toml`，作为 AppHub 发布构建入口。
- 根目录 `Dockerfile` 只保留本地、CI 和可复现构建用途。
- Vite 改为 `base: './'`；Axios、WebSocket 和动态资源改为相对 URL。
- 目标目录必须成为独立 Git 根，分支固定为 `main`。
- 不创建本地 `opscli/` 包绕过真实依赖安装。

## 不支持范围

包括但不限于 Angular、Svelte、Nuxt、非 React 的 SSR 框架、桌面/移动应用、PHP、Java、Go、Ruby、.NET 后端，以及需要自动转换现有生产数据库的项目。

识别到不支持范围后：

1. 不安装替代依赖，不移动或删除原文件。
2. 写明技术栈证据、入口、数据和阻塞能力。
3. 输出 `docs/ops-app/it-handoff.md`。
4. 告诉用户当前不支持，请联系 IT 人员处理。

## 迁移验收

- 对照迁移前清单逐页、逐路由、逐接口核验。
- 关键表单、权限、上传下载和错误状态有可重复测试。
- 前端构建与后端测试通过。
- 根页面、静态资源、SPA 刷新、相对 API 和 WebSocket 在 `root-v1` 下正常。
- `/__apphub_healthz` 返回 200，且不依赖业务数据。
- SQLite 通过临时 `APP_DB_PATH` 完成迁移和读写验证。
- Git 根独立、分支为 `main`，发布声明和依赖锁定通过检查。
- 旧实现只在行为等价得到验证且用户已确认后删除。
