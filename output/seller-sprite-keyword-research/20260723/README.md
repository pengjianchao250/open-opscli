# 卖家精灵关键词选品回归基线（2026-07-23）

## 基线文件

- 官方导出：`../../KeywordResearch-US-202606-667951.xlsx`
- 官方文件 SHA-256：`0fbee9b6c3a4f90bf31c5eec9768d940f65c1eb6f092c99a93e14aea1b3474f9`
- 页面查询响应：`page-query-response.json`
- 官方导出结构：`official-export-profile.json`
- 页面与官方导出对照：`page-vs-official-comparison.json`
- 统一导出契约：`normalized-export-contract.json`
- Web 导出请求契约：`web-export-contract.json`

## 本次确认

- 查询入口：`GET https://www.sellersprite.com/v2/keyword-research`
- 请求编码：`application/x-www-form-urlencoded`
- 响应类型：`text/html`
- 页面结果：50 条业务记录（150 个 HTML `tr`）
- 官方导出：2000 行、28 列
- 前 20 条页面记录与官方工作簿比较：20 条全部通过，共比较 18 个核心字段
- 主列表导出：`GET /v2/keyword/async/list-export-research`，异步生成后从 `/v2/export-log` 下载
- 所选关键词明细导出：`POST /v2/keyword/keywords-batch-export`，一次选择 1—50 个关键词

对照时已确认两个规范化口径：页面“#”是列表序号，不是 ABA 排名；页面均价 `N/A` 在官方导出中写为 `$0.00`。

补充核验：2026-07-23 再次检查首行完整 DOM，页面实际包含 10 个 ASIN 链接，解析器会全部提取；`page-query-response.json` 中的 `relatedAsins` 是采集脚本保留的前 3 个紧凑预览，不代表页面上限。

## 使用方式

1. 接口回归时比较请求方法、路径、参数名、页面表格字段和前 50 条结构化记录。
2. 导出回归时比较工作表名称、28 列表头顺序、字段类型、列宽、冻结窗格、Notes 工作表和文件哈希基线。
3. 页面展示有舍入，本场景本地 XLSX 只能保留 HTML 提供的精度；28 列结构、格式和值类型与官方统一，不承诺底层数值与官网异步导出逐位相同。接口数值与页面值对比需使用 `page-vs-official-comparison.json` 中的精度规则。
4. 官方导出文件是 `.xlsx`；后续产品若仍将导出参数命名为 `xls`，应明确它是兼容选项还是实际旧版二进制格式。

## 尚未覆盖

- 原始 HAR 和完整 HTTP 响应头（本次桌面开发者工具运行时不可用）。
- 导出任务的真实 JSON 响应样本与导出记录页下载请求。
- Web 页面下一页及不同排序条件。
- 开放 API `/v1/keyword-research` 与当前 Web 页面 GET 接口的在线对账。
