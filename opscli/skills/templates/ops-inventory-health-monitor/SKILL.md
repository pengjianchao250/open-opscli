---
name: ops-inventory-health-monitor
description: 监控库存周转天数、库龄分布和断货风险，识别滞销和缺货 SKU，并生成补货、清仓和调拨建议。适用于管理库存水平、制定补货计划、清理死库存或分析库存周转健康度。
---

# 库存健康监控器

跟踪库存健康指标，并生成可执行的补货、清仓和调拨建议。

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

## 能力范围范围

- 库存周转分析
- 库龄分布跟踪
- 断货风险预测
- 滞销 SKU 识别
- 补货量计算
- 跨仓调拨建议

## 核心指标

| 指标 | 字段 | 健康 | 预警 | 严重 |
|--------|-------|---------|---------|----------|
| 周转天数 | `sell_qty_days` | < 45 | 45-90 | > 90 |
| 可售+在途天数 | `sell_intransit_qty_days` | < 60 | 60-120 | > 120 |
| 平台库存 | `platform_qty` | > 7 天销量 | 3-7 天 | < 3 天 |
| 海外仓可售 | `transfer_available_qty` | > 14 天销量 | 7-14 天 | < 7 天 |
| 锁定库存占比 | `transfer_lock_qty / transfer_qty` | < 20% | 20-50% | > 50% |

## 库存健康评级

```python
# 库存健康度评级（A/B/C/D/F）
def rate_inventory(sell_qty_days, platform_qty, avg_daily_sales):
    platform_days = platform_qty / avg_daily_sales 如果 avg_daily_sales > 0 否则 999

    if sell_qty_days < 45 and platform_days > 14:
        return 'A'  # 健康
    elif sell_qty_days < 60 and platform_days > 7:
        return 'B'  # 良好
    elif sell_qty_days < 90 and platform_days > 3:
        return 'C'  # 一般
    elif sell_qty_days < 120:
        return 'D'  # 预警
    else:
        return 'F'  # 滞销
```

## 数据来源

### 主数据源：custom_inventory_turnover_wk_set（`ds_97zj6R0KDKpB`）
- `ed_sku`：公司 SKU
- `sell_qty_days`：可售周转天数
- `sell_intransit_qty_days`：可售 + 在途周转天数
- `platform_qty`：平台库存
- `transfer_qty`：海外仓库存
- `transfer_available_qty`：海外仓可售库存
- `transfer_lock_qty`：海外仓锁定库存
- `intransit_qty`：在途库存
- `average_daily_sales_volume`：日均销量

### 辅助数据源：order_sale_trend_adv_traffic_inv_set（ds_d35ac6f3910c）
- `total_qty`：全链路总库存
- `fba_qty`：FBA 库存

## 分析维度

### 1. 周转健康度

使用 `custom_inventory_turnover_wk_set`（`ds_97zj6R0KDKpB`）：

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_97zj6R0KDKpB",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.sell_qty_days", "alias": "f_sell_days" },
      { "expr": "CASE WHEN ds_97zj6R0KDKpB.sell_qty_days < 45 THEN 'Healthy' WHEN ds_97zj6R0KDKpB.sell_qty_days < 90 THEN 'Warning' ELSE 'Critical' END", "alias": "f_health_status" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" }
      ]
    },
    "orderBy": [{ "field": "f_sell_days", "direction": "DESC" }],
    "limit": 1000
  }
}
```

### 2. 断货风险

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_97zj6R0KDKpB",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty", "alias": "f_platform_qty" },
      { "expr": "ds_97zj6R0KDKpB.average_daily_sales_volume", "alias": "f_avg_daily_sales" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty / NULLIF(ds_97zj6R0KDKpB.average_daily_sales_volume, 0)", "alias": "f_stock_days" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" },
        { "field": "ds_97zj6R0KDKpB.platform_qty / NULLIF(ds_97zj6R0KDKpB.average_daily_sales_volume, 0)", "operator": "lt", "value": 14 }
      ]
    },
    "orderBy": [{ "field": "f_stock_days", "direction": "ASC" }],
    "limit": 1000
  }
}
```

### 3. 补货量计算
```
补货量 = (目标库存天数 × 日均销量) - (平台库存 + 在途库存 + 海外仓可用库存)

目标库存天数：
- 快消品：45-60 天
- 标品：60-90 天
- 季节性：提前 2-3 个月
```

## 输入格式

- SKU 等级："ed_sku = 'ED-12345'"
- 品类级："category = 'Kitchen'"
- 风险类型："断货风险" 或 "滞销"
- 日期：最新可用日期

## 输出格式

```
【SKU】ED-12345（不锈钢水瓶）
【库存健康评级】D（预警）

库存分布：
┌─────────────────┬──────────┬─────────────┐
│ 位置            │ 数量     │ 覆盖天数    │
├─────────────────┼──────────┼─────────────┤
│ 平台仓 (FBA)    │ 120      │ 8 天 ⚠️    │
│ 海外仓可售      │ 80       │ 5 天 ⚠️    │
│ 海外仓锁定      │ 40       │ —          │
│ 在途            │ 200      │ 13 天      │
├─────────────────┼──────────┼─────────────┤
│ 总计可售        │ 400      │ 26 天      │
│ 总库存          │ 440      │ 29 天      │
└─────────────────┴──────────┴─────────────┘

问题诊断：
⚠️ 平台仓仅剩 8 天库存（健康线 > 14 天）
⚠️ 海外仓锁定比例 33%（健康线 < 20%）

行动建议：
1. [P0] 紧急补货：建议补货 300 件
   → 补货后平台仓覆盖 29 天
   → 预计到货时间：海运 35 天，需在 3 月 15 日前发货

2. [P1] 解锁海外仓库存：调查 40 件锁定原因
   → 预计释放后可售天数 +5 天

3. [P2] 评估在途时效：当前在途 200 件预计 3 月 10 日到港
   → 如时效延迟，考虑空运应急 100 件

【预计销售损失】
如不补货，3 月 20 日后断货，预计损失 $3,500/周
```

## 脚本

- `scripts/calculate_inventory_health.py`：计算库存健康评级和风险识别结果
- `scripts/generate_replenishment_plan.py`：生成补货数量与时机建议

## 使用方式

### 第一步：查询数据

使用 opscli query 命令获取库存数据：

```bash
# 构造库存周转查询 payload
opscli query build \
  --dataset ds_97zj6R0KDKpB \
  --dimension ed_sku --dimension product_name \
  --metric sell_qty_days --metric platform_qty --metric transfer_available_qty \
  --metric transfer_lock_qty --metric intransit_qty --metric average_daily_sales_volume \
  --output payload_inventory.json

# 执行查询
opscli query run --payload payload_inventory.json
```

### 第二步：执行分析

```bash
# 库存健康度计算
echo '{"sku": "ED-12345", "inventory": {...}, "sales": {...}}' | python scripts/calculate_inventory_health.py

# 补货计划生成
echo '{"sku_data": {...}, "target_days": 60, "lead_time_days": 35}' | python scripts/generate_replenishment_plan.py
```

## 最佳实践

1. 在补货计算中始终考虑在途库存
2. 标记锁定库存并调查原因
3. 使用 30 天滚动平均销量平滑波动
4. 季节性产品需要调整目标库存天数
5. 使用 `opscli query build` 构造 payload，而不是手写 SQL
