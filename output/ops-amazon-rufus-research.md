# ops-amazon-rufus Research

## 2026-04-29 复刻扩展端 Rufus 行为研究

### 本轮需求

让 `opscli amazon-rufus get <asin> <country>` 尽量复刻扩展端 `AsinRufusDialog` 的“使用问题获取 Rufus 回答”行为，优先对齐请求参数，而不是改变命令形态或引入新的产品能力。

### 扩展端关键实现结论

参考路径：

- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/AsinRufusDialog/composables/useAsinRufusQuery.ts`
- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/AsinRufusDialog/composables/createAsinRufusRunner.ts`
- `E:/code/work/extension/frontend/packages/extensions/src/shared/api/rufus.ts`

扩展端请求模型：

1. 从已拦截记录中选择同 ASIN 的 `/rufus/cl/streaming` seed request。
2. 用 seed request 的 `requestBody` 作为基础 payload。
3. 替换 `queryContext.query` 为当前问题。
4. 显式补齐 `queryContext.actionType = "SEARCH"` 与 `queryContext.qis = "NileCLTextInput"`。
5. 显式补齐 `pageContext.originPageType = "DETAIL_PAGE"`。
6. 将 `pageContext.targetPageMetadata` 与 `pageContext.originPageMetadata` 中的 `ASIN` 对齐到目标 ASIN；不存在则追加。
7. 显式设置 `bottomSheetContext.previousTurnsBottomSheetSize = "expanded"`。
8. 显式设置 `impressionsContext.FIRST_TIME_USER_MESSAGE_SEEN_STATUS = "SEEN"`。
9. 请求 URL 以真实 `requestUrl/pageUrl` 的 origin 为基础重建 `/rufus/cl/streaming`，并设置：
   - `tabId`
   - `programId = "NILE_CLASSIC:desktop-cl"`
   - `ref = "nl_cl_dsk_csq"`
10. 请求 headers 近似完整复用拦截 headers，并使用浏览器凭证上下文。

### 当前 CLI 行为差距

参考路径：

- `opscli/amazon_rufus/services/replay.py`
- `opscli/amazon_rufus/services/browser.py`
- `opscli/amazon_rufus/services/manager.py`

当前 CLI 已具备 seed 捕获与页面内 fetch 重放能力，但参数对齐不足：

1. `build_payload()` 只替换 `queryContext.query`。
2. 不补 `actionType`、`qis`、`pageContext.originPageType`。
3. 不修正 `targetPageMetadata/originPageMetadata` 中的 ASIN。
4. 不补 `bottomSheetContext` 与 `impressionsContext`。
5. 重放 URL 直接使用 `seed.request_url`，不保证 `programId/ref` 存在。
6. headers 仅保留 `anti-csrftoken-a2z`、`content-type`、`x-amz-is-papyrus`，比扩展端更保守。
7. CLI 会把上一题解析出的 `threadId` 注入后续题，扩展端当前主流程没有动态传入该上下文；这是 CLI 已有增强，但可能影响“逐题独立复刻”的一致性。

### 外部信息约束

Amazon 官方对 Rufus 的公开定位是“购物助手”，能力包括回答商品问题、做推荐与辅助比较；这与扩展端围绕商品详情页上下文构造请求的做法一致。公开资料没有提供 `/rufus/cl/streaming` 私有接口契约，因此本需求应以内部扩展端实现作为参数基准，不应臆造未观察到的新字段。

官方资料：

- https://www.aboutamazon.com/news/retail/amazon-rufus
- https://advertising.amazon.com/library/guides/getting-started-with-rufus
- https://sell.amazon.com/blog/amazon-rufus

### 研究结论

本轮应采用“最小参数对齐”方案：

1. 在 CLI payload 构造层复刻扩展端 `buildPayloadFromRecord()` 的字段修正规则。
2. 在 CLI URL 构造层保证 `tabId/programId/ref` 与扩展端一致。
3. headers 先保持当前 allowlist，避免浏览器禁止脚本设置的 header 导致请求失败；如实测缺 header，再按 allowlist 扩展。
4. 保留 CLI 现有 `threadId` 串联能力，但把 `threadState` 补齐为扩展端默认值 `THREAD_STATE_UNKNOWN`，并在后续 Spec 中明确是否提供开关控制独立问答。

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
