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

打开 `http://127.0.0.1:4174/`。开发服务器会将同源的 `/api/v1/mcp-api-keys/config` 代理到 `https://ops.api.xenkee.com`；可通过环境变量 `OPS_WEB_ORIGIN` 覆盖该地址。

在浏览器开发者工具中为 `http://127.0.0.1:4174` 设置 OPS 登录态：

- `localStorage.OPERATION_TOKEN`：OPS Token，可带或不带 `Bearer` 前缀。
- Cookie `polarisUserToken`：当前 OPS Session；如登录态包含 `opscliDeviceCode`，一并设置。

页面通过 `@aukeys/ops-mcp-api-sdk` 换取并在内存中缓存 MCP API Key，业务请求自动注入 Bearer Header。查询参数、任务编号和任务状态仍保存在 `localStorage`，MCP API Key 不会写入浏览器存储。

## 测试

```powershell
npm install
npm test
```

单元测试覆盖场景参数转换、JSON v2 工作表、筛选排序和 CSV。Playwright 覆盖 OPS 登录态换取、MCP API Key 自动注入、任务提交、异步续查、连接额度、任务恢复、Key 不落盘、DaisyUI 组件合同、主题切换和桌面/移动侧边栏。
