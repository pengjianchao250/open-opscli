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
python -m http.server 4174 --directory sites/seller-sprite-lens-prototype
```

打开 `http://127.0.0.1:4174/`。默认 API 地址为 `http://127.0.0.1:8765/api/v1/seller-sprite`。

API Key 只保存在当前页面内存。查询参数、任务编号和任务状态保存在 `localStorage`，便于刷新页面后继续查询后台任务。

## 测试

```powershell
npm install
npm test
```

单元测试覆盖请求鉴权、场景参数转换、JSON v2 工作表、筛选排序和 CSV。Playwright 覆盖任务提交、异步续查、连接额度、任务恢复、API Key 不落盘、DaisyUI 组件合同、主题切换和桌面/移动侧边栏。
