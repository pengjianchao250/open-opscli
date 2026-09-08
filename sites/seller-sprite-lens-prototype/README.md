# SellerSprite Lens Prototype

卖家精灵 MCP/REST 场景的静态工作台原型。页面与 Keepa JSON Lens 统一使用 DaisyUI 5 + Tailwind CSS 4 的表单、按钮、卡片、标签、主题和表格组件，同时保留适合多场景切换的固定侧边栏；数据区复用 JSON Lens 的筛选、排序、树形和原始 JSON 浏览方式，并增加 SellerSprite 异步任务状态与 JSON v2 多工作表支持。

## 一期范围

- 开放 13 个可返回 JSON 的普通场景。
- 暂不开放 Listing Analysis 测试功能。
- 暂不开放只返回官方 XLSX 的 `branddb` 和 `aba-reverse`。
- 所有任务固定提交 `export_format=json`。
- “下载 CSV”只导出浏览器中当前工作表经过筛选和排序后的数据。

## 运行

```powershell
npm install
npm run dev
```

打开 `http://127.0.0.1:4174/`。开发服务器会把 `/api` 代理到本地 `http://127.0.0.1:8765`。本地 FastAPI 需要显式启用 `LOCAL_AUTH_FALLBACK_ENABLED=true`，或在 `127.0.0.1` 域下设置 `polarisUserToken` Cookie；页面不读取 localStorage 登录信息。

页面只调用应用前缀内的相对 `./api/v1/seller-sprite/*` 地址。部署到 AppHub 后，浏览器 Cookie 由同源网关验证，网关注入 Viewer 身份头并将请求转发给 FastAPI；前端不读取或保存认证凭证。查询参数、任务编号和任务状态仍保存在 `localStorage`。

## 测试

```powershell
npm install
npm test
```

单元测试覆盖场景参数转换、JSON v2 工作表、筛选排序和 CSV。Playwright 覆盖 AppHub 相对 API 路径、任务提交、异步续查、服务与额度检查、任务恢复、DaisyUI 组件合同、主题切换和桌面/移动侧边栏。
