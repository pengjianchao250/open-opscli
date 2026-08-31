# JSON Lens Prototype

这是一个可丢弃的 HTML-first 原型，用来验证动态 API/JSON 结果的浏览方式。

## 运行

在仓库根目录执行：

```powershell
python -m http.server 4173 --directory sites/json-lens-prototype
```

打开 <http://127.0.0.1:4173/?variant=a>。

布局变体：

- `?variant=a`：左侧请求构建器 + 右侧结果区
- `?variant=b`：结果优先，顶部请求工具栏
- `?variant=c`：数据检查器 + 请求/字段侧栏

原型内置离线样例数据。默认 API 地址为 `http://127.0.0.1:8765/api/v1/keepa/run`。真实 API 模式下，可在“连接设置”中修改接口地址并填写 Bearer API Key；Key 只存在当前页面内存，不写入 localStorage。

结果表格会缩略显示超长文本，悬停可查看完整内容。“下载 CSV”会导出当前筛选和排序后的表格数据，数组和对象字段以 JSON 文本保存。

字符串列表也会按场景显示业务列名，例如 Top Sellers 显示 `sellerId`、Best Sellers 显示 `asin`。大结果默认每页显示 100 行，筛选、排序和下载仍覆盖全部匹配数据。

## 测试

```powershell
npm install
npm test
```

测试分层：Node 原生测试验证请求头归一化；Playwright 验证浏览器请求合同、场景切换 E2E 和桌面/移动端视觉快照。更新视觉基线使用 `npm run test:update-snapshots`。
