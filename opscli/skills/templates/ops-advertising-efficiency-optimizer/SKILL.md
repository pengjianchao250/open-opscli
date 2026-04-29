---
name: ops-advertising-efficiency-optimizer
description: 跨广告系列、广告组和广告类型 (SP/SD/SB/SBV) 维度分析广告效率。识别高 ACOS 问题并生成字级、活动级和时间段优化建议。当 ACOS 高于目标、重新分配广告预算、比较广告类型效果或诊断广告浪费时使用。
---

# 广告效率优化器

诊断广告效果问题并生成跨多个维度的优化策略。

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

- 活动级 ACOS 诊断
- 广告类型对比（SP、SD、SB、SBV）
- 关键词效果分析
- 预算重新分配建议
- 时间段有效性分析
- ROAS 与 CPC 趋势跟踪

## 核心指标

| 指标 | 公式 | 健康 | 预警 | 严重 |
|--------|---------|---------|---------|----------|
| ACOS | 广告成本 / 广告销售额 | < 20% | 20-30% | > 30% |
| ROAS | 广告销售额 / 广告成本 | > 5.0 | 3.3-5.0 | < 3.3 |
| CPC | 广告成本 / 点击量 | < $1.5 | $1.5-2.5 | > $2.5 |
| CTR | 点击量 / 曝光量 | > 0.3% | 0.2-0.3% | < 0.2% |
| 转化率 | 订单数 / 点击量 | > 10% | 5-10% | < 5% |

## 广告类型比较框架

### 商品推广广告（SP）
- **关注重点**：关键词定向、商品定向
- **关键指标**：ACOS、CPC、关键词排名提升
- **优化方向**：否定关键词、竞价调整、匹配类型

### 品牌推广广告（SB）
- **关注重点**：品牌认知、店铺流量
- **关键指标**：展示份额、新品牌率
- **优化方向**：创意 A/B 测试、标题优化

### 展示型推广广告（SD）
- **关注重点**：重定向、人群定向
- **关键指标**：可见展示次数、再营销点击率
- **优化方向**：人群分层、版位竞价

### 品牌视频广告（SBV）
- **关注重点**：视频互动、品牌叙事
- **关键指标**：视频观看率、参与率
- **优化方向**：视频创意、定向优化

## 分析维度

### 1. 活动级诊断

使用 `advertising_list_set`（`ds_0759e20F0DrG`，子查询类型）：

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_advertising.list_set ... WHERE ... {and_sub_placeholder_1} ...)",
      "alias": "ds_0759e20F0DrG",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_0759e20F0DrG.campaign_name", "alias": "f_campaign" },
      { "expr": "ds_0759e20F0DrG.ad_group_name", "alias": "f_ad_group" },
      { "expr": "ds_0759e20F0DrG.ads_type", "alias": "f_ad_type" },
      { "expr": "SUM(ds_0759e20F0DrG.advertising_fee)", "alias": "f_cost" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_sales_cny)", "alias": "f_sales" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_clicks)", "alias": "f_clicks" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_impressions)", "alias": "f_impressions" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_conversions)", "alias": "f_conversions" }
    ],
    "innerWhere": [
      { "operator": "AND", "conditions": [] },
      { "operator": "AND", "conditions": [
        { "field": "ds_0759e20F0DrG.campaign_name", "operator": "eq", "value": "Water-Bottle-SP-Exact" }
      ]}
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_0759e20F0DrG.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_campaign", "f_ad_group", "f_ad_type"],
    "limit": 1000
  }
}
```

### 2. 广告类型组合分析

使用 `custom_sp_ads_set`（`ds_fE0flP7WonsJ`，非子查询类型）：

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_fE0flP7WonsJ",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_fE0flP7WonsJ.ad_type", "alias": "f_ad_type" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sp)", "alias": "f_sp_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sd)", "alias": "f_sd_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sb)", "alias": "f_sb_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sbv)", "alias": "f_sbv_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sales_cny)", "alias": "f_total_sales" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_fE0flP7WonsJ.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ad_type"],
    "limit": 1000
  }
}
```

### 3. 预算重新分配逻辑

当营销活动的 ACOS > 30% 时：
1. 降低出价10-20%
2.为高支出/低转化词添加否定关键词
3. 暂停 ACOS > 50% 的匹配类型
4. 将预算重新分配给 ROAS > 5.0 的广告系列

## 输入格式

- ASIN 级别：“B08XXXXXX”
- 活动级别：“campaign_name = 'Water-Bottle-SP-Exact'”
- 广告类型：“分析 SP 与 SB”
- 日期范围：“过去 30 天”

## 输出格式

```
【分析对象】ASIN B08XXXXXX（保温水瓶）
【分析周期】2025-01-01 ~ 2025-01-31
【总广告费】$8,500 | 【总广告销售额】$35,000 | 【综合 ACOS】24.3%

广告类型对比：
┌──────────┬─────────┬───────────┬───────┬────────┐
│ 广告类型 │ 支出 │ 销售 │ ACOS │ ROAS │
├──────────┼─────────┼───────────┼───────┼────────┤
│ SP       │ $5,200  │ $22,000   │ 23.6% │ 4.23   │
│ SB       │ $2,100  │ $10,000   │ 21.0% │ 4.76   │
│ SD       │ $1,000  │ $2,500    │ 40.0% │ 2.50 🔴│
│ SBV │ $200 │ $500 │ 40.0% │ 2.50 🔴│
└──────────┴─────────┴───────────┴───────┴────────┘

问题诊断：
🔴 SD 广告 ACOS 40%（目标 < 25%）
   └─ 原因：受众定位过宽，展示量高但转化低
   └─ 建议：缩小受众范围，暂停低转化受众组

🔴 SBV 广告 ACOS 40%
   └─ 原因：视频完播率仅 15%（均值 35%）
   └─ 建议：前 3 秒加入产品核心卖点，缩短视频至 15 秒

优化建议（按预期 ROI 排序）：
1. [P0] 暂停 SD 受众组 "Broad-Interest"（月节省 $400）
2. [P0] 将 SBV 视频前 3 秒改为 "Keep Cold 24h"（预计完播率提升至 30%）
3. [P1] SP 大词 "water bottle" 降低竞价 15%（ACOS 从 28% 降至 23%）
4. [P1] 将节省的 $600 预算转移至 SP 长尾词组（预期 ROAS 6.0+）

预期效果：
→ 综合 ACOS 从 24.3% 降至 20.5%
→ 月广告利润增加 $1,200
```

## 脚本

- `scripts/analyze_ads_efficiency.py`：活动诊断的主要分析脚本
- `scripts/calculate_roas_acos.py`：快速 ROAS/ACOS 计算器
- `scripts/ads_budget_allocator.py`：预算重新分配优化器

## 如何使用

### 第1步：查询数据

使用 opscli 查询命令获取广告数据：

```bash
# 构造广告活动级查询 payload（子查询类型）
opscli query build \
  --dataset ds_0759e20F0DrG \
  --dimension campaign_name --dimension ad_group_name --dimension ads_type \
  --metric advertising_fee --metric ads_sales_cny --metric ads_clicks --metric ads_impressions \
  --output payload_ads.json

# 构造广告类型组合查询 payload
opscli query build \
  --dataset ds_fE0flP7WonsJ \
  --dimension ad_type \
  --metric ads_sp --metric ads_sd --metric ads_sb --metric ads_sales_cny \
  --output payload_ad_type.json

# 执行查询
opscli query run --payload payload_ads.json
```

### 第 2 步：运行分析

```bash
# 广告效率诊断
echo '{"campaigns": [...], "benchmarks": {...}}' | python scripts/analyze_ads_efficiency.py

# ROAS/ACOS 快速计算
echo '{"cost": 1000, "sales": 5000}' | python scripts/calculate_roas_acos.py

# 预算重新分配
echo '{"campaigns": [...], "total_budget": 10000}' | python scripts/ads_budget_allocator.py
```

## 最佳实践

1. 始终在广告系列+广告组级别进行分析，而不仅仅是帐户级别
2. 将 ACOS 与类别基准进行比较，而不仅仅是绝对目标
3. 对于新营销活动（< 14 天），使用宽松的阈值
4. 在评估品牌活动时考虑有机销售提升
5. 使用`opscli query build`构造payloads，而不是手动编写SQL
