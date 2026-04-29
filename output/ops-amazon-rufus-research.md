# ops-amazon-rufus Research

## 研究目标

为 `opscli` 增加一条新的 Amazon Rufus 能力链路，满足以下目标：

- 新增 CLI 命令：`opscli amazon-rufus get <asin> <country>`
- 新增可安装 Skill：`ops-amazon-rufus`
- Skill 支持远端升级，用于同步题库与运行参数
- 运行时复用已登录 Amazon 的本地 Chrome 会话，通过 Playwright 连接 Chrome
- 打开商品页后尽早拦截 `/rufus/cl/streaming` seed request
- 参考现有前端 `AsinRufusDialog` / `asin_rufus_batch` 的实现，重放问题并解析回答
- 上传接口本期不真正执行，但上传 payload 结构需要与现有前端口径对齐
- 上传部分需要保留真实发请求代码，默认以注释状态留在实现中

---

## 本地现状

### 当前仓库已有能力

1. `opscli amazon` 已具备 Playwright 抓取能力，但定位是商品页与搜索页采样，不包含 Rufus。
2. 现有 `amazon` 模块默认直连新开的 Chromium，会话与用户本地已登录 Chrome 隔离。
3. 现有 `ops-amazon` Skill 仅指导 AI 使用 `opscli amazon scrape/payload/search/schema/history`，没有 Rufus 工作流。
4. `opscli skills` 已支持“模板安装 + 远端升级”模式，当前 `ops-dataset-query` 是唯一远端升级样例。

### 与本需求最相关的内部 prior art

#### 仓库内 prior art

- `opscli/amazon/scraping/scraper.py`
  - 现有 Playwright 异步抓取骨架可复用。
  - 但当前实现绑定 `amazon.com` 和独立浏览器实例，不满足“复用本地 Chrome 登录态”。

#### 外部前端 prior art

主要参考以下路径：

- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/AsinRufusDialog/`
- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/ProductRufusAnalysisDialog/composables/runAsinRufusBatchRefetch.ts`

研究结论：

1. `AsinRufusDialog` 的核心不是直接使用拦截到的回答，而是：
   - 先从已拦截记录中选择一个 seed request
   - 基于该 request 生成新的 Rufus payload
   - 再主动重放流式请求获得回答
2. `useAsinRufusQuery.ts` 中的关键能力包括：
   - `selectAsinRufusSeedRecord()`：选择 seed request
   - `buildPayloadFromRecord()`：在原始 requestBody 基础上替换 query，并补齐 ASIN / thread context
   - `getTabIdFromRecord()`：从请求字段或 URL 提取 `tabId`
3. `shared/api/rufus.ts` 已验证前端侧可通过：
   - 复用拦截请求的 URL / headers / payload / tabId
   - 再次 `POST /rufus/cl/streaming`
   - 读取 SSE 流并解析 `inference` / `close` 事件
4. `runAsinRufusBatchRefetch.ts` 比 `AsinRufusDialog` 更接近这次 CLI 需求，但 CLI 一期应按新接口收敛数据面：
   - 拉取合并后的默认题目模板
   - 模板内直接包含题目列表
   - 逐题回放 Rufus
   - 将结果按统一 record + answer 结构上传
5. 现有前端的上传口径分两层：
   - `collectInterceptRecordsApi()`：上传一条 record 壳
   - `updateRecordAnswerApi()`：按题逐条回写结构化答案

---

## 外部官方技术约束

### Playwright 连接本地 Chrome

官方文档确认：

- Playwright Python 支持 `browser_type.connect_over_cdp()` 连接到已有 Chromium/Chrome 实例。
- 官方明确说明该方式是“较低保真”的 CDP 连接，优先用于 attach 到已有浏览器，而不是替代标准 `launch()`。
- 默认上下文会通过 `browser.contexts[0]` 暴露出来。

来源：

- https://playwright.dev/python/docs/api/class-browsertype

结论：

- 本需求可以合法走“用户手动打开 Chrome + `--remote-debugging-port=9222` + Playwright attach”的路线。
- 但实现上要尽量使用稳定、收敛的能力集合：
  - attach 到现有 Chrome
  - 复用已有 context/page
  - 做 request 监听
  - 必要时补 CDP session

### Playwright 网络监听能力

官方文档确认：

- Playwright 提供 `page.on("request")`、`page.on("response")`、`page.on("requestfinished")` 等网络事件。
- `Request.post_data()` 可读取 POST body。
- `Request.headers` 并不保证包含安全相关头和 cookie；需要使用更完整的 header 读取方法时应使用完整 header API。

来源：

- https://playwright.dev/python/docs/events
- https://playwright.dev/python/docs/network
- https://playwright.dev/python/docs/api/class-request

结论：

- seed request 的捕获应基于 Playwright request 事件完成。
- 为了得到尽可能完整的重放上下文，运行时不应只依赖简化 headers。

### Playwright 请求上下文与 cookie 共享

官方文档确认：

- `APIRequestContext` 可以与浏览器上下文共享 cookie 存储。

来源：

- https://playwright.dev/python/docs/api/class-apirequestcontext

结论：

- 理论上可以用 `browser_context.request` 做 Rufus replay。
- 但考虑到 Amazon Rufus 对浏览器环境更敏感，优先建议在已打开商品页的浏览器上下文里完成 replay，而不是切到独立 HTTP 客户端。

---

## 关键业务判断

### 1. 这不是 `ops-amazon` 的简单追加子命令

虽然 Rufus 属于 Amazon 域，但它与现有 `amazon scrape/search` 的运行模型显著不同：

- `amazon scrape/search`
  - 独立起浏览器
  - 不依赖用户本地登录态
  - 面向页面结构抓取
- `amazon-rufus get`
  - 必须 attach 到用户已登录 Chrome
  - 必须捕获并复用真实 Rufus 请求上下文
  - 面向会话化流式问答

推荐将其落成新命令模块 `amazon-rufus`，对应 Python 包目录 `opscli/amazon_rufus/`，以及新 Skill `ops-amazon-rufus`。

### 2. 运行时不能依赖宿主 Chrome MCP

用户要求里提到了“agent 使用 chrome mcp 连接 chrome”，但这属于宿主调试/观察能力，不应成为 `opscli` 运行时硬依赖。

结论：

- `opscli amazon-rufus get` 必须在纯本地 CLI 环境可运行
- Chrome MCP 只作为开发/排障辅助，不进入正式运行链路

### 3. 题库应走 Skill 远端升级，而不是运行时直连后端

项目铁律要求 Skill 不可直接直连业务后端，所有远端动作必须经由 `opscli` 正式入口。

结论：

- `ops-amazon-rufus` 采用“远端升级型 Skill”
- 运行时 `opscli amazon-rufus get` 只读本地 Skill 数据
- 题库通过 `opscli skills upgrade ops-amazon-rufus` 预同步，国家站点映射固定在代码中

### 4. 当前最接近的上传口径是 `asin_rufus_batch`

`runAsinRufusBatchRefetch.ts` 已经给出一套稳定的数据形状：

- `requestBody` 记录本次运行的业务上下文
- `questions[]` 记录题目列表
- `updateRecordAnswerApi()` 按 `{ question, answer }` 上传结构化答案

结论：

- `opscli` 一期不真正调用上传接口
- 但必须输出与该结构兼容的 payload，便于后续接真实 API
- 同时实现中要保留真实发请求代码，并默认注释掉

---

## 推荐方案

### 推荐方向

采用“新 CLI 模块 + 新远端升级 Skill + 本地 Chrome attach + seed request 重放”方案。

### 推荐命名

- CLI 名称：`amazon-rufus`
- Python 包目录：`amazon_rufus`
- 命令入口：`opscli amazon-rufus get <asin> <country>`
- Skill 名称：`ops-amazon-rufus`

### 推荐数据面

`ops-amazon-rufus` 本地数据目录建议至少包含：

- `data/VERSION.json`
- `data/question_templates.json`

`data/question_templates.json` 采用 `default-question-templates` 接口结构，模板与题目列表合并在同一 JSON 中：

```json
{
  "items": [
    {
      "id": 56,
      "description": "测试",
      "preferred_version_index": 0,
      "questions": [
        {
          "id": 3172,
          "text": "问题1",
          "position": 1
        }
      ],
      "created_at": "2026-04-28T09:25:05",
      "updated_at": "2026-04-28T09:25:12"
    }
  ]
}
```

### 推荐运行链路

1. 用户执行 `opscli amazon-rufus get <asin> <country> --new-chrome` 时，命令先新开 Chrome 调试窗口。
2. 自动启动命令固定为 `Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'`。
3. 用户在新开的 Chrome 窗口中登录 Amazon，或复用该 profile 中已有登录态。
4. 命令 attach 到 `http://127.0.0.1:9222`。
5. 在进入商品页前注册 `/rufus/cl/streaming` request 监听器。
6. 打开对应站点商品页。
7. 捕获第一个可用 seed request。
8. 从本地 Skill 数据读取合并后的默认题目模板。
9. 逐题重放 Rufus 请求并解析 SSE。
10. 返回答案结果，并同时构造标准上传 payload。

兼容模式：未传 `--new-chrome` 时，仍按既有逻辑直接连接 `--cdp-url` 指向的已启动 Chrome。

---

## 风险与对策

### 风险 1：页面打开后没有自动出现 seed request

原因：

- 某些站点或页面未自动触发 Rufus
- 用户未登录 Amazon
- 当前商品页未渲染 Rufus 区块

对策：

- 明确错误信息：请登录 Amazon、刷新页面、确认当前站点支持 Rufus
- 命令内部允许有限次页面刷新 / 等待策略

### 风险 2：仅靠 Playwright 高层 API 拿不到足够的请求上下文

对策：

- 第一实现优先使用 Playwright request 事件
- 若 headers / tabId / requestBody 不完整，再补 CDP 事件作为兜底

### 风险 3：不同国家站点 URL / 语言 / 文案差异

对策：

- 将国家映射固定在代码中，并按 `US` 等国家名维护最小可控映射
- 将题库通过 Skill 升级同步，不再拆分 runner config 与 `questions/<template_id>` 文件

### 风险 4：上传接口尚未定义

对策：

- 一期默认只构造 upload payload，不真正发请求
- 同时在代码中保留上传 HTTP 调用实现，并以注释方式禁用
- 输出结构与现有前端 `collect record + update answer` 口径保持一致

---

## 研究结论

这次需求的正确落地方式不是“在 Skill 里直接写一堆 Playwright 脚本”，而是：

- 在 `opscli` 中新增正式命令模块 `amazon-rufus`，对应包目录 `amazon_rufus`
- 在 `skills/templates/` 中新增远端升级 Skill `ops-amazon-rufus`
- 让 `opscli amazon-rufus get` 负责浏览器 attach、seed request 捕获、Rufus replay、答案解析与上传 payload 构造
- 让 `opscli skills upgrade ops-amazon-rufus` 负责题库远端同步，国家站点映射固定在代码中

这样才能同时满足：

- 仓库规范
- Skill 远端升级模型
- 与现有前端口径对齐
- 后续可接真实上传 API 的扩展性
