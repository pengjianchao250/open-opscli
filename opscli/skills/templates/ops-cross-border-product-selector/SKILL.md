---
name: ops-cross-border-product-selector
description: 整合内部销售数据、爬虫 Listing 数据和库存周转指标，应用 BSR 健康度筛选、四象限分类和众筹信号挖掘，构建数据驱动的新产品开发决策体系。适用于探索新品机会、评估竞品 ASIN 是否适合跟卖、进行新品开发 GO/NO-GO 决策或扫描品类机会。
---

# 跨境选品决策助手

跨境选品决策系统：整合内部销售数据、爬虫 Listing 数据、库存周转数据，应用 BSR 健康度筛选 + 四象限分类 + 众筹信号挖掘，构建数据驱动的新品开发决策系统。

## 强制认证与环境门禁

进入本 Skill 后，必须先完成环境与认证检查；检查通过前，禁止直接开始抓取、查询、运行脚本或读取数据样本。

强制顺序如下：

1. 检测是否安装 `aukeys-opscli` Python 发行包
2. 检测 `opscli` 命令是否可执行
3. 检测 `opscli query --help` 是否成功，用于确认查询能力可用
4. 检测当前是否已完成授权登录
5. 只有 `dist_ok=true`、`opscli_ok=true`、`query_ok=true`、`auth_ok=true` 时，才允许继续本 Skill
6. 任一检查失败，都必须立即停止当前 Skill，先使用 `ops-auth` 完成登录，或先安装 `aukeys-opscli`

推荐检测脚本：

```bash
python - <<'PY'
from importlib import metadata
import json
import shutil
import subprocess

dist_ok = False
opscli_ok = False
query_ok = False
auth_ok = False

try:
    metadata.version("aukeys-opscli")
    dist_ok = True
except metadata.PackageNotFoundError:
    pass

opscli_ok = shutil.which("opscli") is not None
if opscli_ok:
    query_ok = subprocess.run(
        ["opscli", "query", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

if dist_ok:
    try:
        from opscli import AuthClient
        auth_ok = AuthClient().is_authenticated()
    except Exception:
        auth_ok = False

print(json.dumps({
    "dist_ok": dist_ok,
    "opscli_ok": opscli_ok,
    "query_ok": query_ok,
    "auth_ok": auth_ok,
    "ready": dist_ok and opscli_ok and query_ok and auth_ok,
}, ensure_ascii=False))
PY
```

禁止事项：

- 禁止跳过认证检查，直接执行 `opscli query build`、`opscli query run` 或任意抓取命令
- 禁止在未登录状态下直接运行本 Skill 的分析脚本
- 禁止手写、复用或拼接过期 Token 绕过 `ops-auth`

## 能力范围

- **BSR 健康度筛选**：基于 BSR 排名、评论数、评分、价格筛选候选 ASIN
- **四象限产品分类**：将产品分类为 稳健机会 / 高潜机会 / 红海市场 / 虚假趋势
- **内部能力缺口分析**：评估内部供应链能力与品类的匹配度
- **竞品 ASIN 评估**：评估单个竞品 ASIN 的跟卖/改进价值
- **众筹信号监控**：监控众筹平台新品信号（可选）
- **供应商匹配**：匹配潜在供应商（可选）

## 工作流模式

```
┌─────────────────────────────────────────────────────────────┐
│                四步选品工作流                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  步骤 1：品类扫描（品类扫描）                            │
│  ├── 1.1 查询内部品类销售数据（ds_d35ac6f3910c）              │
│  ├── 1.2 查询外部爬虫品类数据（ds_pdTYjvLRCadv）              │
│  ├── 1.3 计算品类集中度指标（HHI, CR3, CR5）                 │
│  └── 1.4 识别高潜力品类（高增长 + 低集中度）                  │
│                                                              │
│  步骤 2：BSR 健康度筛选（BSR 健康度筛选）                  │
│  ├── 2.1 应用 BSR 筛选规则（标准/宽松/严格）                 │
│  ├── 2.2 过滤候选 ASIN（BSR 100-5000，评论数 300-1000）     │
│  ├── 2.3 计算候选 ASIN 的评分缺口（我们可超越的空间）          │
│  └── 2.4 标记季节性风险 ASIN                                 │
│                                                              │
│  步骤 3：四象限分类（四象限分类）            │
│  ├── 3.1 获取内部销售数据（销售额、退款率）                   │
│  ├── 3.2 获取外部评论情感数据（好评/差评占比）                 │
│  ├── 3.3 计算品类中位数分界线                                │
│  └── 3.4 分类到四个象限                                      │
│                                                              │
│  步骤 4：机会评分（机会评分）                      │
│  ├── 4.1 计算市场规模评分（BSR 反推）                        │
│  ├── 4.2 计算毛利潜力评分（价格 - 预估成本）                  │
│  ├── 4.3 计算竞争缺口评分（评论数/评分差距）                  │
│  ├── 4.4 计算内部能力匹配度                                  │
│  └── 4.5 综合评分排序，输出 Top N 机会                       │
│                                                              │
│  输出：选品机会报告 + 进入/放弃建议                        │
└─────────────────────────────────────────────────────────────┘
```

## 决策树：选品策略

```
你的选品目标是什么？
├── 探索某个品类中的新机会
│   └── 执行完整四步工作流并包含品类扫描
├── 评估某个具体竞品 ASIN
│   └── 跳过步骤 1，直接对单个 ASIN 执行步骤 2-4
├── 低风险跟卖
│   └── 使用严格 BSR 筛选 + 仅保留稳健机会象限
├── 抢先布局 / 差异化
│   └── 使用宽松 BSR 筛选 + 聚焦高潜力象限
└── 验证内部能力匹配度
    └── 重点关注步骤 4 的能力评分
```

## 四步选品工作流详情

### 第一步：品类扫描

**内部数据**（`order_sale_trend_adv_traffic_inv_set` / `ds_d35ac6f3910c`）：
- 品类销售额、ASIN 数量、平均毛利率、平均退款率

**外部数据**（`custom_crawler_listing_snapshot` / `ds_pdTYjvLRCadv`）：
- 竞品数量、平均评分、平均评论数

### 第二步：BSR 健康度筛选

**筛选规则：**

| 条件 | 标准 | 宽松（探索） | 严格（保守） |
|----------|----------|---------------------|----------------------|
| BSR 排名 | 100-5,000 | 50-10,000 | 500-3,000 |
| 评论数 | 300-1,000 | 100-2,000 | 500-800 |
| 评分 | 3.5-4.3 | 3.0-4.5 | 3.8-4.2 |
| 价格 | $15-50 | $10-80 | $20-40 |

### 第三步：四象限分类

**坐标轴：**
- X 轴：销售额（内部 `original_price`）
- Y 轴：退款/差评率（内部 `refund_percent` + 外部评论情绪）

| 象限 | 内部信号 | 外部信号 | 策略 |
|----------|----------------|-----------------|----------|
| 🟢 稳健机会 | 高销量、低退款 | 高评分、BSR 稳定 | 小幅改进后跟卖 |
| 🟡 高潜机会 | 低销量或尚未布局 | 搜索趋势高、卖家少 | 抢先进入机会 |
| 🔴 红海市场 | 高销量、高退款 | 竞争者多、价格战激烈 | 回避或强差异化 |
| ⚫ 虚假趋势 | 短期暴涨后回落 | 热度短暂 | 忽略 |

### 第四步：机会评分

**评分公式：**
```python
机会分数 = (
    w1 * market_size_score +       # 市场规模 (BSR rank inverse)     [权重 0.25]
    w2 * margin_potential_score +  # 毛利潜力 (price - estimated cost) [权重 0.30]
    w3 * competition_gap_score +   # 竞争缺口 (reviews gap)           [权重 0.20]
    w4 * internal_capability_score # 内部能力匹配度                   [权重 0.15]
    w5 * pain_point_severity       # 痛点严重程度                     [权重 0.10]
)
```

## 输入格式

```json
{
  "category": "Kitchen Gadgets",
  "country": "US",
  "bsr_range": [100, 5000],
  "price_range": [15, 50],
  "review_range": [300, 1000],
  "rating_range": [3.5, 4.3],
  "filter_mode": "standard",
  "internal_capability": {
    "has_motor_supply_chain": true,
    "existing_categories": ["Kitchen", "Home"],
    "exclude_categories_with_asin_count_gt": 50
  },
  "top_n": 5
}
```

## 输出格式

```json
{
  "category": "Kitchen Gadgets",
  "filter_criteria": {
    "bsr_range": [100, 5000],
    "price_range": [15, 50],
    "review_range": [300, 1000],
    "rating_range": [3.5, 4.3]
  },
  "candidate_count": 23,
  "top_opportunities": [
    {
      "rank": 1,
      "asin": "B08XXXXXX",
      "product_name": "电动蒜泥器",
      "bsr": 1250,
      "price": 29.99,
      "rating": 3.9,
      "reviews": 847,
      "quadrant": "high_potential",
      "quadrant_label": "🟡 高潜力",
      "opportunity_score": 87,
      "market_size_estimate": 2300000,
      "competition_gap": "Top 10 卖家平均 rating 3.8，我们可达 4.5+",
      "internal_capability_match": true,
      "capability_reason": "已有电机供应链（搅拌机产品线）",
      "estimated_margin_percent": 35,
      "estimated_cost": 8.0,
      "recommendation": "建议进入",
      "timeline_estimate": "3个月上市"
    }
  ],
  "risk_warnings": [
    {
      "asin": "B08AAAAAA",
      "product_name": "低价红海产品",
      "quadrant": "red_ocean",
      "warning": "已有 200+ 卖家，价格战激烈，平均毛利率仅 8%",
      "recommendation": "建议放弃"
    }
  ],
  "quadrant_distribution": {
    "safe_bet": 5,
    "high_potential": 12,
    "red_ocean": 4,
    "false_trend": 2
  }
}
```

## 脚本

| 脚本 | 用途 | 输入 | 输出 |
|--------|---------|-------|--------|
| `scripts/product_selector.py` | 执行完整 4-Step 选品工作流 | category, filter criteria, internal capability | 选品机会报告 JSON |

### 脚本使用方式

```bash
# 执行完整选品流程
cat <<'EOF' | python opscli/skills/templates/ops-cross-border-product-selector/scripts/product_selector.py
{
  "category": "Kitchen Gadgets",
  "country": "US",
  "filter_mode": "standard",
  "internal_capability": {
    "has_motor_supply_chain": true,
    "existing_categories": ["Kitchen", "Home"],
    "exclude_categories_with_asin_count_gt": 50
  },
  "top_n": 5
}
EOF
```

## 最佳实践

1. **有条件时始终用真实销售数据交叉验证 BSR**——BSR 可能因季节性波动而失真
2. **考虑季节性**——BSR 对季节性产品可能产生误导
3. **内部能力匹配非常关键**——不要推荐超出供应链能力范围的产品
4. **标记存在专利/IP 风险的产品**——选品时需规避专利风险
5. **跟卖使用严格筛选，探索使用宽松筛选**——保守跟卖用严格规则，新品探索用宽松规则
6. **痛点严重度是关键差异化因素**——差评痛点分析是差异化机会的重要来源

## 参考文档

- `reference/bsr_filtering_rules.md` — BSR 筛选规则详解（标准/宽松/严格三档）
- `reference/quadrant_matrix_guide.md` — 四象限分类指南与策略建议
- `reference/dataset_fields_mapping.md` — 数据集字段映射与 payload 模板
