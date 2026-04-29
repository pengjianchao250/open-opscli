---
name: ops-competitive-intelligence-analyst
description: 将内部销售集中度数据与竞争对手抓取数据和品牌搜索分析相融合。应用波特的五力、定位图和四个行动框架来生成类别级竞争情报仪表板和战略建议。在评估市场进入、分析竞争定位、制定差异化策略、评估品类竞争格局或进行品牌定位分析时使用。
---

# 竞争情报分析师

竞争情报分析师：融合内部品类销售集中度、爬虫竞品数据、品牌搜索分析，应用波特五力 + 定位图 + 四行动框架，输出品类级竞争情报看板与策略建议。

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

- **Porter's Five Forces Scoring**：基于赫芬达尔-赫希曼指数 (HHI) 和市场数据计算五力评分
- **Positioning Map Generation**：生成价格-评分定位图数据，支持气泡大小和颜色维度
- **Four Actions Framework Strategy**：基于定位分析生成 Eliminate/Reduce/Raise/Create 策略
- **Competitor Profiling**：构建竞品画像，包含优劣势分析和战略定位
- **Category Concentration Analysis**：计算品类集中度指标（HHI、CR3、CR5）
- **Market Entry/Exit Recommendations**：基于综合评分给出进入/退出建议

## 工作流程模式

```
┌─────────────────────────────────────────────────────────────┐
│ 三层分析工作流程 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ 第一层：波特五力 │
│  ├── 1.1 计算品类 HHI（赫芬达尔-赫希曼指数）                  │
│  ├── 1.2 评估新进入者威胁（品类增长率 + 新品牌数）             │
│  ├── 1.3 评估供应商议价能力（SKU 集中度）                     │
│  ├── 1.4 评估买方议价能力（价格敏感度 + 评论影响）          │
│  ├── 1.5 评估替代品威胁（跨品类销售数据）                     │
│  └── 1.6 评估现有竞争强度（HHI + 竞品数量/评分）               │
│                                                              │
│ 第二层：定位地图 │
│  ├── 2.1 收集竞品价格/评分/销量数据                           │
│  ├── 2.2 计算自身品类位置                                    │
│  ├── 2.3 生成定位图坐标数据（X=价格, Y=评分, 大小=销量）       │
│  └── 2.4 识别定位空白点和拥挤区域                             │
│                                                              │
│ 第三层：四个行动框架 │
│  ├── 3.1 分析行业默认但客户不价值的功能（Eliminate）           │
│  ├── 3.2 识别可大幅降本的因素（Reduce）                       │
│  ├── 3.3 确定可显着超越行业的因素（Raise）                    │
│  └── 3.4 发现行业从未提供的新价值（Create）                   │
│                                                              │
│  Output: 综合情报看板 + 策略建议报告                           │
└─────────────────────────────────────────────────────────────┘
```

## 决策树：分析方法

```
你想分析什么？
├── 品类级景观
│ ├── 新市场进入→完整的三层分析
│ └── 现有位置 → 第 2 层 + 第 3 层
├── 特定于竞争对手
│ └── 单一竞争对手深度挖掘 → 竞争对手分析 + 第 2 层
└── 战略定位
    └── 差异化战略→聚焦第三层（四个行动）
```

## 分析框架栈

### 第 1 层：波特五力

|力|内部数据|外部数据|得分 (1-5) |
|-------|--------------|---------------|:-----------:|
|新进入者的威胁|品类销售增长|来自爬虫的新品牌计数| 1-5 | 1-5
|供应商的议价能力| SKU集中 |供应商多元化 | 1-5 | 1-5
|买家的议价能力|审查敏感性 |价格弹性| 1-5 | 1-5
|替代品的威胁|跨品类销售 |替代产品趋势| 1-5 | 1-5
|竞争格局|销售集中度（HHI）|竞争对手数量/评级 | 1-5 | 1-5

**HHI 计算：**
```python
def calculate_hhi(market_shares):
    """赫芬达尔-赫希曼指数"""
    return sum(share**2 for share in market_shares) * 10000

# HHI < 1500: 低集中度 (Score: 1-2)
# HHI 1500-2500: 中等集中度 (Score: 3)
# HHI > 2500: 高集中度 (Score: 4-5)
```

### 第二层：定位图

**方面：**
- X 轴：平均价格 (`custom_crawler_listing_snapshot.price`)
- Y 轴：平均评级 (`custom_crawler_listing_snapshot.star`)
- 气泡大小：销量 (`order_sale_trend_set.order_qty`)
- 气泡颜色：毛利率 (`order_sale_trend_adv_traffic_inv_set.gross_profit_percent`)

**数据来源：**
- 内部：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- 外部：`custom_crawler_listing_snapshot` (`ds_pdTYjvLRCadv`)

### 第三层：四个行动框架

定位分析后，应用：
- **消除**：删除行业认为理所当然但客户不重视的功能
- **减少**：减少远低于行业标准的因素
- **加薪**：加薪系数远高于行业标准
- **创造**：创造行业从未提供过的因素

## 数据源

＃＃＃ 内部的
- `custom_brand_search_catalog_set` (`ds_I13gHlcdwevS`)：类别表现
- `custom_brand_search_query_set` (`ds_xsTOkHIpr3ad`)：搜索词表现
- `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)：销售集中度

＃＃＃ 外部的
- `custom_crawler_listing_snapshot` (`ds_pdTYjvLRCadv`)：竞争对手价格/评级/排名
- `custom_crawler_listing_trend_set`：竞争对手趋势

## 输入格式

```json
{
  "category": "Water Bottles",
  "country": "US",
  "time_range": "last_90_days",
  "competitors": "top_10_sellers",
  "analysis_layers": ["porter", "positioning", "four_actions"]
}
```

## 输出格式

```json
{
  "category": "Water Bottles",
  "country": "US",
  "analysis_period": "2024-11-01 ~ 2025-01-31",
  "layer1_porter_five_forces": {
    "new_entrants": {"score": 3, "evidence": "品类年增 25%，但 Top3 占 60%"},
    "supplier_power": {"score": 2, "evidence": "供应商集中度高，但可替代"},
    "buyer_power": {"score": 4, "evidence": "价格敏感，review 影响大"},
    "substitutes": {"score": 2, "evidence": "替代品少（保温杯/塑料杯）"},
    "rivalry": {"score": 4, "evidence": "HHI = 2850，高度集中"},
    "total_score": 15,
    "max_score": 25,
    "attractiveness": "中等吸引力，竞争激烈"
  },
  "layer2_positioning_map": {
    "x_axis": "price",
    "y_axis": "rating",
    "bubbles": [
      {"name": "Our Brand", "x": 45, "y": 4.5, "size": 5000, "color": 0.18, "type": "self"},
      {"name": "Hydro Flask", "x": 89, "y": 4.8, "size": 12000, "color": 0.35, "type": "competitor"},
      {"name": "Amazon Basics", "x": 15, "y": 4.0, "size": 8000, "color": 0.08, "type": "competitor"}
    ],
    "positioning_conclusion": "我们处于中段价格带，上方有高端空间，下方有性价比红海"
  },
  "layer3_four_actions": {
    "eliminate": ["淘汰基础款无特色颜色", "移除过度包装"],
    "reduce": ["降低对大词广告依赖", "减少 SKU 数量"],
    "raise": ["提升保温时长至 24h", "提升品牌搜索占比至 25%", "提升售价至 $55"],
    "create": ["增加温度显示 LED 屏", "开发 App 连接功能", "推出定制化刻字服务"],
    "expected_impact": {
      "gross_margin_improvement": "18% → 28%",
      "brand_search_share": "12% → 25%"
    }
  },
  "recommendation": "GO with differentiation strategy",
  "confidence_score": 0.82
}
```

## 脚本

|脚本 |目的|输入 |输出|
|--------|---------|-------|--------|
| `scripts/competitive_analysis.py` | 执行完整 3-Layer 竞争分析 | category, country, time_range, competitors | 综合竞争情报 JSON |

### 脚本用法

```bash
# 执行完整竞争分析
cat <<'EOF' | python opscli/skills/templates/ops-competitive-intelligence-analyst/scripts/competitive_analysis.py
{
  "category": "Water Bottles",
  "country": "US",
  "time_range": "last_90_days",
  "competitors": "top_10_sellers",
  "analysis_layers": ["porter", "positioning", "four_actions"]
}
EOF
```

## 最佳实践

1. **Always use HHI for concentration measurement** — HHI 是评估市场集中度的黄金标准
2. **Positioning map should include at least 5 competitors + self** — 确保定位图有足够参照
3. **Four Actions must be based on actual cost structure data** — 策略建议需要有内部成本数据支撑
4. **Consider seasonality when analyzing competitor trends** — BSR 和销量数据需考虑季节性波动
5. **Cross-validate external crawler data with internal sales data** — 爬虫数据需与内部数据交叉验证
6. **Brand search share is a leading indicator** — 品牌搜索占比是竞争壁垒的重要先行指标

## 参考文档

- `reference/porter_template.md` — 波特五力评分模板与评分标准
- `reference/dataset_fields_mapping.md` — 数据集字段映射与 payload 模板
