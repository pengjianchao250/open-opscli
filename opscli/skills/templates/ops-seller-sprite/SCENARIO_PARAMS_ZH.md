# 卖家精灵场景参数手册

本文件是 `ops-seller-sprite` 的唯一参数参考。`SKILL.md` 和 `SKILL_MCP.md` 只保留入口和执行规则；场景映射、参数词典、默认值、别名和类目口径统一以本文件为准。

## 场景映射

| 用户表达 | `scenario` |
| --- | --- |
| 查竞品 / 查产品 / 选竞品 / competitor lookup | `competitor-lookup` |
| 选产品 / product research | `product-research` |
| 关键词挖掘 / keyword mining | `keyword-miner` |
| 关键词选品 / 关键词研究 / keyword research | `keyword-research` |
| ABA 数据选品 / ABA 关键词趋势 / ABA research | `aba-research` |
| 全球商标库 / 商标查询 / brand database | `branddb` |
| 关联流量 / 关联产品 / 查关联 ASIN / association traffic | `association-traffic` |
| 出单词反查 / ABA 反查 / ABA reverse | `aba-reverse` |
| 关键词反查 / reverse ASIN | `keyword-reverse` |
| 查流量来源 / traffic source | `traffic-source` |
| 选市场 / market research | `market-research` |
| Listing panorama / listing analysis | `listing-analysis` |

## 公共参数与默认值

- `site`：站点，如 `US`、`JP`、`DE`、`UK`、`FR`、`IT`、`ES`、`CA`、`IN`、`MX`
- `period`：周期，如 `30d`、`nearly`、`2026-03`
- `page_size`：每页数量，默认 `100`
- `export_format`：默认 `xls`

默认值：

| 字段 | 默认值 |
| --- | --- |
| `site` | `US` |
| `period` | `30d` |
| `page_size` | `100` |
| `export_format` | `xls` |

关键注意：

- `product-research` 里的“月份 / 数据月份 / 2026-04”应传顶层 `period`，不是 `putawayMonth`。
- `keyword-research` 的 `period` 表示数据月份，使用 `YYYY-MM`；不要把公共默认 `30d` 当作月份。未指定时使用后端返回的最新可用月份，不硬编码页面月份选项。
- `keyword-research` 默认使用 `page=1/page_size=100`，只获取第一页后完成任务，不自动续页。
- `association-traffic` 使用公共默认 `page_size=100`；场景固定选择“用全部变体查询”，不对外开放“当前变体”切换。
- `aba-research` 未提供 `period`（或收到公共默认 `30d`）时默认最近完整周；固定只请求第一页 100 条，忽略公共分页覆盖值，并在本地生成 `.xlsx`。
- `aba-reverse` 未提供 `period`（或收到公共默认 `30d`）时，默认选择每周和最近完整周；显式周期可传具体周结束日或月份。只支持 `xls` / `xlsx`，实际返回官方 `.xlsx` 文件。
- `branddb` 固定使用 `browser-route`，`text` 必填，接口等待上限 120 秒；只支持 `xls` / `xlsx`，官方文件原样保存。请求发出后遇到超时、登录失效或结果不明时不会自动重试或换账号，避免重复消耗导出额度。
- `putawayMonth` 只表示上架月数，如 `1`、`3`、`6`、`12`。
- `competitor-lookup` 收到 Amazon 商品链接时，应先提取 ASIN，再传 `params.asins`。
- `competitor-lookup` 如果用户只给了单个 `asin`，也应先归一化成 `params.asins` 再执行。
- `listing-analysis` 结果通常 3 分钟以上才生成，推荐使用 `listing-analysis-submit/status/result` 三段式；提交走 `ai-history?module=LA` 页面输入，续查用 `task/history` 按 ASIN 获取真实报告 `taskId`，取结果再进入 `ai-report?id=<taskId>&from=history` 捕获 `competing-lookup`；不要让 `seller_sprite_run` 同步阻塞等待完整结果。

## 缺参澄清规则

- 场景不明确时先澄清，不要直接跑。
- 只问必填，不问可选。
- `competitor-lookup` 至少需要 `keyword`、`brand`、`sellerName`、`asins` 或 Amazon 商品链接中的一种。
- `competitor-lookup` 缺少上述主筛选条件时，应在本地快速报错或继续澄清，不要把无效请求拖成 MCP 30 秒超时。
- `keyword-reverse` 必须有 `asin`。
- `traffic-source` 必须有关键词或 ASIN。
- `association-traffic` 必须有 1—20 个合法 ASIN；可传数组，也可传逗号、换行、制表符或 TXT/Excel 按列复制文本。
- `aba-research` 必须有父/子 ASIN 或关键词，可使用 `q`、`keywordOrAsin`、`keyword` 或 `asin`。
- `aba-reverse` 必须有 1—20 个 ASIN 或 Amazon 产品链接；周期可省略，默认使用每周和最近完整周。
- `branddb` 必须有品牌名称、所有人或注册号搜索文本，统一传 `params.text`。
- `product-research`、`market-research`、`keyword-research` 虽然没有硬性必填，但用户只说“跑一下”“看下市场”时仍应先确认意图。
- `keyword-research` 执行前先确认当前 `seller_sprite_scenarios` 已暴露该场景；未暴露时不能改用 `keyword-miner` 冒充。
- `association-traffic` 执行前先确认当前 `seller_sprite_scenarios` 已暴露该场景；未暴露时不能改用 `traffic-source` 冒充。
- `aba-research` 执行前先确认当前 `seller_sprite_scenarios` 已暴露该场景；未暴露时不能改用 `keyword-research` 或 `aba-reverse` 冒充。
- `aba-reverse` 执行前先确认当前 `seller_sprite_scenarios` 已暴露该场景；未暴露时不能改用 `keyword-reverse` 冒充。

## 场景参数速查

| `scenario` | 必填 | 常用可选参数 | 默认重点 |
| --- | --- | --- | --- |
| `competitor-lookup` | `keyword` / `brand` / `sellerName` / `asins` / 商品链接 五选一；单个 `asin` 需先转成 `asins` | `node` / `category` / `nodeIdPath` / `nodeIdPaths` | `page=1`，按销量倒序，`lowPrice=N` |
| `product-research` | 无 | `recommendationMode`、类目参数、销量/价格/评分/卖家/关键词筛选 | `page=1`，`selectType=2`，按 `total_units` 倒序，`smallAndLight=N`，`lowPrice=N` |
| `keyword-miner` | `keyword` | `filterRootWord`、`amazonChoice`、`includeHighFrequency` | `pageNum=1`，`orderBy=5`，`desc=true` |
| `keyword-research` | 无 | 关键词、类目、需求/增长/竞争/转化/成本范围、`marketPeriod` | 数据月份用顶层 `period`；默认只取第一页 100 条 |
| `aba-research` | 父/子 ASIN 或关键词 | `departments`、`rankGrowthType`、排序、搜索结果范围筛选 | 周/月 ABA 周期；固定第一页 100 条；本地生成 XLSX |
| `branddb` | `text` | `feature`、`office`、`brandName`、`status`、`applicant`、`niceClass`、`applicationYear`、`expiryYear`、排序、`ids` | browser-route 直接请求；120 秒；官方 XLSX；不可自动重试 |
| `association-traffic` | `asins`，1—20 个 | `relations`、`orderField`、`desc` | 全部变体固定开启；只取第一页；`page_size=100` |
| `aba-reverse` | `asin` / `asins` / 产品链接，1—20 个 | `period`、`reverseType`、`orderField`、`orderDesc`、`conversionType`、`loadVariations` | 默认每周和最近完整周；直接保存官方完整 XLSX |
| `keyword-reverse` | `asin` | `badges` | `page=1`，`order=12`，`desc=true` |
| `traffic-source` | 关键词或 ASIN | `keyword`、`asin`、`asins`、`order`、`desc` | `pageNo=1`，`order=10`，`desc=true` |
| `market-research` | 无 | `departmentKeyword` / `category`、`node` / `nodeIdPath`、`newReleaseNum`、`topn`、市场指标筛选 | `sampleNumber=1`，`topn=10`，`newReleaseNum=6`，按 `total_sales` 倒序 |
| `listing-analysis` | `asin` | `station` | `station=GLOBAL`；用 submit/status/result 三段式续查 |

## `keyword-research` 关键词选品

### 场景边界

- 用于在关键词市场中按需求、增长、竞争、转化、成本和市场周期筛选机会词。
- 单一种子词扩词使用 `keyword-miner`；从 ASIN 找词使用 `keyword-reverse`；查关键词或 ASIN 的流量去向使用 `traffic-source`。
- 返回值属于第三方市场估算或外部情报，不等同于自有账号的搜索、订单或广告第一方数据。
- Skill 中存在此节不代表服务端已经部署。运行前必须以 `seller_sprite_scenarios` 的返回为准。

### 基础参数

| 中文含义 | 公共字段 | 页面字段 / 备注 |
| --- | --- | --- |
| 站点 | 顶层 `site` | 页面字段 `station`，由适配层映射 |
| 数据月份 | 顶层 `period` | 使用 `YYYY-MM`；页面字段 `month` 为 `YYYYMM` |
| 类目 | `departments` | 类目 code 列表；随站点变化，不按显示文案猜 code |
| 包含关键词 | `keywords` | 页面别名 `includeKeywords` |
| 排除关键词 | `excludeKeywords` | 多值分隔或数组口径以当前场景契约为准 |
| 新细分市场 | `withYearlyGrowth` | 页面布尔语义存在历史差异，以当前场景契约为准 |
| 市场周期 | `marketPeriod` | 枚举见下表；不限时省略或传空字符串 |

### 常用范围字段

| 中文含义 | 最小值 / 最大值 |
| --- | --- |
| 月搜索量 | `minSearches` / `maxSearches` |
| 搜索增长率 | `minSearchesCr` / `maxSearchesCr` |
| 同比增长值 | `minSearchMonthCv` / `maxSearchMonthCv` |
| 同比增长率 | `minSearchMonthCr` / `maxSearchMonthCr` |
| 近 3 个月增长值 | `minSearchNearlyCv` / `maxSearchNearlyCv` |
| 近 3 个月增长率 | `minSearchNearlyCr` / `maxSearchNearlyCr` |
| 商品数 | `minProducts` / `maxProducts` |
| 购买量 | `minPurchases` / `maxPurchases` |
| 购买率 | `minPurchaseRate` / `maxPurchaseRate` |
| 展示量 | `minImpressions` / `maxImpressions` |
| 点击量 | `minClicks` / `maxClicks` |
| SPR | `minSPR` / `maxSPR` |
| 标题密度 | `minTitleDensity` / `maxTitleDensity` |
| 货流值 | `minGoodsValue` / `maxGoodsValue` |
| 均价 | `minAvgPrice` / `maxAvgPrice` |
| 评分数 | `minRatings` / `maxRatings` |
| 评分值 | `minRating` / `maxRating` |
| PPC 竞价 | `minBid` / `maxBid` |
| 点击总占比 | `minAraClickRate` / `maxAraClickRate` |
| 转化总占比 | `minCvsShareRate` / `maxCvsShareRate` |
| 需供比 | `minSupplyDemandRatio` / `maxSupplyDemandRatio` |
| 单词个数 | `minWordCount` / `maxWordCount` |

页面别名归一规则：

| 页面字段 | 公共字段 |
| --- | --- |
| `minGrowth` / `maxGrowth` | `minSearchesCr` / `maxSearchesCr` |
| `minYearlyGrowth` / `maxYearlyGrowth` | `minSearchMonthCv` / `maxSearchMonthCv` |
| `minYearlyGrowthRate` / `maxYearlyGrowthRate` | `minSearchMonthCr` / `maxSearchMonthCr` |
| `minGrowthTrendMin` / `maxGrowthTrendMin` | `minSearchNearlyCv` / `maxSearchNearlyCv` |
| `minGrowthRateTrendMin` / `maxGrowthRateTrendMin` | `minSearchNearlyCr` / `maxSearchNearlyCr` |
| `minAvgReviews` / `maxAvgReviews` | `minRatings` / `maxRatings` |
| `minAvgRating` / `maxAvgRating` | `minRating` / `maxRating` |
| `minMonopolyClickRate` / `maxMonopolyClickRate` | `minAraClickRate` / `maxAraClickRate` |

展示量、SPR、点击量、标题密度和转化总占比由当前 `keyword-research` Web 场景直接接收；它们不应被转发到卖家精灵开放 API 的同名场景，两个接口契约不能混用。

### 分页与结果范围

- 默认传 `page=1`、`page_size=100`，映射为页面查询参数 `page=1`、`size=100`。
- 每个任务只保留当前页结果；默认任务返回第一页，最多 100 条，不自动请求或合并后续页。

### 范围校验

- 最小值和最大值都可省略；空值不传，不自动补 `0`。
- 允许只传一侧；两侧都有值时必须满足最小值不大于最大值。
- 整数字段拒绝小数和布尔值；小数字段只接受有限数值。
- `minWordCount` 只能是 `1—5` 的整数；`maxWordCount` 只能是 `1—9` 的整数。
- `minRating` 和 `maxRating` 都只能是 `0—5` 的数值。
- 百分比字段的传值口径由当前场景契约负责，不根据页面显示自行除以或乘以 `100`。

### 市场周期枚举

| 用户表达 | `marketPeriod` |
| --- | --- |
| 不限 | 省略或空字符串 |
| 一般性市场 | `N` |
| 1—3 月旺季 | `S1,S2,S3` |
| 4—6 月旺季 | `S4,S5,S6` |
| 7—9 月旺季 | `S7,S8,S9` |
| 10—12 月旺季 | `S10,S11,S12` |
| 持续增长市场 | `I` |
| 持续衰退市场 | `D` |

### 导出对齐

- 官方关键词选品文件的实际格式是 `.xlsx`。如果公共请求仍使用兼容值 `export_format=xls`，最终文件名、扩展名和 MIME 信息必须以工具真实返回为准。
- MCP 导出对齐官方主表的 28 列及顺序，只生成 `Keywords(数据行数)` 主工作表，冻结窗格为 `A2`；不生成官方文件中的 `Notes` 工作表。
- 不在官方 28 列中增加内部调试字段；百分比按页面 HTML 的数值口径输出且不二次换算，页面展示精度可能低于官网异步导出；站点货币、类目和页面 DOM 中的前 10 ASIN 保持官方展示口径。
- 若业务要求底层数值与官网导出逐位一致，必须使用官网异步导出文件，不能从已舍入的页面 HTML 恢复精度。
- 官方主列表导出是异步任务；受理成功不等于文件已生成，仍按普通任务的 `job_id/state/ready` 规则续查。

## `aba-research` ABA 数据选品

### 场景边界

- 用于按 Amazon Brand Analytics 周期，通过父/子 ASIN 或关键词筛选 ABA 关键词趋势。
- 与 `keyword-research`、`keyword-reverse`、`aba-reverse` 完全隔离；不得改投其他场景，也不调用 `aba-reverse` 的官方导出接口。
- 不支持页面六种推荐模式，用户未提供的筛选条件保持为空。
- Skill 中存在此场景不代表当前 MCP 已部署；执行前必须以 `seller_sprite_scenarios` 返回结果为准。

### 基础参数

| 中文含义 | 公共字段 | 规则 |
| --- | --- | --- |
| 站点 | 顶层 `site` | 支持 `US`、`UK`、`DE`、`FR`、`JP`、`CA`、`IT`、`ES`；美国站映射为 `market=COM` |
| 父/子 ASIN 或关键词 | `params.q` | 兼容 `keywordOrAsin`、`keyword`、`asin`；四者至少提供一个 |
| 周期 | 顶层 `period` | 周模式支持 `YYYY-MM-DD`、`YYYYMMDD`、`ara_YYYYMMDD` 或官网周标签；月模式支持 `YYYY-MM`、`YYYYMM`、`ara_YYYYMM` |
| 周期类型 | `params.reverseType` | `W` / `week` / `每周`，或 `M` / `month` / `每月`；省略时按周期格式推断，未提供周期则默认最近完整周 |
| 类目多选 | `params.departments` | 页面类目 code 数组或逗号分隔文本；不得根据自然语言类目名称猜 code |
| 排名对比周期 | `params.rankGrowthType` | `W1`、`W2`、`W3`、`W4`，默认 `W1` |
| 包含关键词 | `params.includeKeywords` | 字符串或列表；列表按逗号拼接 |
| 排除关键词 | `params.excludeKeywords` | 字符串或列表；列表按逗号拼接 |
| 排名变化量 | `params.rankGrowthValue` | 有限数值 |

### 排序

- `params.orderField` 支持：`searchfrequencyrank`、`searches`、`rankGrowthValue`、`rankGrowthRate`、`impressions`、`clicks`、`monopolyClickRate`、`conversionRate`、`cprExact`、`titleDensityExact`。
- `params.orderDesc` 控制倒序，默认 `false`；也兼容对象形式 `params.order={"field": "...", "desc": true}`。

### 搜索结果范围筛选

| 中文含义 | 最小值 / 最大值 |
| --- | --- |
| 搜索量 | `minSearches` / `maxSearches` |
| ABA 排名 | `minSearchRank` / `maxSearchRank` |
| 排名变化率 | `minRankGrowthRate` / `maxRankGrowthRate` |
| 展示量 | `minImpressions` / `maxImpressions` |
| 点击量 | `minClicks` / `maxClicks` |
| 点击集中度 | `minMonopolyClickRate` / `maxMonopolyClickRate` |
| 转化率 | `minConversionRate` / `maxConversionRate` |
| SPR | `minSPR` / `maxSPR` |
| 标题密度 | `minTitleDensity` / `maxTitleDensity` |
| 单词个数 | `minWordCount` / `maxWordCount` |

- 搜索量、ABA 排名、展示量、点击量、SPR、标题密度和单词个数只接受整数。
- 变化率、点击集中度和转化率接受有限数值，并保持页面原始百分比口径，例如页面输入 `12.5` 就传 `12.5`，不自动除以 `100`。
- 最小值和最大值都可省略；两侧都有值时最小值不能大于最大值。

### 分页与导出

- 后端固定提交一次 `POST /v3/api/aba-research`，强制使用 `page=1`、`size=100`；调用方传入的 `page`、`size` 或顶层 `page_size` 不会改变这一约束。
- 只保存第一页实际返回的数据，不请求或合并后续页；`row_count` 等于第一页 `data.items` 的实际数量。
- 不调用官网导出接口，不消耗官网有限导出次数；根据查询 JSON 在本地生成 `ABAKeywordTrend-{站点}-{周期}.xlsx`。
- 本地工作簿对齐官方 19 列业务主表、橙色表头、冻结窗格、列宽和数字格式；不生成官网 `Notes` 页及二维码图片。

## `association-traffic` 关联流量

### 场景边界

- 用于输入父体或子体 ASIN，查询全部变体带来的关联流量商品及关联类型。
- 与 `traffic-source` 不同：`association-traffic` 关注输入 ASIN 的关联商品集合；`traffic-source` 查询关键词或 ASIN 的流量来源。
- 点击查询后的页面弹窗固定选择“用全部变体查询”；公共参数不提供 `queryVariations=false`。
- browser-route 会逐个填写 ASIN 并按回车，页面计数必须达到输入数量后才点击“立即查询”和“用全部变体查询”。

### 输入与分页

| 中文含义 | 公共字段 | 规则 |
| --- | --- | --- |
| ASIN | `asins`，兼容单个 `asin` | 1—20 个；每个为 10 位字母数字；支持数组、逗号、换行、制表符和 TXT/Excel 按列粘贴 |
| 关联类型 | `relations` | 可省略；省略表示全部类型；可传下表 code 数组或分隔文本 |
| 排序字段 | `orderField` | 默认 `createdTime`；可用 `relationCount` |
| 倒序 | `desc` | 默认 `true` |
| 每页数量 | 顶层 `page_size` | 固定按公共默认 `100` 执行；只返回第一页，最多 100 条 |

若主接口返回 `pagerDto.size=20` 且实际只有 20 条数据，视为游客限制响应。browser-route 会恢复登录态并重试一次；登录成功后仍只获取第一页 100 条。

### 关联类型枚举

| `relations` code | 页面名称 | 类型 |
| --- | --- | --- |
| `VAV` | 看了又看 | 自然关联 |
| `CSI` | 相似产品 | 自然关联 |
| `AVP` | 看了还看 | 自然关联 |
| `BAV` | 看了却买 | 自然关联 |
| `MIB` | 捆绑销售 | 自然关联 |
| `FBT` | 组合购买 | 自然关联 |
| `MIE` | 更多相关 | 自然关联 |
| `BAB` | 买了又买 | 自然关联 |
| `COB` | 品牌推荐 | 自然关联 |
| `SP` | 商品广告 | 广告关联 |
| `FSA` | 四星产品 | 广告关联 |
| `BCA` | 品牌广告 | 广告关联 |

### 导出对齐

- MCP 导出对齐官网关联流量主表的 56 列、顺序、币种表头、百分比、关系类型中文名、列宽和超链接。
- 工作表名复现官网批量导出的 `Related-首个ASIN-batch(输入数)(31` 可见格式。
- 本地工作簿只生成业务主表，不生成官网导出中的 `Notes` 页。
- 官方参考文件为 `.xlsx`；若请求仍使用兼容值 `export_format=xls`，以工具返回的真实文件名和格式为准。

## `aba-reverse` 出单词反查

### 场景边界

- 用于按 Amazon Brand Analytics 周期，从父体或子体 ASIN 反查出单关键词。
- 与 `keyword-reverse` 隔离：`aba-reverse` 下载 ABA 官方 Excel，`keyword-reverse` 继续使用关键词反查接口和本地导出逻辑。
- Skill 中存在此场景不代表当前 MCP 已部署；执行前必须以 `seller_sprite_scenarios` 返回结果为准。

### 输入与周期

| 中文含义 | 公共字段 | 规则 |
| --- | --- | --- |
| 站点 | 顶层 `site` | 默认 `US` |
| ASIN / 产品链接 | `params.asin` 或 `params.asins` | 1—20 个；支持父体/子体 ASIN、Amazon `/dp/`、`/gp/product/`、`/product/` 链接；支持数组、空格、中英文逗号、分号、换行和制表符；按首次出现顺序去重 |
| 周期 | 顶层 `period` | 可省略，默认最近完整周。每周可传 `YYYY-MM-DD`、`YYYYMMDD`、`ara_YYYYMMDD` 或官网周标签；日期为该周结束日。每月传 `YYYY-MM`、`YYYYMM` 或 `ara_YYYYMM` |
| 周期类型 | `params.reverseType` | 可省略；未提供周期时默认 `W`。显式值支持 `W` / `week` / `weekly` / `每周`，或 `M` / `month` / `monthly` / `每月`；仅省略类型时按 `period` 格式推断 |
| 排序字段 | `params.orderField` | 默认 `searchRank` |
| 倒序 | `params.orderDesc` | 默认 `false` |
| 转化类型 | `params.conversionType` | 可省略 |
| 加载变体 | `params.loadVariations` | 默认 `false` |

未提供周期时，周模式自动选取当前日期之前最近一个已经完整结束的周六；周六当天仍选择上一周，避免使用尚未结束的当周。周模式会自动使用该周结束日前的上一个完整月份作为 `monthlyTable`；月模式的 `table` 与 `monthlyTable` 使用同一月份。

### 调用示例

```text
seller_sprite_run(
  scenario="aba-reverse",
  site="US",
  period="2026-07-18",
  params={"asin": "B00000JBNX", "reverseType": "W"},
  export_format="xls"
)
```

### 导出规则

- 只支持 `export_format=xls` 或 `xlsx`，两者最终都以官网实际返回的 `.xlsx` 文件为准。
- 后端直接调用官网导出接口，官方 XLSX 原样保存；接口返回多少条就保留多少条，不分页、不截取、不解析、不重建。
- 官方列名、顺序、样式、工作表和 `Notes` 页全部保留。
- 因工作簿不做本地解析，任务结果的 `row_count=0` 和 `data=[]` 不表示没有数据；应以 `export.filename`、`export.url` 或 `export.path` 指向的文件为准。

## `branddb` 全球商标库

### 输入与筛选

| 中文含义 | `params` 字段 | 规则 |
| --- | --- | --- |
| 搜索文本 | `text` | 必填；品牌名称、所有人或注册号 |
| 商标特征 | `feature` | 可省略，默认空字符串 |
| 注册局 | `office` | 单值、数组或逗号分隔，多值去空去重 |
| 品牌名称 | `brandName` | 单值、数组或逗号分隔 |
| 状态 | `status` | `Registered`、`Expired`、`Ended`、`Pending`、`Unknown`；也支持已注册、已过期、已结束、待审核、未知 |
| 申请人 | `applicant` | 单值、数组或逗号分隔 |
| 尼斯分类 | `niceClass` | 1—45 的整数列表 |
| 申请年份 | `applicationYear` | 四位年份列表 |
| 到期年份 | `expiryYear` | 四位年份列表 |
| 倒序 | `desc` | 默认 `true`；显式 `false` 会保留 |
| 排序字段 | `orderField` | 默认空字符串 |
| 页码 / 页面数量 | `pageNum` / `pageSize` | 默认 `1` / `20`，与官网导出请求一致 |
| 指定记录 | `ids` | 正整数 ID 列表；默认空数组表示按当前筛选导出 |

### 导出规则

- 仅支持 `browser-route` 和 `export_format=xls/xlsx`；先打开 `/v3/branddb` 建立登录态，再通过同一浏览器上下文直接 `POST /v3/api/branddb/export-syn`，不点击页面导出按钮。
- 单次接口等待上限为 120 秒。请求一旦发出，登录失效、验证码、401/403、超时或结果不明均直接失败，不自动重新发送，也不换账号故障转移。
- 官方 XLSX 的文件名和字节原样保留，不分页、不解析、不重建；`row_count=0`、`data=[]` 时应以导出文件为准。
- 进程崩溃恢复仍沿用通用持久队列的 at-least-once 模型；第三方接口无幂等键，因此不承诺严格 exactly-once。

## `product-research` 重点参数

### 推荐模式

`recommendationMode` 可用值：

`低价长尾选品`、`研发新品榜`、`潜力单变体`、`销量飙升`、`潜力市场`、`未被满足的市场`、`不压库存的市场`、`投机市场`、`高需求低要求市场`、`全品类铺货`、`精品铺货`、`低价商品`、`新手推荐`

推荐模式会展开为一组筛选条件；如果用户同时显式给出同名筛选条件，以用户条件为准。

### 常用中文字段

| 中文含义 | `params` 字段 |
| --- | --- |
| 类目 | `nodeIdPaths` / `node` / `category` / `nodeIdPath` |
| 月销量 | `minSales` / `maxSales` |
| 月销售额 | `minAmount` / `maxAmount` |
| 子体销量 | `minAmzUnit` / `maxAmzUnit` |
| 月销量增长率 | `minTotalUnitsGrowth` / `maxTotalUnitsGrowth` |
| 大类 BSR | `minRanking` / `maxRanking` |
| 小类 BSR | `minSubBsrRank` / `maxSubBsrRank` |
| BSR 增长数 / 增长率 | `minRankingCv` / `maxRankingCv`、`minRankingCr` / `maxRankingCr` |
| 变体数 | `minVariations` / `maxVariations` |
| Q&A | `minQuestions` / `maxQuestions` |
| 月评新增 / 留评率 | `minReviewsGrouth` / `maxReviewsGrouth`、`minReviewsRate` / `maxReviewsRate` |
| 毛利率 / LQS | `minProfit` / `maxProfit`、`lqsFrom` / `lqsTo` |
| 价格 | `minPrice` / `maxPrice` |
| 评分数 / 评分 | `minReviews` / `maxReviews`、`minReviewRating` / `maxReviewRating` |
| FBA 运费 | `minFba` / `maxFba` |
| 上架月数 | `putawayMonth` |
| 包装重量 | `minWeights` / `maxWeights`，配合 `weightUnit` |
| 买家运费 | `minDeliveryPrice` / `maxDeliveryPrice` |
| 卖家数 | `minSellers` / `maxSellers` |
| 卖家所属地 | `sellerNationList` |
| 包含 / 排除品牌 | `includeBrands` / `excludeBrands` |
| 包含 / 排除卖家 | `includeSellers` / `excludeSellers` |
| 包含 / 排除关键词 | `keywords` / `outOfKeywords` |

### 枚举参数

- `productTags`：`BestSeller`、`AmazonChoice`、`NewRelease`、`A+`、`NonA+`
- `sellerTypes`：`AMZ`、`FBA`、`FBM`
- `pkgDimensionTypeList`：`SS`、`LS`、`SB`、`LB`、`ELO`、`EL5O`、`EL7O`、`EL15O`、`O`
- `sellerNationList`：如 `CN`、`US`、`JP`、`GB`、`DE`
- `video`：`Y` / `N`
- `lowPrice`：`Y` / `N`
- `smallAndLight`：常用 `N` 或 `lowPrice`
- `filterSub`：是否只看所选子类目排名
- `matchType`：`0` 模糊匹配，`1` 词组匹配，`2` 精准匹配

关于 `A+` / `NonA+`：

- 仅勾选 A+：传 `"A+"`
- 仅勾选不含 A+：传 `"NonA+"`
- 两者都勾选或都不勾选：都不要传

### 官方别名

如果同时给了官方别名和内部字段，以内部字段为准。

| 官方别名 | 内部字段 |
| --- | --- |
| `minUnits` / `maxUnits` | `minSales` / `maxSales` |
| `minRevenue` / `maxRevenue` | `minAmount` / `maxAmount` |
| `minUnitsCr` / `maxUnitsCr` | `minTotalUnitsGrowth` / `maxTotalUnitsGrowth` |
| `minRatings` / `maxRatings` | `minReviews` / `maxReviews` |
| `minRatingsCv` / `maxRatingsCv` | `minReviewsGrouth` / `maxReviewsGrouth` |
| `minStar` / `maxStar` | `minReviewRating` / `maxReviewRating` |
| `availableMonth` | `putawayMonth` |
| `fulfillment` | `sellerTypes` |
| `badgeBS=true` | 向 `productTags` 添加 `BestSeller` |
| `badgeAC=true` | 向 `productTags` 添加 `AmazonChoice` |
| `badgeNR=true` | `productTags=["NewRelease"]` |
| `variation` | `maxVariations` |
| `minBsr` / `maxBsr` | `minRanking` / `maxRanking` |
| `minBsrCv` / `maxBsrCv` | `minRankingCv` / `maxRankingCv` |
| `minBsrCr` / `maxBsrCr` | `minRankingCr` / `maxRankingCr` |
| `minLqs` / `maxLqs` | `lqsFrom` / `lqsTo` |
| `dimensionType` | `pkgDimensionTypeList` |
| `sellerNation` | `sellerNationList` |
| `excludeKeywords` | `outOfKeywords` |

## `market-research` 常用字段

| 中文含义 | `params` 字段 |
| --- | --- |
| 类目关键词搜索 | `departmentKeyword` / `category` |
| 精确类目节点 | `node` / `nodeIdPath` |
| 样本数量 | `sampleNumber` |
| 头部 Listing 数量 | `topn` / `topNSelect` |
| 新品定义月份 | `newReleaseNum` / `newReleaseMonths` / `newReleaseNumSelect` |
| 月均销量 | `minAvgSales` / `maxAvgSales` |
| 平均 BSR | `minAvgBsr` / `maxAvgBsr` |
| 平均重量 | `minAvgWeight` / `maxAvgWeight` |
| 头部 Listing 平均 BSR | `minHeadListingAvgBsr` / `maxHeadListingAvgBsr` |
| 商品总数 | `minTotalProducts` / `maxTotalProducts` |
| 月均销售额 | `minAvgRevenue` / `maxAvgRevenue` |
| 平均价格 | `minAvgPrice` / `maxAvgPrice` |
| 平均体积 | `minAvgVolume` / `maxAvgVolume` |
| 头部 Listing 月均销量 | `minHeadListingAvgSales` / `maxHeadListingAvgSales` |
| 平均评分数 / 平均星级 | `minAvgReviews` / `maxAvgReviews`、`minAvgRating` / `maxAvgRating` |
| 平均毛利率 | `minAvgProfit` / `maxAvgProfit` |
| 头部 Listing 月均销售额 | `minHeadListingAvgRevenue` / `maxHeadListingAvgRevenue` |
| 品牌数量 | `minBrands` / `maxBrands` |
| 商品集中度 | `minHeadListingProductCrn` / `maxHeadListingProductCrn` |
| A+ 数量占比 | `minEbcRatio` / `maxEbcRatio` |
| Amazon 自营占比 | `minAmzRatio` / `maxAmzRatio` |
| 卖家数量 | `minSellers` / `maxSellers` |
| 品牌集中度 | `minHeadListingBrandCrn` / `maxHeadListingBrandCrn` |
| FBA 占比 | `minFbaRatio` / `maxFbaRatio` |
| 卖家所属地 | `sellerNations` |
| 平均卖家数 | `minAvgSellers` / `maxAvgSellers` |
| 卖家集中度 | `minHeadListingSellerCrn` / `maxHeadListingSellerCrn` |
| FBM 占比 | `minFbmRatio` / `maxFbmRatio` |
| 新品数量占比 | `minNewRatio` / `maxNewRatio` |
| 新品平均价格 | `minNewAvgPrice` / `maxNewAvgPrice` |
| 新品月均销售额 | `minNewAvgRevenue` / `maxNewAvgRevenue` |
| 新品数量 | `minNewCount` / `maxNewCount` |
| 新品平均星级 / 评分数 / 月均销量 | `minNewAvgRating` / `maxNewAvgRating`、`minNewAvgReviews` / `maxNewAvgReviews`、`minNewAvgSales` / `maxNewAvgSales` |

## 类目规则

### `product-research` / `competitor-lookup`

- 可以直接传自然语言类目，如 `bath`、`bed frames`、`Home & Kitchen:Bedding:Bed Skirts`
- 也可以直接传数值节点路径，如 `1055398:1063236`
- 后端会通过卖家精灵类目接口解析类目文本
- 如果只返回一个候选，后端会直接继续查询
- 如果返回多个候选且其中有一个和用户输入完全匹配，后端会优先使用完全匹配项
- 如果返回多个候选但无法唯一确认，必须停下来让用户选，不要猜
- `product-research` 在用户确认类目后，优先传 `nodeIdPaths: ["..."]`，不要丢掉类目条件

### `market-research`

- 优先用 `departmentKeyword` 做类目 / 市场关键词搜索
- `category` 只是 `departmentKeyword` 的别名
- 只有用户明确给出 SellerSprite 节点路径并要求精确节点筛选时，才使用 `node` / `nodeIdPath`
