# JSON Lens Prototype

这是一个可丢弃的 HTML-first 原型，用来验证动态 API/JSON 结果的浏览方式。

## 运行

在当前目录执行：

```powershell
npm install
npm run dev
```

打开 <http://127.0.0.1:4173/?variant=a>。开发服务器会将同源的 `/api/v1/mcp-api-keys/config` 代理到 `https://ops.api.xenkee.com`；可通过环境变量 `OPS_WEB_ORIGIN` 覆盖该地址。

在浏览器开发者工具中为 `http://127.0.0.1:4173` 设置 OPS 登录态：

- `localStorage.OPERATION_TOKEN`：OPS Token，可带或不带 `Bearer` 前缀。
- Cookie `polarisUserToken`：当前 OPS Session；如登录态包含 `opscliDeviceCode`，一并设置。

布局变体：

- `?variant=a`：左侧请求构建器 + 右侧结果区
- `?variant=b`：结果优先，顶部请求工具栏
- `?variant=c`：数据检查器 + 请求/字段侧栏

原型内置离线样例数据。页面通过 `@aukeys/ops-mcp-api-sdk` 换取并在内存中缓存 MCP API Key，业务请求自动调用 `/api/v1/keepa/run` 并注入 Bearer Header；连接设置可选覆盖 MCP API 基地址，也兼容粘贴旧版完整接口地址，留空时使用 OPS 配置返回地址。MCP API Key 不会写入浏览器存储。

结果表格会缩略显示超长文本，悬停可查看完整内容。“下载 CSV”会导出当前筛选和排序后的表格数据，数组和对象字段以 JSON 文本保存。

字符串列表也会按场景显示业务列名，例如 Top Sellers 显示 `sellerId`、Best Sellers 显示 `asin`。大结果默认每页显示 100 行，筛选、排序和下载仍覆盖全部匹配数据。

## 测试

```powershell
npm install
npm test
```

测试分层：

- Node 原生测试验证表格筛选/排序和 CSV 导出。
- Playwright 场景矩阵覆盖全部 11 个 Keepa 查询场景，校验 OPS 登录态换取、MCP API Key 自动注入、页面请求体和响应渲染。
- 页面交互测试覆盖必填/筛选校验、复杂参数转换、API 错误、结果视图、布局切换、站点兼容和历史查询。
- 视觉回归测试覆盖桌面端、移动端、暗色主题和历史查询展开状态。

常用入口：

```powershell
npm run test:e2e          # 无头模式运行全部页面测试
npm run test:e2e:headed   # 打开浏览器运行，便于观察交互
npm run test:e2e:ui       # 使用 Playwright UI 逐条运行和回放
npm run test:e2e:report   # 打开最近一次测试的 HTML 报告
```

更新视觉基线使用 `npm run test:update-snapshots`。测试使用浏览器内的 OPS 配置和业务 API mock，不依赖真实后端或真实凭证。
