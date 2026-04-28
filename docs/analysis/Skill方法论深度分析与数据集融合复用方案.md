# Skill 方法论深度分析与数据集融合复用方案

> **文档定位**：深度拆解 7 个跨境电商 Skill（`competitive-landscape`、`cross-border-selection`、`market-insight-product-selection`、`product-attribute-analyzer`、`product-selection`、`review-analyst-agent`、`review-summarizer`）的设计理念与核心方法论，结合 opscli 现有 41 个数据集（1701 字段）的能力边界，提炼可直接复用于内部产品分析体系的框架、模型与流程。
>
> **适用范围**：数据产品经理、BI 分析师、运营策略团队
>
> **版本**：v1.0

---

## 目录

1. [执行摘要](#一执行摘要)
2. [Skill 方法论架构总览](#二skill-方法论架构总览)
3. [各 Skill 核心方法论深度拆解](#三各-skill-核心方法论深度拆解)
4. [opscli 数据集 × Skill 方法论 融合矩阵](#四opscli-数据集--skill-方法论-融合矩阵)
5. [可复用的 Skill 内容清单（按优先级）](#五可复用的-skill-内容清单按优先级)
6. [基于数据集+Skill方法论的产品优化建议方向](#六基于数据集skill方法论的产品优化建议方向)
7. [推荐落地实施路径](#七推荐落地实施路径)

---

## 一、执行摘要

### 1.1 核心发现

| 发现 | 说明 |
|------|------|
| **Skill 体系是"外部市场调研工具箱"** | 7 个 Skill 聚焦外部市场数据采集、竞品分析、选品决策，方法论成熟但**缺乏内部经营数据融合** |
| **opscli 数据集是"内部经营体检报告"** | 41 个数据集覆盖销售、广告、库存、流量、退款、促销、组织绩效，但**缺乏外部市场视角的决策框架** |
| **互补性极强** | Skill 的方法论框架 + opscli 的内部数据 = 完整的 "市场感知 → 经营诊断 → 优化建议" 闭环 |
| **可直接复用 6 大方法论** | 3-D 产品属性标签、4-Agent 评论分析流水线、VoC 多源验证、波特五力品类分析、BSR 健康度筛选、优先级行动矩阵 |

### 1.2 价值预估

- **短期（1-2 周）**：复用 `review-analyst-agent` 的优先级矩阵 + `product-attribute-analyzer` 的 3-D 标签体系，可立即提升 ASIN 健康度评分透视的**诊断深度**。
- **中期（1 个月）**：融合 `market-insight-product-selection` 的 VoC 验证框架 + `competitive-landscape` 的定位图，可构建**品类级竞争情报看板**。
- **长期（2-3 个月）**：整合 `product-selection` 的 4 步选品流程 + 内部数据，可升级为**数据驱动的新品开发决策系统**。

---

## 二、Skill 方法论架构总览

### 2.1 7 个 Skill 的方法论定位

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     外部市场感知层（Skill 方法论）                          │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────┤
│  竞争格局分析  │  选品决策引擎  │  产品属性洞察  │  评论/VOC分析  │  数据采集   │
│ competitive- │ product-     │ product-     │ review-      │ cross-      │
│ landscape    │ selection    │ attribute-   │ analyst-     │ border-     │
│              │              │ analyzer     │ agent        │ selection   │
├──────────────┼──────────────┼──────────────┼──────────────┼─────────────┤
│ Porter五力   │ 行业研究     │ 3-D标签体系  │ 4-Agent流水线 │ 详情页爬虫  │
│ 蓝海战略     │ 消费者研究   │ 销售加权份额 │ 情感分析     │ SKU展开     │
│ 定位图       │ BSR筛选逻辑  │ 属性组合分析 │ 优先级矩阵   │ 数据验证    │
│ 差异化策略   │ 众筹信号挖掘 │ Market Portrait│ 行动规划   │             │
└──────────────┴──────────────┴──────────────┴──────────────┴─────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     内部经营诊断层（opscli 数据集）                         │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────┤
│  销售财务    │  广告效率    │  库存周转    │  流量转化    │  组织绩效   │
│ order_sale_  │ advertising_ │ custom_      │ custom_asin_ │ team_name/  │
│ trend_*      │ list_set     │ inventory_*  │ sales_traffic│ dev_team_*  │
├──────────────┼──────────────┼──────────────┼──────────────┼─────────────┤
│ price        │ acos         │ inventory_   │ sessions     │ dept_name   │
│ gross_profit │ roas         │ turnaround_  │ convert_     │ large_team_ │
│ refund       │ cpc          │ days         │ percent      │ team_name   │
│ fee          │ clicks       │ fba_qty      │ page_views   │ team_       │
│              │ impressions  │              │              │ username    │
└──────────────┴──────────────┴──────────────┴──────────────┴─────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     优化建议输出层（融合后能力）                            │
├─────────────────────────────────────────────────────────────────────────┤
│ • ASIN 健康度评分（内部经营 + 外部评价）                                   │
│ • 品类竞争格局看板（内部份额 + 外部五力）                                   │
│ • 产品差异化建议（3-D属性 + 成本结构 + 评论痛点）                            │
│ • 运营优先级行动矩阵（数据异常 + 评论情感 + 改进ROI）                         │
│ • 新品机会雷达（内部空白 + 外部趋势 + 供应链可行性）                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 方法论成熟度评估

| Skill | 方法论深度 | 数据依赖度 | 可自动化程度 | 与内部数据融合难度 | 复用优先级 |
|-------|:--------:|:--------:|:----------:|:---------------:|:--------:|
| `product-attribute-analyzer` | ★★★★★ | 高（需销量数据） | 高 | 低（直接用内部数据替代外部销量） | P0 |
| `review-analyst-agent` | ★★★★★ | 中（需评论数据） | 中 | 中（需接入爬虫评价数据） | P0 |
| `competitive-landscape` | ★★★★☆ | 中（需竞品数据） | 低 | 中（需品类级聚合） | P1 |
| `market-insight-product-selection` | ★★★★☆ | 高（多源数据） | 低 | 高（需外部数据补充） | P1 |
| `product-selection` | ★★★★☆ | 高（需市场数据） | 中 | 高 | P2 |
| `review-summarizer` | ★★★☆☆ | 中 | 高 | 低 | P1 |
| `cross-border-selection` | ★★★☆☆ | 高（需爬虫） | 高 | 高 | P2 |

---

## 三、各 Skill 核心方法论深度拆解

### 3.1 `product-attribute-analyzer` — 产品属性 3-D 标签体系

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│                   3-Dimensional Tagging System               │
├─────────────────┬─────────────────┬─────────────────────────┤
│ Dimension 1     │ Dimension 2     │ Dimension 3             │
│ Structural/Fit  │ Material/Process│ Design Elements         │
│ 结构/版型       │ 材料/工艺       │ 设计元素                │
├─────────────────┼─────────────────┼─────────────────────────┤
│ • V-neck        │ • Cotton        │ • Solid color           │
│ • Crew-neck     │ • Polyester     │ • Striped               │
│ • Loose-fit     │ • Waffle-knit   │ • Minimalist            │
│ • Slim-fit      │ • Ribbed        │ • Bohemian              │
│ • 12oz / 20oz   │ • Stainless steel│ • Hollow-out           │
└─────────────────┴─────────────────┴─────────────────────────┘
```

**关键创新点**：
1. **销售加权市场份额**：不是按 ASIN 数量算份额，而是按 `monthly_sales` 加权。一个占 15% 的 listing 可能贡献 40% 销量（供给不足的机会）。
2. **属性组合分析**：不仅看单个维度，还看 "Loose-fit + V-neck + Solid color" 的组合占比。
3. **Market Portrait**：提炼出 "Market Favorite Archetype"（市场最受欢迎的原型配置）。

**可复用框架**：
- ✅ 3-D 标签字典设计规范（标准化命名、主标签选取规则）
- ✅ 销售加权份额计算公式
- ✅ 属性组合排名表模板
- ✅ Market Portrait 输出格式

---

### 3.2 `review-analyst-agent` — 4-Agent 评论分析流水线

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│                 4-Agent Parallel Analysis Pipeline           │
├───────────────┬───────────────┬───────────────┬─────────────┤
│ Agent 1       │ Agent 2       │ Agent 3       │ Agent 4     │
│ Review        │ Sentiment     │ Issue         │ Improvement │
│ Scraper       │ Analyzer      │ Identifier    │ Recommender │
├───────────────┼───────────────┼───────────────┼─────────────┤
│ • 多源采集    │ • 整体情感    │ • 投诉主题    │ • 优先级排序 │
│ • 去重分页    │ • 情感趋势    │ • 频率统计    │ • 改进建议  │
│ • 元数据提取  │ • 挫败指标    │ • 严重程度    │ • 预期影响  │
└───────────────┴───────────────┴───────────────┴─────────────┘
                              ↓
                    ┌─────────────────┐
                    │  Synthesis      │
                    │  优先级矩阵      │
                    │  行动计划        │
                    └─────────────────┘
```

**关键创新点**：
1. **优先级矩阵**：将问题分为 `Critical` / `Important` / `Nice-to-have` 三级。
2. **预期影响量化**：每个改进建议都附带 "expected_impact"（如 "Could improve rating by 0.3-0.5 stars"）。
3. **情感趋势追踪**：对比 6 个月前后的情感分数变化。

**可复用框架**：
- ✅ 4-Agent 流水线设计模式
- ✅ 优先级矩阵分类标准
- ✅ 预期影响量化模板
- ✅ 情感趋势计算方式
- ✅ JSON 结构化报告格式

---

### 3.3 `competitive-landscape` — 竞争格局多框架分析

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│              Competitive Analysis Framework Stack            │
├─────────────────────────────────────────────────────────────┤
│ Layer 1: Porter's Five Forces（行业吸引力评估）               │
│   - Threat of New Entrants                                  │
│   - Bargaining Power of Suppliers                           │
│   - Bargaining Power of Buyers                              │
│   - Threat of Substitutes                                   │
│   - Competitive Rivalry                                     │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: Blue Ocean Strategy（价值创新）                     │
│   - Four Actions Framework: Eliminate / Reduce / Raise / Create│
│   - Strategy Canvas（战略画布）                              │
│   - Value Innovation（低成本 + 高价值）                       │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: Positioning（定位分析）                             │
│   - Positioning Map（2-3 维度定位图）                        │
│   - Differentiation Strategy（产品/服务/品牌/价格差异化）      │
│   - Positioning Statement Framework（定位声明模板）            │
├─────────────────────────────────────────────────────────────┤
│ Layer 4: Competitive Intelligence（竞争情报）                │
│   - Competitor Profile Template（竞品画像模板）               │
│   - Pricing Comparison Matrix（定价对比矩阵）                 │
│   - Monitoring Cadence（监控节奏：周/月/季/年）               │
└─────────────────────────────────────────────────────────────┘
```

**关键创新点**：
1. **五力评分卡**：将抽象的竞争环境量化为 1-5 分的评分卡。
2. **战略画布**：可视化自身与竞品在关键竞争要素上的差异。
3. **定位声明模板**：标准化的价值主张输出格式。

**可复用框架**：
- ✅ 波特五力评分卡模板
- ✅ 四行动框架（Eliminate/Reduce/Raise/Create）
- ✅ 定位图绘制方法
- ✅ 竞品画像模板（公司概况/产品/Go-to-Market/优势/劣势/策略）
- ✅ 定价对比矩阵

---

### 3.4 `market-insight-product-selection` — 市场洞察选品法

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│           Evidence-First Multi-Source Triangulation          │
├─────────────────────────────────────────────────────────────┤
│ Step 1: Deep Search Protocol（深度搜索协议）                  │
│   - Round 1: Broad (3-6 queries)                            │
│   - Round 2: Deep (2-4 queries)                             │
│   - Round 3+: Until saturation                              │
│   - Stop conditions: No new entities for 2 rounds           │
├─────────────────────────────────────────────────────────────┤
│ Step 2: Entity Extraction & Mapping（实体提取与映射）         │
│   - Extract: products, brands, companies, technologies      │
│   - Map relationships: [Product] uses [Component]           │
│   - Identify next investigation points                      │
├─────────────────────────────────────────────────────────────┤
│ Step 3: Cross-Source Validation（跨源验证）                   │
│   - Connect insights from ≥3 sources                        │
│   - Contrarian search (find opposing views)                 │
│   - Source quality ranking (Industry > Tech > Community)    │
├─────────────────────────────────────────────────────────────┤
│ Step 4: Product Categorization（产品分类）                    │
│   - Safe bets: High sales + low complaints                  │
│   - High-potential: High buzz + low supply                  │
│   - Red ocean: High sales + high complaints                 │
│   - False trends: Short-term spikes                         │
└─────────────────────────────────────────────────────────────┘
```

**关键创新点**：
1. **深度搜索协议**：不限制搜索轮数，直到检测到饱和信号才停止。
2. **四象限产品分类**：将产品机会分为 Safe bets / High-potential / Red ocean / False trends。
3. **VoC（Voice of Customer）**：将评论/社交讨论中的用户痛点作为选品核心输入。

**可复用框架**：
- ✅ 深度搜索协议（轮次设计、停止条件）
- ✅ 实体提取与关系映射方法
- ✅ 跨源验证逻辑
- ✅ 四象限产品分类法
- ✅ 需求重述（Demand Restatement）模板

---

### 3.5 `product-selection` — 四步选品工作流

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│              Product Selection 4-Step Workflow               │
├─────────────────────────────────────────────────────────────┤
│ Step 1: Industry Research（行业研究）                         │
│   - Criteria: Traffic trend > Sales trend > Competition      │
│   - Tools: SimilarWeb, Jungle Scout, Helium 10              │
├─────────────────────────────────────────────────────────────┤
│ Step 2: Consumer Research（消费者研究）★ 不可跳过              │
│   - Extract complaints from reviews/social/Q&A              │
│   - Categorize: Quality / Design / Price / Delivery         │
│   - Map to: Improvement / Gap-filling / Differentiation     │
├─────────────────────────────────────────────────────────────┤
│ Step 3: Product Selection（产品选择）                         │
│   - Approach 1: E-commerce (BSR 100-5,000, 300-1,000 reviews)│
│   - Approach 2: Ad & Traffic (ad frequency ≥10 in 30d)      │
│   - Approach 3: Crowdfunding (200-500% funded, 500-5k backers)│
├─────────────────────────────────────────────────────────────┤
│ Step 4: Supplier Matching（供应商匹配）★ 仅按需触发            │
│   - Alibaba/1688 search                                     │
│   - Qualification: Trade Assurance / MOQ / Lead time        │
└─────────────────────────────────────────────────────────────┘
```

**关键创新点**：
1. **自适应入口**：根据用户提供的上下文决定从哪一步开始。
2. **消费者研究不可跳过**：即使指定了行业，也需要消费者洞察来指导具体品类选择。
3. **BSR 筛选逻辑**：BSR 100-5,000 是最佳跟卖区间；review 300-1,000 表示已验证但仍有改进空间。

**可复用框架**：
- ✅ 自适应入口决策树
- ✅ 行业研究筛选标准（流量/销售/竞争/新品率/合规）
- ✅ 消费者痛点分类体系
- ✅ BSR 健康度筛选逻辑
- ✅ 供应商评估标准

---

### 3.6 `review-summarizer` — 评论摘要与情感分析

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│              Multi-Platform Review Intelligence              │
├─────────────────────────────────────────────────────────────┤
│ Input: Product URL / Product Name                           │
│ Platforms: Amazon, Google, Yelp, TripAdvisor                │
├─────────────────────────────────────────────────────────────┤
│ Analysis Pipeline:                                          │
│   1. Multi-platform scraping                                │
│   2. Sentiment analysis (overall + aspect-based)            │
│   3. Insight extraction (pros/cons/FAQ/use cases)           │
│   4. Summary generation (executive + detailed)              │
│   5. Recommendation engine                                  │
├─────────────────────────────────────────────────────────────┤
│ Output:                                                     │
│   • Overall sentiment score (-1.0 to +1.0)                  │
│   • Sentiment distribution (positive/neutral/negative %)    │
│   • Top pros with frequency counts                          │
│   • Top cons with frequency counts                          │
│   • Statistical summary (avg rating, review count)          │
└─────────────────────────────────────────────────────────────┘
```

**关键创新点**：
1. **多平台对比**：同一产品在不同平台的评价差异分析。
2. **基于方面的情感分析（Aspect-based）**：如 "battery life"、"sound quality" 分别打分。
3. **使用场景提取**：从评论中自动识别用户的使用场景和应用方式。

**可复用框架**：
- ✅ 多平台评论采集标准
- ✅ 情感分数计算方式（-1.0 到 +1.0）
- ✅ 基于方面的情感分析维度设计
- ✅ 使用场景提取方法
- ✅ 评论数据 CSV 导出格式

---

### 3.7 `cross-border-selection` — 跨境选品数据采集

**核心方法论**：

```
┌─────────────────────────────────────────────────────────────┐
│              Amazon Detail Page Scraping Protocol            │
├─────────────────────────────────────────────────────────────┤
│ HARD-GATE: Must visit detail page (NOT listing page)        │
│ HARD-GATE: Must expand by SKU variant                       │
│ HARD-GATE: Must extract 11 core fields                      │
├─────────────────────────────────────────────────────────────┤
│ 11 Core Fields:                                             │
│   1. Product SKU (variant)                                  │
│   2. Parent ASIN                                            │
│   3. Product Title                                          │
│   4. SKU Price                                              │
│   5. Product Rating                                         │
│   6. Review Count                                           │
│   7. Sales Volume                                           │
│   8. Product Selling Points (bullet points)                 │
│   9. Product Specs                                          │
│   10. Product Image Link                                    │
│   11. Detail Page Link                                      │
├─────────────────────────────────────────────────────────────┤
│ Output: JSON (nested) + CSV (flattened by SKU)              │
│ Validation: Record count = Sum of SKU counts                │
└─────────────────────────────────────────────────────────────┘
```

**关键创新点**：
1. **三层提取机制**：图片 URL 必须通过 HTTP HEAD 验证有效性。
2. **SKU 展开原则**：每个变体（Size × Color）独立成一行记录。
3. **HARD-GATE 验证**：4 阶段验证清单，任一条件不满足即停止。

**可复用框架**：
- ✅ 11 核心字段标准（可用于定义爬虫数据表字段）
- ✅ SKU 展开数据模型
- ✅ 数据完整性验证清单
- ✅ JSON + CSV 双格式输出规范

---

## 四、opscli 数据集 × Skill 方法论 融合矩阵

### 4.1 数据集能力 vs Skill 需求对照

| Skill 方法论 | 需要的数据输入 | opscli 可提供的对应数据 | 融合可行性 | 融合方式 |
|-------------|--------------|---------------------|:--------:|---------|
| **3-D 产品属性标签** | ASIN 列表 + 标题/图片 + 月销量 | `query_product_set`（品类/型号/品牌）+ `order_sale_trend_set`（月销量）+ `query_listing_set`（ASIN/图片） | ★★★★★ | 直接用内部销量替代外部销量估算 |
| **销售加权市场份额** | 各 ASIN 月销量 | `order_sale_trend_adv_traffic_inv_set`.`order_qty` / `original_price` | ★★★★★ | 聚合计算即可 |
| **4-Agent 评论分析** | 评论文本 + 评分 | `custom_crawler_listing_snapshot`（rating/reviews_qty）+ 爬虫评论表（如扩展） | ★★★★☆ | 需扩展爬虫采集评论文本 |
| **优先级矩阵** | 问题频率 + 严重程度 + 改进成本 | `custom_operation_suggest_suggestions_set`（运营建议/关注点/严重程度）+ 退款数据 | ★★★★☆ | 将运营建议与评论痛点关联 |
| **波特五力评分卡** | 品类级竞争数据（卖家数/集中度/进入壁垒） | `custom_brand_search_catalog_set`（目录绩效）+ `custom_brand_search_query_set`（搜索词绩效） | ★★★☆☆ | 需品类聚合 + 外部数据补充 |
| **定位图** | 价格 + 功能/评分 二维坐标 | `custom_crawler_listing_snapshot`（price/rating）+ `order_sale_trend_set`（销量） | ★★★★☆ | 用爬虫数据绘制自身+竞品定位 |
| **四象限产品分类** | 销售额 + 投诉率 | `order_sale_trend_adv_traffic_inv_set`（price）+ `custom_refund_place_set`（退款） | ★★★★★ | 直接计算：高销低退=Safe bet |
| **BSR 健康度筛选** | BSR 排名 + review 数 + rating | `custom_crawler_listing_snapshot`（subclass_rank/rating/reviews_qty） | ★★★★★ | 直接应用 BSR 100-5000 筛选逻辑 |
| **消费者痛点映射** | 评论中的投诉主题 | `custom_refund_place_set`（退款原因/产地）+ `custom_operation_suggest_suggestions_set`（issue_type） | ★★★★☆ | 用内部退款原因替代部分评论痛点 |
| **情感趋势追踪** | 时序评论情感分数 | 需新增评论情感时序表，或基于 `custom_crawler_listing_trend_set`（rating_stars 趋势） | ★★★☆☆ | 用星级趋势近似情感趋势 |

### 4.2 数据融合后的增强能力

```
┌─────────────────────────────────────────────────────────────────┐
│                    融合后的增强分析能力                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   BEFORE (Skill 单独使用)          AFTER (Skill + opscli 数据)  │
│  ────────────────────────          ─────────────────────────    │
│                                                                 │
│  外部估算销量 × 属性标签           内部真实销量 × 属性标签        │
│  → 市场份额有偏差                  → 市场份额 100% 准确           │
│                                                                 │
│  评论情感分析 → 改进建议           评论痛点 + 退款数据 + 广告ACOS  │
│  → 只知其然                        → 知其然 + 知其所以然         │
│                                                                 │
│  波特五力 → 定性判断               波特五力 + 内部品类销售集中度   │
│  → 主观评估                        → 定量验证                    │
│                                                                 │
│  BSR 筛选 → 发现跟卖机会           BSR 筛选 + 内部毛利 + 周转天数  │
│  → 只考虑市场需求                  → 同时考虑盈利能力和库存健康    │
│                                                                 │
│  定位图 → 可视化竞争格局           定位图 + 毛利率 + 广告依赖度    │
│  → 只看价格和评分                  → 看价格/评分/盈利/流量结构    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、可复用的 Skill 内容清单（按优先级）

### 5.1 P0 — 立即复用（1-2 周落地）

#### ① `product-attribute-analyzer` 的 3-D 标签体系 + 销售加权份额

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| 3-D 标签字典设计规范 | 对 `query_product_set` 的 `category`/`model`/`brand_name`/`style_name` 等字段进行标准化映射 | `query_product_set`, `query_listing_set` | 产品属性标签字典 |
| 销售加权份额计算公式 | `SUM(order_qty) WHERE tag = 'X' / SUM(order_qty) ALL` | `order_sale_trend_adv_traffic_inv_set` | 各标签的市场份额表 |
| 属性组合排名表模板 | 按 `category` + `development_type` + `sku_type` 组合聚合销量 | `order_sale_trend_adv_traffic_inv_set` | Top 10 属性组合 |
| Market Portrait 输出格式 | 直接套用模板，替换为内部数据 | `order_sale_trend_adv_traffic_inv_set` | 品类 Market Portrait 报告 |

#### ② `review-analyst-agent` 的优先级矩阵 + 行动规划

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| 优先级三级分类（Critical/Important/Nice-to-have） | 将 `custom_operation_suggest_suggestions_set` 的 `severity` + `issue_type` 映射到三级分类 | `custom_operation_suggest_suggestions_set` | 运营建议优先级看板 |
| 预期影响量化模板 | 对高退款率产品，量化 "修复后预计降低退款率 X%" | `custom_refund_place_set`, `order_sale_trend_adv_traffic_inv_set` | 改进 ROI 预估 |
| 4-Agent 流水线设计模式 | 设计内部数据版：数据提取 → 异常检测 → 根因分析 → 建议生成 | 全部核心数据集 | 自动化诊断流水线 |

#### ③ `review-summarizer` 的基于方面的情感分析维度

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| Aspect-based 分析维度 | 将退款原因、运营建议关注点映射到分析维度 | `custom_refund_place_set`, `custom_operation_suggest_suggestions_set` | 多维度痛点分布图 |
| 情感分数计算方式 | 用 `star`（星级）和 `refund_percent`（退款率）构建近似情感分数 | `custom_crawler_listing_snapshot`, `order_sale_trend_adv_traffic_inv_set` | ASIN 情感健康度评分 |

### 5.2 P1 — 短期复用（1 个月落地）

#### ④ `competitive-landscape` 的波特五力 + 定位图

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| 波特五力评分卡模板 | 用内部品类销售集中度替代 "卖家数"，用 `custom_brand_search_query_set` 替代 "搜索趋势" | `custom_brand_search_catalog_set`, `custom_brand_search_query_set`, `order_sale_trend_adv_traffic_inv_set` | 品类竞争强度评分卡 |
| 定位图绘制方法 | X 轴：平均价格 / Y 轴：平均评分 / 气泡大小：销量 / 气泡颜色：毛利率 | `custom_crawler_listing_snapshot`, `order_sale_trend_adv_traffic_inv_set` | 品类定位气泡图 |
| 四行动框架（Eliminate/Reduce/Raise/Create） | 结合成本结构分析（`purchase_cost_percent`, `first_leg_percent` 等）进行价值创新分析 | `order_sale_trend_adv_traffic_inv_set` | 产品差异化策略建议 |

#### ⑤ `market-insight-product-selection` 的四象限分类 + 深度搜索协议

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| 四象限产品分类法 | X 轴：销售额（`original_price`）/ Y 轴：退款率（`refund_percent`） | `order_sale_trend_adv_traffic_inv_set` | 产品机会矩阵 |
| 实体提取与关系映射 | 从 `custom_brand_search_query_set` 提取搜索词-产品-品牌关系 | `custom_brand_search_query_set` | 搜索词关联图谱 |
| 需求重述模板 | 对每个品类输出 1-2 句需求重述 | `custom_asin_sales_traffic_set`（流量结构） | 品类需求洞察卡片 |

#### ⑥ `product-selection` 的 BSR 健康度筛选 + 消费者痛点映射

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| BSR 健康度筛选逻辑 | 对 `custom_crawler_listing_snapshot.subclass_rank` 应用 BSR 100-5000 筛选 | `custom_crawler_listing_snapshot` | 潜力 ASIN 清单 |
| 消费者痛点分类体系 | 将内部退款原因映射到 Quality/Design/Price/Delivery 分类 | `custom_refund_place_set` | 退款根因分类报告 |
| 改进/填补/差异化机会映射 | 将痛点映射到产品改进方向 | `custom_operation_suggest_suggestions_set` | 产品迭代建议清单 |

### 5.3 P2 — 中期复用（2-3 个月落地）

#### ⑦ `cross-border-selection` 的 11 核心字段标准 + 数据验证清单

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| 11 核心字段标准 | 作为 `custom_crawler_listing_snapshot` 和 `custom_crawler_listing_trend_set` 的字段扩展规范 | 爬虫数据集 | 爬虫数据标准 v2.0 |
| SKU 展开数据模型 | 对多变体 ASIN 建立父子关系模型 | `query_listing_set`（`parent_asin`/`asin`） | ASIN 变体关系图谱 |
| HARD-GATE 验证清单 | 设计内部数据质量验证流程 | 全部数据集 | 数据质量监控看板 |

#### ⑧ `product-selection` 的众筹信号挖掘 + 供应商匹配

| 复用内容 | 落地方式 | 所需数据集 | 预期输出 |
|---------|---------|-----------|---------|
| 众筹筛选逻辑 | 对新品（`new_old_product = 'new'`）应用 "高增速 + 低基数" 筛选 | `custom_inventory_turnover_wk_cw_set` | 新品机会雷达 |
| 供应商评估标准 | 将供应商评估维度纳入产品开发流程 | 外部数据源 | 供应商评估模板 |

---

## 六、基于数据集+Skill方法论的产品优化建议方向

### 6.1 优化建议总览

结合 Skill 方法论和 opscli 数据集优势，可从 **8 个方向** 给产品优化建议：

| 方向 | Skill 方法论来源 | 核心数据集 | 优化建议类型 | 业务价值 |
|------|----------------|-----------|------------|---------|
| **① 产品属性优化** | `product-attribute-analyzer` 3-D 标签 | `order_sale_trend_adv_traffic_inv_set` + `query_product_set` | 基于真实销量的属性配置建议 | 高 |
| **② 评论痛点修复** | `review-analyst-agent` 优先级矩阵 | `custom_refund_place_set` + `custom_operation_suggest_suggestions_set` | 按 ROI 排序的改进清单 | 高 |
| **③ 成本结构优化** | `competitive-landscape` 四行动框架 | `order_sale_trend_adv_traffic_inv_set`（成本占比字段） | Eliminate/Reduce/Raise/Create 策略 | 高 |
| **④ 定价策略优化** | `competitive-landscape` 定价对比矩阵 | `custom_crawler_listing_snapshot`（price）+ `order_sale_trend_set`（avg_price_cny） | 价格带定位与动态调价建议 | 中高 |
| **⑤ 广告效率优化** | `product-selection` BSR 筛选 + 广告数据 | `advertising_list_set` + `custom_type_advertising_list` | ACOS 优化 + 关键词机会挖掘 | 高 |
| **⑥ 库存结构优化** | `market-insight-product-selection` 四象限 | `custom_inventory_turnover_wk_set` + `order_sale_trend_adv_traffic_inv_set` | 滞销清仓/断货补货/在途调配 | 高 |
| **⑦ 品类竞争策略** | `competitive-landscape` 波特五力 + 定位图 | `custom_brand_search_catalog_set` + `custom_brand_search_query_set` | 品类进入/退出/深耕决策 | 中高 |
| **⑧ 新品开发决策** | `product-selection` 4 步流程 + `market-insight` VoC | `custom_asin_sales_traffic_set` + `custom_brand_search_query_set` | 数据驱动的新品机会评估 | 中 |

### 6.2 方向详解

#### 方向 ①：产品属性优化（3-D 标签 + 销售加权份额）

**方法论**：复用 `product-attribute-analyzer` 的 3-D 标签体系，将产品属性分为 Structural/Fit、Material/Process、Design Elements 三个维度。

**数据集应用**：
- 用 `query_product_set` 的 `category` / `sec_category` / `model` / `style_name` / `development_type` / `sku_type` 等字段作为标签来源
- 用 `order_sale_trend_adv_traffic_inv_set` 的 `order_qty` / `original_price` 作为销量权重

**优化建议示例**：

```
品类：Kitchen Gadgets
样本：156 个 ASIN

Dimension 1: Development Type（开发类型）
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ Attribute Tag   │ ASIN Count│ Total Sales │ Market Share│ Avg Sales/ASIN│
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ 自主研发        │ 45       │ $890,000    │ 52.3%      │ $19,778      │
│ OEM贴牌         │ 78       │ $620,000    │ 36.4%      │ $7,949       │
│ 外采成品        │ 33       │ $192,000    │ 11.3%      │ $5,818       │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘

→ 优化建议：自主研发产品虽数量少（29%），但贡献 52% 销售额且单均销量最高。
  建议：增加自主研发 SKU 占比，减少外采成品。

Dimension 2: SKU Type（SKU等级）
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ Attribute Tag   │ ASIN Count│ Total Sales │ Market Share│ Avg Sales/ASIN│
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ A级             │ 23       │ $720,000    │ 42.3%      │ $31,304      │
│ B级             │ 56       │ $580,000    │ 34.1%      │ $10,357      │
│ C级             │ 77       │ $402,000    │ 23.6%      │ $5,221       │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘

→ 优化建议：A级 SKU 数量仅占 15%，但贡献 42% 销售额。
  建议：将 B/C 级中表现好的产品（销售额 > $15k）升级为 A 级资源投入。
```

#### 方向 ②：评论痛点修复（优先级矩阵 + 内部数据验证）

**方法论**：复用 `review-analyst-agent` 的 4-Agent 流水线和优先级矩阵，将问题分为 Critical / Important / Nice-to-have。

**数据集应用**：
- 用 `custom_refund_place_set` 的退款原因和 `overseas_origin_suffix`（产地）作为 Issue Identifier 的输入
- 用 `custom_operation_suggest_suggestions_set` 的 `issue_type` / `severity` / `operation_stage` 作为优先级判断依据
- 用 `order_sale_trend_adv_traffic_inv_set` 的 `gross_profit` / `refund_percent` 量化预期影响

**优化建议示例**：

```
产品：ASIN B08XXXXXX（保温杯）

优先级矩阵：
┌─────────────────────┬──────────┬──────────┬──────────────────────────────┐
│ Issue               │ Severity │ Frequency│ 内部数据验证                  │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 🔴 Critical         │          │          │                              │
│ 漏水（leaking）     │ 高       │ 23%      │ refund_percent = 18.5%，     │
│                     │          │          │ 高于品类均值 8.2%             │
│ 容量虚标            │ 高       │ 15%      │ 退货原因中 "尺寸不符" 占 31%  │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 🟡 Important        │          │          │                              │
│ 保温时间短          │ 中       │ 19%      │ 星级 3.8（品类均值 4.3）      │
│ 杯盖难清洗          │ 中       │ 12%      │ reviews_qty 增长但 rating 持平│
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 🟢 Nice-to-have     │          │          │                              │
│ 颜色选择少          │ 低       │ 8%       │ 无显著销售影响                │
│ 包装简陋            │ 低       │ 5%       │ 无退款关联                    │
└─────────────────────┴──────────┴──────────┴──────────────────────────────┘

→ 优化建议：
  1. 【Critical】立即排查漏水原因（密封圈/焊接工艺），预计修复后退款率可从 18.5% 降至 10% 以下
  2. 【Critical】修正容量标注，增加实物对比图，预计降低 "尺寸不符" 退货 50%
  3. 【Important】升级保温材料或调整用户预期（标注实际保温时长），预计提升 rating 0.3-0.5 星
```

#### 方向 ③：成本结构优化（四行动框架）

**方法论**：复用 `competitive-landscape` 的 Blue Ocean Strategy 四行动框架（Eliminate / Reduce / Raise / Create）。

**数据集应用**：
- 用 `order_sale_trend_adv_traffic_inv_set` 的全部成本占比字段（`purchase_cost_percent`, `first_leg_percent`, `freight_percent`, `storage_charges_percent`, `advertising_fee_percent`, `fee_percent`, `tax_fee_percent`, `fixed_cost_percent`）作为分析基础

**优化建议示例**：

```
产品：ASIN B09XXXXXX（蓝牙耳机）

成本结构（占销售额比例）：
┌─────────────────────┬──────────┬──────────┬─────────────────────────────┐
│ Cost Item           │ Current  │ Benchmark│ 四行动分析                   │
├─────────────────────┼──────────┼──────────┼─────────────────────────────┤
│ 采购成本            │ 28.5%    │ 25.0%    │ Reduce: 谈判或更换供应商      │
│ 头程运费            │ 8.2%     │ 6.5%     │ Reduce: 合并发货/优化货代     │
│ 平台手续费          │ 15.0%    │ 15.0%    │ — 固定成本，难以改变          │
│ 广告费              │ 22.0%    │ 18.0%    │ Reduce: 优化ACOS从22%到18%   │
│ 仓租                │ 5.5%     │ 4.0%     │ Eliminate: 清理滞销库存       │
│ 税金                │ 8.0%     │ 8.0%     │ — 固定成本                    │
│ 固定成本            │ 3.0%     │ 3.0%     │ — 固定成本                    │
│ 退款/赔偿           │ 6.8%     │ 3.5%     │ Eliminate: 修复产品质量问题   │
├─────────────────────┼──────────┼──────────┼─────────────────────────────┤
│ 毛利率              │ 3.0%     │ 17.0%    │ 严重低于健康水平              │
└─────────────────────┴──────────┴──────────┴─────────────────────────────┘

→ 四行动策略：
  Eliminate:
    • 清理库龄 > 90 天的滞销库存，减少超量仓租和移除费
    • 修复导致 6.8% 退款率的质量问题（如充电口松动）
  
  Reduce:
    • 将广告 ACOS 从 22% 优化至 18%，预计节省 $4,200/月
    • 头程运费占比从 8.2% 降至 7%，通过货量整合谈判
  
  Raise:
    • 提升售价 10%（当前定价 $29.99，竞品区间 $35-45，有提价空间）
    • 加强品牌溢价（品牌搜索词占比从 12% 提升至 20%）
  
  Create:
    • 开发差异化功能（如主动降噪 + 环境音模式），避开价格战
    • 增加配件包（充电座/收纳盒）提升客单价
```

#### 方向 ④：定价策略优化（定位图 + 价格带分析）

**方法论**：复用 `competitive-landscape` 的定位图和 `product-attribute-analyzer` 的价格带分析。

**数据集应用**：
- 用 `custom_crawler_listing_snapshot` 的 `price` / `rating` / `subclass_rank` 绘制竞争定位图
- 用 `order_sale_trend_set` 的 `avg_price_cny` 分析自身价格带分布

**优化建议示例**：

```
品类：Dog Beds（狗床）

定位图（Price vs. Rating，气泡大小 = 月销量）：

High Price
    |
    |     ★ Premium Brand A      ★ Premium Brand B
    |          (4.8★, $89)            (4.7★, $79)
    |
    |                 ● Our Position?
    |               (4.5★, $45)
    |
    |    ★ Mid Brand C          ★ Mid Brand D
    |     (4.3★, $39)            (4.2★, $35)
    |
    |  ★ Value Brand E    ★ Value Brand F
    |   (4.0★, $19)        (3.9★, $15)
    |
Low Price |____________________________________________
         Low Rating                          High Rating

价格带分布（内部销售数据）：
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ Price Band      │ ASIN Count│ Total Sales │ Market Share│ Avg Margin   │
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ $15-25 (低端)    │ 12       │ $45,000     │ 15.2%      │ 12%          │
│ $25-40 (中端)    │ 18       │ $128,000    │ 43.3%      │ 22%          │
│ $40-60 (中高端)  │ 8        │ $98,000     │ 33.1%      │ 28%          │
│ $60+ (高端)      │ 3        │ $25,000     │ 8.4%       │ 35%          │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘

→ 优化建议：
  1. 当前主打 $45 中高端价格带，但数量少（仅 8 个 ASIN），供不应求
  2. 建议：将 3-4 个表现好的中端 ASIN 升级配置（材质/功能），迁移至 $50-55 价格带
  3. 高端市场 ($60+) 竞争者少但销量低，可尝试 1-2 个差异化 SKU 测试市场
```

#### 方向 ⑤：广告效率优化（BSR 筛选 + 广告类型对比）

**方法论**：复用 `product-selection` 的 BSR 健康度筛选 + `product-attribute-analyzer` 的销售加权分析。

**数据集应用**：
- 用 `advertising_list_set` / `custom_type_advertising_list` / `custom_sp_ads_set` / `custom_sd_ads_set` / `custom_sb_ads_set` 分析广告效率
- 用 `custom_crawler_listing_snapshot` 的 `subclass_rank` 评估市场位置

**优化建议示例**：

```
广告效率多维分析：

┌─────────────────┬────────┬──────────┬────────┬────────┬─────────────┐
│ Ad Type         │ Spend  │ Sales    │ ACOS   │ ROAS   │ Recommendation│
├─────────────────┼────────┼──────────┼────────┼────────┼─────────────┤
│ SP (Sponsored)  │ $8,200 │ $32,800  │ 25.0%  │ 4.0    │ 维持，优化关键词│
│ SD (Display)    │ $3,500 │ $8,750   │ 40.0%  │ 2.5    │ ⚠️ 高ACOS，需审查│
│ SB (Brand)      │ $2,800 │ $18,200  │ 15.4%  │ 6.5    │ ✅ 高效，增加预算│
│ SBV (Video)     │ $1,200 │ $4,800   │ 25.0%  │ 4.0    │ 测试扩大       │
└─────────────────┴────────┴──────────┴────────┴────────┴─────────────┘

→ 优化建议：
  1. SB 广告 ROAS 6.5，为最高效类型，建议将预算从 $2,800 提升至 $4,500
  2. SD 广告 ACOS 40%，远超健康线（30%），需审查投放受众和竞品定位
  3. SP 广告销量占比最高，建议将 SD 节省的预算转移至 SP 的长尾词广告组
  4. 结合 `custom_brand_search_query_set`，发现 3 个高转化品牌词未被投放，建议新增 SB 广告组
```

#### 方向 ⑥：库存结构优化（四象限分类 + 周转健康度）

**方法论**：复用 `market-insight-product-selection` 的四象限产品分类法。

**数据集应用**：
- 用 `custom_inventory_turnover_wk_set` 的 `inventory_turnaround_days` / `average_daily_sales_volume`
- 用 `order_sale_trend_adv_traffic_inv_set` 的 `gross_profit_percent` / `sell_qty_days` / `total_qty`

**优化建议示例**：

```
库存四象限矩阵（X轴：周转天数 / Y轴：毛利率）：

High Margin
    |
    |  ★ 明星产品          |  ⚠️ 问题产品
    |  (快周转 + 高毛利)    |  (慢周转 + 高毛利)
    |                      |
    |  → 加大备货          |  → 分析滞销原因
    |  → 增加广告投入       |  → 促销清货或优化listing
    |______________________|_______________________
    |                      |
    |  ▲ 现金牛            |  ✕ 淘汰品
    |  (快周转 + 低毛利)    |  (慢周转 + 低毛利)
    |                      |
    |  → 维持库存           |  → 立即清货
    |  → 优化成本结构       |  → 停止采购
    |
Low Margin
         Fast Turnover          Slow Turnover

具体产品示例：
┌──────────┬────────────┬────────────┬────────────┬─────────────────────────────┐
│ ASIN     │ Turnover   │ Margin     │ Quadrant   │ Action                      │
├──────────┼────────────┼────────────┼────────────┼─────────────────────────────┤
│ B08AAA   │ 18 days    │ 32%        │ 明星       │ 增加 30% 备货，加大广告       │
│ B08BBB   │ 75 days    │ 28%        │ 问题       │ 开启 20% Coupon 促销清货      │
│ B08CCC   │ 22 days    │ 12%        │ 现金牛     │ 谈判采购成本，目标提升至 15%  │
│ B08DDD   │ 95 days    │ 5%         │ 淘汰       │ 立即移除库存，停止采购         │
└──────────┴────────────┴────────────┴────────────┴─────────────────────────────┘
```

#### 方向 ⑦：品类竞争策略（波特五力 + 内部集中度）

**方法论**：复用 `competitive-landscape` 的波特五力评分卡。

**数据集应用**：
- 用 `custom_brand_search_catalog_set`（亚马逊目录绩效）评估品类搜索份额
- 用 `custom_brand_search_query_set`（搜索词绩效）评估关键词竞争度
- 用 `order_sale_trend_adv_traffic_inv_set` 按品类聚合计算内部销售集中度

**优化建议示例**：

```
品类：Water Bottles（水杯）

波特五力评分卡（结合内部数据）：
┌─────────────────────┬────────┬────────┬─────────────────────────────────────┐
│ Force               │ Score  │ Impact │ Internal Data Evidence              │
├─────────────────────┼────────┼────────┼─────────────────────────────────────┤
│ 新进入者威胁         │ 4/5    │ 高     │ 新品 ASIN 占比 35%，但存活率仅 20%   │
│ 供应商议价能力       │ 2/5    │ 低     │ 3 家主要供应商，MOQ 灵活              │
│ 买家议价能力         │ 3/5    │ 中     │ 价格敏感度高，$20 以下销量占 65%      │
│ 替代品威胁           │ 3/5    │ 中     │ 不锈钢/玻璃/塑料三分天下              │
│ 现有竞争强度         │ 5/5    │ 极高   │ Top 10 ASIN 占品类销售额 72%          │
├─────────────────────┼────────┼────────┼─────────────────────────────────────┤
│ 综合评估             │ —      │ 高竞争 │ 高竞争 + 低壁垒，需谨慎进入或差异化   │
└─────────────────────┴────────┴────────┴─────────────────────────────────────┘

→ 优化建议：
  1. 该品类为 Red Ocean，不建议新进入，除非有强差异化
  2. 现有产品应采取 Niche Focus 策略：聚焦 "运动保温杯" 细分（内部数据显示增速 40%，Top 10 占比仅 45%）
  3. 通过 `custom_brand_search_query_set` 发现 "collapsible water bottle" 搜索量增长 180% 但供给少，是潜在 Blue Ocean
```

#### 方向 ⑧：新品开发决策（VoC + 内部空白分析）

**方法论**：复用 `product-selection` 的 4 步流程 + `market-insight-product-selection` 的 VoC 验证。

**数据集应用**：
- 用 `custom_brand_search_query_set` 发现高搜索量低品牌份额的关键词
- 用 `custom_asin_sales_traffic_set` 分析设备流量结构（Mobile App vs Browser）
- 用 `custom_inventory_turnover_wk_cw_set` 的 `new_old_product` 标志追踪新品表现

**优化建议示例**：

```
新品机会雷达：

内部空白分析：
┌─────────────────────┬────────────┬────────────┬─────────────────────────────┐
│ Category Gap        │ Search Vol │ Our Share  │ Opportunity                 │
├─────────────────────┼────────────┼────────────┼─────────────────────────────┤
│ 儿童折叠水杯         │ 高         │ 0%         │ 完全空白，需求增长快          │
│ 智能温控杯           │ 中高       │ 3%         │ 有少量布局，可加大投入        │
│ 大容量运动壶         │ 中         │ 12%        │ 已有基础，需差异化升级        │
└─────────────────────┴────────────┴────────────┴─────────────────────────────┘

VoC 验证（从 `custom_operation_suggest_suggestions_set` + 退款数据）：
  • 儿童水杯退款原因中 "材质不安全" 占 41% → 机会：FDA认证 + 食品级材质
  • 智能杯运营建议中 "APP连接不稳定" 被提及 23 次 → 机会：优化蓝牙连接体验

→ 新品开发建议：
  1. 【高优先级】儿童折叠水杯：FDA认证 + 防漏设计 + 卡通外观，目标 $15-20 价格带
  2. 【中优先级】智能温控杯 V2：解决蓝牙稳定性 + 增加温度显示屏，目标 $35-45
  3. 【测试】大容量运动壶：增加过滤功能 + 吸管设计，与现有 SKU 形成矩阵
```

---

## 七、推荐落地实施路径

### 7.1 三阶段路线图

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 1: 基础框架搭建（第 1-2 周）                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  ✅ 复用 `product-attribute-analyzer` 3-D 标签体系                      │
│     → 对现有产品按 category + development_type + sku_type 进行 3-D 打标  │
│     → 输出销售加权份额表（每个维度的 Market Share %）                     │
│                                                                         │
│  ✅ 复用 `review-analyst-agent` 优先级矩阵                              │
│     → 将 `custom_operation_suggest_suggestions_set` 的 issue 按三级分类  │
│     → 关联 `refund_percent` 量化预期影响                                 │
│     → 输出 Critical/Important/Nice-to-have 运营看板                     │
│                                                                         │
│  ✅ 复用 `review-summarizer` 情感分析维度                                │
│     → 用 `star` + `refund_percent` 构建 ASIN 情感健康度评分              │
│     → 输出多维度痛点分布图                                               │
├─────────────────────────────────────────────────────────────────────────┤
│  Phase 2: 分析深度增强（第 3-4 周）                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  ✅ 复用 `competitive-landscape` 定位图 + 定价矩阵                       │
│     → 用 `custom_crawler_listing_snapshot` 绘制 Price vs Rating 气泡图   │
│     → 叠加毛利率颜色编码                                                 │
│                                                                         │
│  ✅ 复用 `market-insight-product-selection` 四象限分类                   │
│     → X轴：销售额 / Y轴：退款率                                          │
│     → 识别 Safe bets / High-potential / Red ocean / False trends        │
│                                                                         │
│  ✅ 复用 `product-selection` BSR 健康度筛选                              │
│     → 对 `subclass_rank` 应用 BSR 100-5000 逻辑                         │
│     → 叠加 `gross_profit_percent` 和 `sell_qty_days` 过滤               │
│     → 输出 "潜力 ASIN 清单"                                             │
├─────────────────────────────────────────────────────────────────────────┤
│  Phase 3: 智能化升级（第 2-3 个月）                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  ✅ 构建自动化诊断流水线（4-Agent 内部版）                                │
│     Agent 1: 数据提取（SQL 自动聚合）                                    │
│     Agent 2: 异常检测（规则引擎：ACOS>30%, 退款率>10%, 周转>90天）       │
│     Agent 3: 根因分析（关联多表定位问题来源）                             │
│     Agent 4: 建议生成（套用 Skill 方法论模板输出建议）                    │
│                                                                         │
│  ✅ 构建品类竞争情报看板                                                  │
│     → 波特五力评分卡（品类级）                                           │
│     → 定位图（价格/评分/销量/毛利率）                                    │
│     → 搜索词份额趋势（`custom_brand_search_query_set`）                 │
│                                                                         │
│  ✅ 构建新品机会雷达                                                      │
│     → 内部空白分析（高搜索量低份额关键词）                               │
│     → 外部趋势验证（VoC + 众筹信号）                                     │
│     → 供应链可行性评估（需外部数据补充）                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 关键成功因素

| 因素 | 说明 |
|------|------|
| **数据质量** | `custom_crawler_listing_snapshot` 等爬虫数据需保持高频更新，否则定位图和 BSR 分析会失真 |
| **标签标准化** | 3-D 标签体系需要预先定义好标签字典，避免 "Crewneck" 和 "Round neck" 被当作不同标签 |
| **规则可配置** | 阈值（如 ACOS>30%, 周转>90天）应支持按品类/平台/国家差异化配置 |
| **人工复核** | Skill 方法论生成的建议需运营专家复核，尤其是涉及价格调整和库存清理的决策 |
| **闭环验证** | 建议执行后，需通过 `date_id` 时序数据追踪效果（如修复后退款率是否下降） |

### 7.3 预期产出清单

| 阶段 | 产出物 | 格式 | 使用场景 |
|------|--------|------|---------|
| Phase 1 | 产品属性 3-D 标签字典 + 销售加权份额表 | Markdown / BI 透视表 | 产品规划会 |
| Phase 1 | 运营建议优先级看板 | BI Dashboard | 运营周会 |
| Phase 1 | ASIN 情感健康度评分卡 | BI Dashboard | 日常监控 |
| Phase 2 | 品类定位气泡图 | Python 图表 / BI | 品类策略会 |
| Phase 2 | 产品机会四象限矩阵 | BI Dashboard | 季度复盘 |
| Phase 2 | 潜力 ASIN 清单 | Markdown / 表格 | 跟卖/扩展决策 |
| Phase 3 | 自动化诊断报告 | 自动邮件 / BI 告警 | 异常响应 |
| Phase 3 | 品类竞争情报看板 | BI Dashboard | 高层汇报 |
| Phase 3 | 新品机会雷达 | BI Dashboard + 报告 | 新品开发会 |

---

## 附录：Skill 与数据集映射速查表

| Skill | 核心复用内容 | 直接映射的数据集 | 需扩展的数据 | 复用难度 |
|-------|-----------|----------------|------------|:-------:|
| `product-attribute-analyzer` | 3-D标签、销售加权份额、Market Portrait | `order_sale_trend_adv_traffic_inv_set`, `query_product_set` | 无 | ⭐ |
| `review-analyst-agent` | 4-Agent流水线、优先级矩阵、行动规划 | `custom_operation_suggest_suggestions_set`, `custom_refund_place_set` | 评论文本数据 | ⭐⭐ |
| `review-summarizer` | 情感分析、Aspect-based分析、Pros/Cons提取 | `custom_crawler_listing_snapshot`, `custom_crawler_listing_trend_set` | 评论文本数据 | ⭐⭐ |
| `competitive-landscape` | 波特五力、定位图、四行动框架、定价矩阵 | `custom_brand_search_catalog_set`, `custom_brand_search_query_set` | 外部竞品数据 | ⭐⭐⭐ |
| `market-insight-product-selection` | 四象限分类、深度搜索协议、VoC验证 | `order_sale_trend_adv_traffic_inv_set`, `custom_asin_sales_traffic_set` | 外部趋势数据 | ⭐⭐⭐ |
| `product-selection` | BSR筛选、消费者痛点映射、众筹信号 | `custom_crawler_listing_snapshot`, `custom_inventory_turnover_wk_cw_set` | 外部众筹/广告数据 | ⭐⭐⭐ |
| `cross-border-selection` | 11核心字段、SKU展开模型、HARD-GATE验证 | `custom_crawler_listing_snapshot`, `query_listing_set` | 无（作为标准规范） | ⭐ |

---

*文档基于 7 个 Skill（`competitive-landscape`、`cross-border-selection`、`market-insight-product-selection`、`product-attribute-analyzer`、`product-selection`、`review-analyst-agent`、`review-summarizer`）的深度拆解，以及 opscli 41 个数据集（1701 字段）的结构分析生成。建议按 Phase 1 → Phase 2 → Phase 3 的顺序逐步落地，优先完成 P0 级复用内容。*
