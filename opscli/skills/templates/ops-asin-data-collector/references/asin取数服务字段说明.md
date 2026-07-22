# live-data 字段取数映射

本文用于约束 Skill 在 `opscli asin-data live-data --return-mode ai_ready` 返回中，如何把用户自然语言字段需求映射到稳定 `data_scope`、`source_key` 和字段候选。字段级判断必须优先读取 `items[].datasets[].source_key`，不要只依赖 xlsx sheet 名称。

## 1. 取数范围选择

| 用户需求 | 推荐 data_scope | 必读 source_key | 说明 |
| --- | --- | --- | --- |
| 标题、五点、品牌、类目、SKU、Listing 状态、主图、副图、search terms | `listing_basic`；同时需要爬虫证据时用 `basic` | `listing_basic` | 这些是刊登后台事实，优先取北极星刊登接口数据。 |
| A+ 图片、A+ 描述、QA、评论、Review List、商品详情、页面评分、页面排名、当前 Amazon 页面快照 | `basic` | `crawler_details`；语义 sheet 存在时读取 `product_detail`、`qa`、`reviews` | 这些来自爬虫详情或爬虫拆分后的语义视图。 |
| 销量、流量、转化、广告搜索词、活动、库存周转 | `bi` | `sales_traffic`、`sp_search_term`、`deals`、`turnover_inventory` | 必须提供 `sales_start` 和 `sales_end`。 |
| 历史卖家精灵关键词、竞品、Rufus 文件 | 不用 `live-data` | 不适用 | 改用 `fetch-file`。 |

快速性原则：只取用户问题需要的最小 `data_scope`。只要用户没有要求 BI，不要使用 `all`；只要用户只问刊登后台字段，不要使用 `basic`。

## 2. 稳定 source_key 与兼容 sheet

| source_key | 兼容 sheet 名 | 主要用途 |
| --- | --- | --- |
| `listing_basic` | `基础汇总`、`刊登数据` | 刊登后台基础字段、标题、五点、图片、品牌、类目、SKU、状态、关键词。 |
| `crawler_details` | `爬虫数据` | Amazon 页面快照、A+、QA、评论列表、商品详情、评分、排名、页面价格。 |
| `product_detail` | `商品详情` | `crawler_details.product_details` 拆分视图；存在时可直接读取商品详情属性。 |
| `bullets` | `五点描述` | 兼容旧拆分视图；存在时可作为五点明细，但主来源仍是 `listing_basic`。 |
| `image_links` | `图片链接` | 兼容旧拆分视图；存在时可作为图片链接明细。 |
| `qa` | `QA` | 兼容旧拆分视图；存在时可直接读取问答。 |
| `reviews` | `评论` | 兼容旧拆分视图；存在时可直接读取评论。 |

解析优先级：

1. 先按 `source_key` 找数据集。
2. 再用 `sheet_name` 做兼容定位。
3. `preview_rows` 只用于快速判断字段是否存在；需要完整数据时读取 `artifacts[].uri` 或 `local_path` 对应 xlsx。

## 3. 字段映射表

| 用户说法 / 字段意图 | 推荐 data_scope | 首选 source_key | 字段候选 | 降级 / 备注 |
| --- | --- | --- | --- | --- |
| 标题、商品标题、Listing 标题、title | `listing_basic` | `listing_basic` | `商品标题`、`产品标题`、`item_name.value`、`title` | 只有用户明确要 Amazon 页面快照标题时，才降级读 `crawler_details.listing`、`标题`、`f_product_name`。 |
| 五点、五点描述、卖点、bullet points | `listing_basic` | `listing_basic` | `五点描述`、`bullet_point.value`、`bullet_point.value1`、`bullet_point.value2`、`bullet_point.value3`、`bullet_point.value4`、`bullet_point.value5` | `bullets` sheet 存在时可补充明细；不要用爬虫五点覆盖刊登五点。 |
| 品牌、brand | `listing_basic` | `listing_basic` | `品牌`、`brand`、`brand.value` | 页面展示品牌对比时可同时读 `crawler_details.brand`。 |
| 类目、category | `listing_basic` | `listing_basic` | `类目`、`category`、`product_type.value`、`item_type_keyword.value` | 页面排名类目读 `crawler_details.major_name`、`subclass_name`。 |
| 主图、main image | `listing_basic` | `listing_basic` | `主图链接`、`主图`、`main_image`、`main_image_url` | 页面快照图可降级读 `crawler_details.image`。 |
| 副图、附图、图片链接、image links | `listing_basic` | `listing_basic` | `其他附图链接`、`副图1`、`副图2`、`副图3`、`副图4`、`副图5`、`other_images` | `image_links` sheet 存在时可补充；页面快照图读 `crawler_details.subplot`、`subplots`。 |
| Search Terms、关键词搜索、后台关键词 | `listing_basic` | `listing_basic` | `关键词搜索`、`generic_keyword.value`、`search_terms` | 用户问广告搜索词时不要用此字段，改读 `bi.sp_search_term`。 |
| A+ 图片、A+ image、a plus image | `basic` | `crawler_details` | `a_image`、`f_a_image`、`A+图片`、`a_plus_images`、`aplus_images` | 这是爬虫详情字段，不在 `listing_basic` 中强取。 |
| A+ 描述、A+ 文案、A+ description | `basic` | `crawler_details` | `a_description`、`f_a_description`、`A+文案`、`a_plus_description`、`aplus_description` | 需要完整模块内容时读 xlsx，不只看 preview。 |
| QA、Q&A、问答 | `basic` | `crawler_details`；存在语义视图时读 `qa` | `qa`、`f_qa`、`qa_list`、`questions_answers`、`QA` | `qa` source_key 存在时优先使用该拆分视图，否则读 `crawler_details` 原字段。 |
| 评论、review、review list、review_List、Review List | `basic` | `crawler_details`；存在语义视图时读 `reviews` | `review_list`、`f_review_list`、`reviews`、`reviewList`、`评论列表` | `reviews` source_key 存在时优先使用该拆分视图，否则读 `crawler_details` 原字段。 |
| 商品详情、product details、规格参数 | `basic` | `crawler_details`；存在语义视图时读 `product_detail` | `product_details`、`f_product_details`、`产品详情`、`Product Details` | 商品详情来自页面爬虫，不等同于刊登后台属性。 |
| 评分、星级、rating | `basic` | `crawler_details` | `rating`、`评分`、`星级` | Listing 后台不存在实时页面评分时，不从 `listing_basic` 推断。 |
| 评论数、rating count、review count | `basic` | `crawler_details` | `rating_count`、`review_count`、`评论数` | 与评论正文分开处理。 |
| 价格、当前售价、页面价格 | `basic` | `crawler_details` | `price`、`unit_price`、`价格`、`页面价格` | 用户问后台配置价格时改读 `listing_basic` 的价格字段。 |
| 大类排名、小类排名、BSR | `basic` | `crawler_details` | `major_rank`、`subclass_rank`、`大类排名`、`小类排名`、`major_name`、`subclass_name` | 排名是页面快照事实。 |

## 4. 冲突处理规则

| 冲突场景 | 处理规则 |
| --- | --- |
| `listing_basic` 和 `crawler_details` 都有标题、五点、图片 | Listing 可控内容默认以 `listing_basic` 为准；`crawler_details` 只作为 Amazon 页面展示快照或一致性对比证据。 |
| 用户问“当前页面显示的标题/五点/图片” | 读 `crawler_details`，并在结论中标注这是页面快照。 |
| 用户问“后台刊登标题/五点/图片”或未指定“页面显示” | 读 `listing_basic`。 |
| `qa` / `reviews` 语义 source 和 `crawler_details` 原字段同时存在 | 优先读语义 source，必要时回看 `crawler_details` 原字段补充。 |
| 某 source `quality.empty=true` 或诊断包含 `EMPTY_DATASET` | 表示该 source 无数据，不当作命令失败；结论中标注缺失。 |
| 诊断包含 `SOURCE_ERROR` 或 `items[].status!="success"` | 视为失败或部分失败，不要把缺失字段解释为业务事实。 |

## 5. Skill 识别示例

| 用户表达 | 应选择的命令参数 | 读取规则 |
| --- | --- | --- |
| “帮我取这个 ASIN 的标题和五点” | `live-data --data-scope listing_basic` | 读取 `listing_basic` 的标题和五点字段。 |
| “标题五点、主图副图都拿一下” | `live-data --data-scope listing_basic` | 读取 `listing_basic`，图片只读刊登后台图。 |
| “取标题五点，再取 A+、QA、Review List” | `live-data --data-scope basic` | 标题五点读 `listing_basic`；A+、QA、Review List 读 `crawler_details` 或语义 source。 |
| “看看当前 Amazon 页面展示的标题和五点跟后台是否一致” | `live-data --data-scope basic` | `listing_basic` 与 `crawler_details` 同字段对比。 |
| “给我销量、流量、广告搜索词” | `live-data --data-scope bi --sales-start ... --sales-end ...` | 按 BI source_key 分开读取。 |

## 6. 输出约束

- 对外回答字段来源时，使用 `source_key` 描述来源，例如“标题来自 `listing_basic`，A+ 来自 `crawler_details`”。
- 不要把 `crawler_details` 的页面标题/五点直接当成后台刊登标题/五点。
- 不要把 `listing_basic` 的后台关键词当成广告搜索词。
- 不要只根据 `preview_rows` 判断“没有更多数据”；完整内容以 xlsx artifact 为准。
- 如果用户要求文件交付，首选返回 `items[].artifacts[].uri` 的 OSS xlsx 地址。
