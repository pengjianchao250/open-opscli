---
name: ops-product-attribute-analyzer
description: 应用三维产品属性标签体系（结构/版型、材料/工艺、设计元素）计算各属性组​​合的销量加权市场份额，识别供给不足的高价值属性机会。适用于规划产品开发、分析品类趋势、优化 SKU 组合或研究市场属性偏好。
---

# 产品属性分析器

通过三维标签体系和销量加权市场份额分析产品属性，为产品开发决策提供依据。

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

- 三维属性标签化与标准化
- 销量加权市场份额计算
- 属性组合排序与机会识别
- 市场画像生成
- 供给不足机会识别

## 三维标签体系

### 维度 1：开发与结构
映射到 `query_product_set` 的字段：
- `development_type`: 自主研发 / OEM贴牌 / 外采成品
- `sku_type`: A级 / B级 / C级
- `style_name`: 风格化名称
- `protection_level`: 保护等级

### 维度 2：品类与型号
- `category`: 一级品类
- `sec_category`: 二级品类
- `model`: 产品型号
- `pmc_type`: 物控编码等级

### 维度 3：渠道与等级
- `level_name`: 产品等级
- `platform_name`: 平台
- `country_name`: 国家
- `channel_name`: 渠道

## 销量加权市场份额公式

```
市场份额（属性 X）=
    当属性 = X 时的 SUM(order_qty)
    ─────────────────────────────────────
    全部样本的 SUM(order_qty)
```

不是看 count(ASIN)——销量比 SKU 数量更重要。

## 属性组合分析

分析 2-3 个属性交叉组合，寻找供需缺口：

```sql
SELECT
    开发类型，
    sku_类型，
    SUM(订单数量) 作为总销售额，
    COUNT(DISTINCT asin) as asin_count,
    SUM(订单数量) * 1.0 / SUM(SUM(订单数量)) OVER() 作为市场份额，
    SUM(order_qty) * 1.0 / COUNT(DISTINCT asin) 作为 sales_per_asin
FROM order_sale_trend_adv_traffic_inv_set
WHERE date_id >= '{start_date}'
GROUP BY development_type, sku_type
ORDER BY market_share DESC;
```

## 机会识别

以下情况应标记为机会：
- `sales_per_asin` > 品类平均值的 150%
- `market_share` < 20%，但单 ASIN 销量很高
- `asin_count` 较低，但 `total_sales` 很高

→ 表示存在供给不足机会

## 输入格式

- 品类级："category = 'Kitchen Gadgets'"
- 维度选择："按 development_type + sku_type 分析"
- 日期范围："最近 90 天"
- 过滤条件："country_name = 'US'"

## 输出格式

```
【品类】Kitchen Gadgets
【分析周期】2024-11-01 ~ 2025-01-31
【样本】156 个 ASIN，总销量 45,200

维度 1：开发类型
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ 属性标签        │ ASIN 数量 │ 总销量      │ 市场份额   │ 单 ASIN 销量 │
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ 自主研发        │ 45       │ $890,000    │ 52.3%      │ $19,778 ⭐   │
│ OEM贴牌         │ 78       │ $620,000    │ 36.4%      │ $7,949      │
│ 外采成品        │ 33       │ $192,000    │ 11.3%      │ $5,818      │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘
→ 机会：自主研发产品数量少（29%）但贡献 52% 销售额，单均销量最高。
   建议：增加自主研发 SKU 占比。

维度 2：SKU 等级
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ 属性标签        │ ASIN 数量 │ 总销量      │ 市场份额   │ 单 ASIN 销量 │
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ A级             │ 23       │ $720,000    │ 42.3%      │ $31,304 ⭐   │
│ B级             │ 56       │ $580,000    │ 34.1%      │ $10,357      │
│ C级             │ 77       │ $402,000    │ 23.6%      │ $5,221      │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘
→ 机会：A级 SKU 数量仅占 15%，但贡献 42% 销售额。
   建议：将 B/C 级中表现好的产品（销售额 > $15k）升级为 A 级资源投入。

组合分析：开发类型 × SKU 等级
┌─────────────────┬──────────┬─────────────┬────────────┐
│ 组合            │ ASIN 数量 │ 市场份额   │ 单 ASIN 销量 │
├─────────────────┼──────────┼─────────────┼────────────┤
│ 自主研发 + A级   │ 12       │ 35.2%       │ $42,100 ⭐ │
│ 自主研发 + B级   │ 25       │ 14.8%       │ $15,200   │
│ OEM + A 线 │ 8 │ 5.1% │ $18,900 │
└─────────────────┴──────────┴─────────────┴────────────┘
→ 最高价值组合：自主研发 + A级（供需比最低）

市场画像：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 市场偏好主流原型：
   自主研发 + A级 + US站 + FBA
   → 占品类销售额 32%，仅 8% ASIN 数量
   → 供给严重不足，建议加大开发投入
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 脚本

- `scripts/calculate_weighted_share.py`：计算单个维度的销量加权市场份额
- `scripts/analyze_attribute_combo.py`：分析属性组合机会
- `scripts/generate_market_portrait.py`：生成市场画像摘要报告

## 使用方式

### 第一步：查询数据

使用 opscli query 命令获取属性和销量数据：

```bash
# 构造查询 payload（属性维度）
opscli query build \
  --dataset ds_8f24440d149b \
  --dimension development_type --dimension sku_type \
  --dimension category --dimension sec_category \
  --output payload_product.json

# 构造查询 payload（销量数据）
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension development_type --dimension sku_type \
  --metric order_qty --metric original_price \
  --output payload_sales.json

# 执行查询
opscli query run --payload payload_sales.json
```

### 第二步：执行分析

```bash
# 单维度销售加权份额计算
echo '{"dimension": "development_type", "data": [...]}' | python scripts/calculate_weighted_share.py

# 属性组合机会分析
echo '{"combo_data": [...], "threshold_ratio": 1.5}' | python scripts/analyze_attribute_combo.py

# 生成市场画像
echo '{"category": "Kitchen", "shares": [...], "opportunities": [...]}' | python scripts/generate_market_portrait.py
```

## 最佳实践

1. 始终使用销量加权份额，不要使用 ASIN 数量份额
2. 比较 sales_per_asin 以识别供给不足机会
3. 使用 90 天滚动数据平滑季节性影响
4. 过滤销量少于 10 的 ASIN，避免噪音干扰
5. 使用 `opscli query build` 构造 payload，不要手写 SQL
