# AI商品情报分析平台（Amazon Listing Intelligence）规划

## 开发标注

- 当前 Listing Intelligence Skill 仅作为项目开发规范存放在 `opscli/amazon_listing_intelligence/skill/ops-amazon-listing-intelligence/`。
- 暂不放入 `opscli/skills/templates/`，也不写入 `opscli/skills/templates/manifest.json`，避免在服务未成熟前被正式 Skill 模板发现或提前暴露。
- MCP 工具 `amazon_listing_intelligence_spec_must_read` 会读取上述开发目录下的 `SKILL_MCP.md`。

## 项目目标

构建一个基于 AI Agent 的跨境电商商品情报平台。

目标不是简单复刻卖家精灵，而是实现：

```text
Listing分析
+
用户洞察
+
竞品分析
+
市场分析
+
趋势预测
+
优化建议
```

最终输出：

- Listing分析报告
- 竞品分析报告
- 类目分析报告
- 用户画像报告
- AI优化建议

---

# 一、整体路线图

## 第一期（MVP）

目标：

```text
80% 卖家精灵
+
80% Helium10
```

特点：

- 不依赖付费API
- 不依赖账号授权
- 优先使用公开数据
- 快速验证产品价值

---

## 第二期（增强版）

目标：

- 降低爬虫成本
- 增加历史趋势分析
- 增加关键词数据库

引入：

- Amazon PA API
- Reddit API
- TikTok Creative Center

---

## 第三期（商业版）

目标：

构建完整商品情报系统

引入：

- Keepa
- Rainforest
- DataForSEO
- Oxylabs
- TikTok Shop
- Temu

最终形成：

```text
Amazon成交数据
+
TikTok种草数据
+
Temu供应链数据
+
Google趋势数据
+
Reddit需求数据
```

---

# 二、数据源全景表

| 数据源 | 数据内容 | 是否公开 | 是否需要账号 | 是否付费 | 是否需要爬虫 |
|----------|----------|----------|----------|----------|----------|
| Amazon Listing | 标题、Bullet、A+、图片、价格 | ✅ | ❌ | ❌ | ✅ |
| Amazon Search | 搜索排名、广告位、竞品ASIN | ✅ | ❌ | ❌ | ✅ |
| Amazon Review | 评论内容、评分、时间 | ✅ | ❌ | ❌ | ✅ |
| Amazon Q&A | 用户问题、购买顾虑 | ✅ | ❌ | ❌ | ✅ |
| Amazon BSR | 类目排名 | ✅ | ❌ | ❌ | ✅ |
| Google Trends | 搜索趋势 | ✅ | ❌ | ❌ | ❌ |
| Reddit | 用户讨论、需求洞察 | ✅ | ❌ | ❌ | API/爬虫均可 |
| TikTok Shop | 销量、达人、视频 | ✅ | ❌ | ❌ | ✅ |
| Temu | 销量、评论、价格 | ✅ | ❌ | ❌ | ✅ |
| AliExpress | 销量、价格、评论 | ✅ | ❌ | ❌ | ✅ |
| Walmart | 评论、价格、竞品 | ✅ | ❌ | ❌ | ✅ |
| eBay | 历史成交价格 | ✅ | ❌ | ❌ | 部分需要 |

---

# 三、第一期（仅公开数据）

## Amazon Search

抓取：

```text
关键词
排名
ASIN
广告位
价格
评分
评论数
```

用途：

```text
关键词竞争分析
竞品分析
市场分析
```

---

## Amazon Listing

抓取：

```text
Title
Bullet
Description
A+
Images
```

用途：

```text
标题分析
卖点分析
图片分析
SEO分析
```

---

## Amazon Review

抓取：

```text
Review
Star
Date
Country
```

用途：

```text
用户画像
需求分析
痛点分析
评论聚类
```

---

## Amazon Q&A

抓取：

```text
用户提问
品牌回复
```

用途：

```text
用户顾虑
购买障碍
FAQ生成
```

---

## Google Trends

获取：

```text
关键词趋势
季节性
地区热度
```

用途：

```text
趋势预测
选品分析
```

---

## Reddit

获取：

```text
用户讨论
用户吐槽
真实需求
```

用途：

```text
需求发现
JTBD分析
用户语言库
```

---

# 四、爬虫风险评估

## 数据源风险评级

| 平台 | 数据价值 | 反爬强度 | 维护成本 | 推荐等级 |
|--------|--------|--------|--------|--------|
| Google Trends | ⭐⭐⭐⭐ | ⭐ | ⭐ | A+ |
| Reddit | ⭐⭐⭐⭐ | ⭐ | ⭐ | A+ |
| AliExpress | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | A |
| eBay | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | A |
| Walmart | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | B |
| Amazon Listing | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | B |
| Amazon Search | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | B |
| Amazon Review | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | B- |
| Temu | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | C |
| TikTok Shop | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | C |

---

# 五、各平台反爬情况

## Amazon

反爬等级：

⭐⭐⭐⭐⭐

主要检测：

```text
IP信誉
Cookie
浏览器指纹
Canvas
WebGL
行为轨迹
访问频率
```

建议：

第一期只抓：

```text
Listing
Search
前几页Review
```

不要抓：

```text
全量历史Review
```

---

## TikTok Shop

反爬等级：

⭐⭐⭐⭐⭐

检测：

```text
设备指纹
登录状态
行为轨迹
IP信誉
```

建议：

第一期不要接。

---

## Temu

反爬等级：

⭐⭐⭐⭐⭐

特点：

```text
Cloudflare
JS Challenge
动态接口
频繁升级
```

建议：

第三期再接。

---

## AliExpress

反爬等级：

⭐⭐

基本：

```text
Playwright
+
代理IP
```

即可稳定运行。

---

## Reddit

反爬等级：

⭐

最友好平台之一。

优先推荐。

---

## Google Trends

反爬等级：

⭐

官方开放。

最稳定。

---

# 六、技术架构

## 数据采集层

推荐：

```text
Playwright
```

原因：

```text
兼容Amazon
支持动态页面
支持代理
```

---

## 数据存储

推荐：

```text
PostgreSQL
```

核心表：

```text
product
keyword
review
qa
competitor
trend
```

---

## 向量库

推荐：

```text
pgvector
```

存储：

```text
Review Embedding
Q&A Embedding
Keyword Embedding
```

---

# 七、AI Agent架构

## Agent 1：Crawler Agent

负责：

```text
抓取商品
抓取评论
抓取关键词
抓取竞品
```

---

## Agent 2：Parser Agent

负责：

```text
清洗数据
OCR图片
结构化内容
```

---

## Agent 3：Review Insight Agent

负责：

```text
评论聚类
情感分析
痛点分析
需求分析
```

输出：

```text
用户画像
用户痛点
购买动机
```

---

## Agent 4：Keyword Agent

负责：

```text
关键词聚类
搜索意图分析
关键词机会发现
```

---

## Agent 5：Market Agent

负责：

```text
竞品分析
价格带分析
品牌格局分析
```

输出：

```text
市场机会
市场空白
```

---

## Agent 6：Optimization Agent

负责：

```text
标题优化
Bullet优化
A+优化
主图优化建议
```

---

# 八、第二期（账号体系）

## Reddit API

需要：

```text
开发者账号
```

获取：

```text
帖子
评论
点赞
热度
```

---

## TikTok Creative Center

需要：

```text
TikTok账号
```

获取：

```text
热门广告
热门商品
热门素材
```

---

## Amazon PA API

需要：

```text
Amazon Associate账号
```

获取：

```text
价格
图片
品牌
评分
```

---

# 九、第三期（商业API）

## Keepa

价值最高

获取：

```text
BSR历史
价格历史
Review变化
BuyBox
库存变化
```

---

## Rainforest

获取：

```text
Amazon Search
Amazon Product
Amazon Review
```

特点：

```text
无需维护爬虫
```

---

## DataForSEO

获取：

```text
Amazon关键词
Google关键词
搜索量
趋势
```

---

## Oxylabs

获取：

```text
Amazon
TikTok
Temu
Walmart
```

企业级方案。

---

# 十、报告体系设计

## Level 1：Listing Audit

分析：

```text
标题
Bullet
图片
Review
```

对应：

```text
卖家精灵
Helium10
```

---

## Level 2：Conversion Audit

分析：

```text
为什么不转化
```

输出：

```text
CTR
CVR
购买障碍
```

---

## Level 3：Buyer Psychology

分析：

```text
为什么购买
```

输出：

```text
用户画像
核心焦虑
购买动机
```

---

## Level 4：Competitive Positioning

分析：

```text
为什么竞品赢
```

输出：

```text
价格带
品牌格局
市场定位图
```

---

## Level 5：Category Intelligence

分析：

```text
未来应该卖什么
```

输出：

```text
类目趋势
市场机会
新品方向
```

---

# MVP最终建议

优先级：

## S级

```text
Amazon Search
Amazon Listing
Google Trends
Reddit
Keepa（第二期）
```

---

## A级

```text
Amazon Review
AliExpress
TikTok Creative Center
```

---

## B级

```text
Walmart
```

---

## C级

```text
TikTok Shop
Temu
```

---

# 最终目标

打造：

```text
AI Commerce Intelligence Platform
（AI商品情报平台）
```

通过：

```text
Amazon（成交）
+
TikTok（种草）
+
Temu（供应链）
+
Google Trends（趋势）
+
Reddit（需求）
```

输出：

```text
商品分析
竞品分析
用户画像
需求洞察
趋势预测
优化建议
新品机会发现
```
