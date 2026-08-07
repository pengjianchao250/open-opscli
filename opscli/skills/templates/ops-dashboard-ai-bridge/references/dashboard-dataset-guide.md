# Dashboard Dataset Guide

本文件整理“运营系统数据集”导航页中的数据集用途、最小粒度和推荐图表，用于建图前理解业务语义。执行规则见 `dashboard-operation-standards.md`，工具参数见 `dashboard-tool-contract.md`。

## 使用边界

- 本指南只生成语义候选，不代表当前账号有权使用，也不证明数据集或字段仍然存在。
- 数据集名称、ID 和完整字段必须来自本轮 `dashboard_session_search_datasets` 与 `dashboard_session_get_dataset_fields` 结果；未返回的候选不可使用。
- “粒度线索”用于比较候选和规划字段角色，不可据此手写字段 key、ID 或类型。
- 推荐 `viewType` 只提供选型候选。最终图表必须同时符合用户问题、实时字段和 `dashboard-operation-standards.md` 的图表特点，并纳入固定 5 图计划。
- 导航页中“待本表补充”及缺少数据集名称或推荐图表的占位记录不进入候选；用途说明为空时只保留表内已有的名称、对应功能、粒度和图表信息，不自行补写业务含义。

## 匹配流程

1. 从用户目标识别业务域、分析对象、比较方式和期望明细层级。
2. 用下表筛出 1 到 3 个中文名称候选，比较用途与粒度线索，不按关键词相似度直接定表。
3. 搜索当前页面真实数据集；候选未返回时舍弃，多个结果都会改变结论时让用户选择。
4. 读取唯一候选的完整字段目录，将字段标题、说明和真实角色与“字段关注”逐项对齐。
5. 按用户意图规划 5 个不同问题，再从候选 `viewType` 和完整图表特点中选型；不照搬数据集推荐组成固定套图。

## 字段规划

- 粒度中的部门、渠道、国家、SKU、ASIN、仓库、广告活动等是维度线索；只选完整字段目录中真实存在且符合用户问题的字段。
- 订单号、包裹号、活动 ID、关键词 ID、事件 ID 等记录标识优先用于明细定位，不作为连续度量。
- “字段关注”描述业务语义，不等于字段名。度量必须从本轮目录按标题、说明和角色匹配，多义时询问。
- 关系映射、清单和逐笔记录类数据集优先考虑明细表或透视表；趋势、构成、漏斗和进度仍需真实字段满足对应图表条件。
- 综合数据集适合一套图同时覆盖多个经营问题；专题明细数据集适合深入单一环节。一个创建批次无法由同一真实数据集支撑 5 张有效图时停止或询问。

## 导航页图表映射

| 导航页名称 | 当前候选 `viewType` | 选择提示 |
| --- | --- | --- |
| 交叉表 | `crosstab_table` | 需要行列交叉比较 |
| 指标趋势图 | `metric_trend` | 关键值与有序变化同时成立 |
| 基础柱状图 / 基础条形图 | `bar_basic` / `hbar_basic` | 按标签长度和类别数量选择方向 |
| 堆叠柱状图 | `bar_stacked` | 构成系列可相加且单位一致 |
| 百分比堆叠柱状图 / 条形图 | `bar_stacked_percent` / `hbar_stacked_percent` | 关注比例结构 |
| 基础折线图 | `line_basic` | 横轴连续或有序 |
| 柱线组合图 | `combo_bar_line` | 规模与比率或趋势联合比较 |
| 指标卡 | `indicator` | 只回答当前关键值 |
| 明细表 | `detail_table` | 查看记录、实体或精确值 |
| 透视表 | `pivot_table` | 按层级汇总展开 |
| 漏斗图 | `funnel_basic` | 存在同一群体的有序阶段 |
| 进度图 | `progress_chart` | 存在真实目标、阈值、预算、SLA 或可验证阶段 |

## 销售分析

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| 即时综合数据集 | 日常经营总览或 ASIN 诊断；同时关注销售、广告、流量、转化和库存 | 部门 + 渠道 + 渠道 SKU + 天 | `crosstab_table`、`metric_trend` |
| 即时销售数据集 | 实时销量波动、短期追踪、活动或投放即时效果；关注销量与销售表现 | 部门 + 渠道 + 渠道 SKU + 天 | `crosstab_table`、`metric_trend` |
| 发货数据集 | 按发货表现复盘长周期业绩和销售规模；关注发货销量与销售表现 | 部门 + 渠道 + 渠道 SKU + 天 | `crosstab_table`、`metric_trend` |
| 销售区域分布 | 比较国家、区域和渠道，识别核心与薄弱市场；关注区域销售贡献 | 天 + 部门 + 渠道 + 订单号 | `bar_basic`、`hbar_basic`、`hbar_stacked_percent` |
| Listing管理数据集 | 查看 Listing 绑定关系 | 以实时字段目录为准 | `detail_table` |

## 广告分析

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| 广告费数据集 | 汇总多平台广告支出并关联整体销售；关注花费、曝光、点击、广告销售和总销售 | 部门 + 渠道 + 渠道 SKU + 天 | `indicator`、`metric_trend` |
| 广告类型花费数据集 | 比较 SP、SD、SB、SBV 的花费和结构 | 部门 + 渠道 + 渠道 SKU + 天 + 广告类型 | `bar_stacked`、`bar_stacked_percent` |
| SP广告数据集 | 深入 SP 广告花费、点击、订单、销售与转化 | 部门 + 渠道 + 渠道 SKU + 天 | `pivot_table`、`funnel_basic` |
| SD广告数据集 | 深入 SD 触达、再营销、视频、加购、订单和销售 | 部门 + 渠道 + 渠道 SKU + 天 | `pivot_table`、`funnel_basic` |
| SB广告数据集 | 深入 SB/SBV 品牌曝光、引流、视频和转化 | 部门 + 广告活动 ID + 天 | `pivot_table`、`funnel_basic` |
| SP+SD广告数据集 | 在统一字段结构下比较 SP 与 SD 效率 | 部门 + 渠道 + 渠道 SKU + 天 + 广告类型 | `pivot_table`、`bar_stacked_percent` |
| SP+SD+SB广告数据集 | 汇总 SP、SD、SB，分析全盘广告与类型结构 | 渠道 + 广告活动 ID + 天 + 广告类型 | `pivot_table`、`bar_stacked_percent` |
| SP关键词数据集 / SB关键词数据集 | 识别高效、低效或高花费无转化关键词；关注关键词及广告表现 | 天 + 渠道 + 广告组 ID + 广告活动 ID + 关键词 ID | `detail_table`、`hbar_basic` |
| SP搜索词数据集 / SB搜索词数据集 | 分析消费者实际搜索词并发现扩词机会 | 天 + 渠道 + 广告组 ID + 广告活动 ID + 搜索词 | `detail_table`、`hbar_basic` |
| SP投放词数据集 / SD投放词数据集 | 比较关键词、商品或受众定向效果 | 天 + 渠道 + 广告组 ID + 广告活动 ID + 投放目标 ID | `detail_table`、`hbar_basic` |
| SP广告位数据集 | 比较不同广告位表现，辅助调整溢价和预算 | 天 + 渠道 + 广告活动 ID + 广告位 | `detail_table`、`bar_stacked_percent` |
| SBV效果追踪 | 跟踪品牌视频素材、投放词和转化阶段表现 | 渠道 + 广告活动 ID + 天 | `funnel_basic`、`detail_table` |
| SP广告预算数据集 / SD广告预算数据集 / SB广告预算数据集 | 识别单类广告预算不足、利用率偏低或消耗异常 | 广告活动 | `detail_table`、`hbar_basic` |
| SP+SD+SB广告预算数据集 | 比较三类广告预算分配和使用效率 | 广告活动 | `detail_table`、`bar_stacked` |

## 客服与平台报告

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| 客诉分析数据集 | 汇总客户投诉，定位高频问题、重点 SKU 和产品改进项 | 客诉编号 + 渠道 SKU | `detail_table`、`hbar_basic` |
| 亚马逊Feedback数据集 | 监控店铺 Feedback 和负面服务风险，不用于商品评论分析 | 明细 ID + 订单号 + 渠道 SKU | `detail_table`、`bar_basic` |
| 亚马逊店铺绩效数据集 | 监控账户状况、履约和合规绩效；关注绩效类型、状态与比率 | 店铺 + 站点 + 绩效类型 + 报告周期 | `indicator`、`progress_chart` |
| 亚马逊目录绩效 | 发现 Listing 目录曝光、表现和内容质量问题 | 国家 + 平台 + ASIN + 报告周期 | `funnel_basic`、`hbar_basic` |
| 亚马逊搜索词绩效 | 分析搜索词曝光、点击和购买表现 | 国家 + 平台 + ASIN + 搜索词 + 报告周期 | `detail_table`、`hbar_basic` |
| 亚马逊ABA数据集 | 查看市场搜索词及其周期表现 | 国家 + 搜索词 + 报告周期 | `detail_table` |
| VC报告【Manufacturing】 / VC报告【Sourcing】 | 分别查看 VC 制造或采购寻源运营指标 | 部门 + 渠道 + ASIN + 报告周期 | `detail_table` |

## 运营监控

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| ASIN运营事件数据集 | 查询 ASIN 运营事件，解释指标异动并复盘事件效果 | 平台 + 国家 + ASIN + 事件变更时间 + 事件变更 ID | `detail_table`、`metric_trend` |
| ASNI每日趋势数据集 | 查看 ASIN 监控指标的每日变化 | 平台 + 国家 + ASIN + 天 | `metric_trend`、`line_basic` |
| 运营事件清单数据集 | 查询变动事件及类型清单 | 变动事件 ID | `detail_table` |
| ASNI最新快照数据集 | 查看 ASIN 当前监控状态 | 平台 + 国家 + ASIN | `detail_table`、`indicator` |

导航页同时存在 `ASIN` 与 `ASNI` 拼写，搜索时保留原名并以本轮真实候选为准，不自行纠正技术标识。

## 物流与市场

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| 自发货-物流费用账单 | 核算物流费用，识别费用结构和异常账单 | 天 + 订单号 + 包裹号 | `detail_table`、`bar_stacked` |
| 海运在途SKU明细 | 查看海运在途 SKU 与运输状态，判断补货和断货风险 | 发货单号 + 柜号 + 公司 SKU + 最终目的仓 | `detail_table`、`progress_chart` |
| 自发货包裹数据集 | 跟踪包裹运输、交付、履约效率和物流异常 | 包裹号 + Item ID | `detail_table`、`bar_stacked` |
| 亚马逊品类市场容量 | 评估国家和平台类目的市场容量及品类机会 | 国家 + 类目 ID + 月份 | `line_basic`、`combo_bar_line` |

## 库存分析

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| 实时库存明细 | 查看当前 SKU 库存，支持缺货、调拨和履约判断 | 天 + 仓库名称 + 公司 SKU + 法人主体 ID | `detail_table`、`bar_stacked` |
| 库存周转数据集 | 评估库存周转，识别滞销、积压和缺货风险 | 部门 + 公司 SKU | `detail_table`、`line_basic` |
| 物控版库存周转 | 从物控视角评估 SKU 周转和备货合理性 | 部门 + 公司 SKU | `detail_table`、`line_basic` |
| 物控库存周转【期初期末】 | 比较期初期末库存，观察消耗、补充和结构变化 | 部门 + 公司 SKU | `detail_table`、`line_basic` |
| SKU仓库库存明细【物控版】 | 按 SKU 和仓库查看库存结构，支持备货、调拨和清仓 | 天 + 仓库名称 + 公司 SKU + 法人主体 ID | `detail_table`、`bar_stacked` |
| 捆绑SKU对应关系 | 查询捆绑 SKU 与组成 SKU 的映射，支持库存换算和销售归因 | 部门 + 捆绑 SKU + 公司 SKU | `detail_table`、`pivot_table` |
| SKU调拨出单情况 | 跟踪调拨是否出单和执行进度，定位未处理或延迟任务 | 部门 + 平台 + 国家 + 公司 SKU + 调拨新仓 | `detail_table`、`hbar_stacked_percent` |
| SKU仓库库龄明细 | 查看各仓 SKU 库龄，定位长库龄和滞销库存 | 天 + 仓库名称 + 公司 SKU + 法人主体 ID | `detail_table`、`bar_stacked` |
| SKU仓租库龄明细 | 结合仓租与库龄识别长期占仓和高成本 SKU | 天 + 仓库名称 + 公司 SKU + 法人主体 ID | `detail_table`、`bar_stacked` |

## 流量、活动与退款

| 数据集 | 何时选择与字段关注 | 粒度线索 | 候选 `viewType` |
| --- | --- | --- | --- |
| 亚马逊SC设备流量转化率数据集 | 比较不同设备的流量与成交转化，定位流量或转化问题 | 国家 + ASIN + 天 + 设备类型 | `combo_bar_line`、`bar_stacked_percent` |
| 流量转化率数据 | 分析亚马逊 SC 流量获取和成交转化 | 国家 + ASIN + 天 | `combo_bar_line`、`metric_trend` |
| TikTok流量转化率 | 分析 TikTok 渠道流量与成交转化，支持内容和商品优化 | 天 + 国家 + 父 ASIN | `combo_bar_line`、`bar_stacked_percent` |
| 活动数据集 | 分析亚马逊促销期间的销售、流量和推广表现 | 部门 + 渠道 + 渠道 SKU + 活动 ID + 天 | `detail_table`、`funnel_basic` |
| 亚马逊FBA退货退款 / 亚马逊VC退货退款 / 沃尔玛退货退款 / Wayfair退货退款 / TikTok退货退款 / Temu退货退款 / Shein退货退款 / Shopify退货退款 | 按平台查看退货退款，定位异常渠道、订单、SKU 和售后问题 | 天 + 部门 + 渠道 + 渠道 SKU + 订单号 | `detail_table`、`hbar_basic` |
| 退货产地数据集 | 从产地相关维度分析退款，辅助定位产品或供应链问题 | 天 + 部门 + 渠道 + 渠道 SKU | `hbar_basic`、`detail_table` |
