---
name: ops-profit-structure-analyzer
description: None
  拆解 ASIN / 品类 / 团队层级的成本结构，识别利润压缩点，
  并应用 Eliminate / Reduce / Raise / Create 四行动框架生成
  可量化的优化策略。触发场景包括：利润结构分析、成本拆解、
  低毛利、降本、成本结构对比、四行动框架、亏损诊断、利润优化。
---

# 利润结构分析器

将销售额分解为 8 个成本类别，通过与内部基准对比识别偏离项，并应用四行动框架（Eliminate/Reduce/Raise/Create）生成可量化的利润优化策略。

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

- **单 ASIN 成本结构拆解**：输入 ASIN，输出完整成本结构瀑布图与偏离分析
- **品类/团队级横向对比**：对比不同品类或团队的成本结构差异，定位异常项
- **基准偏离度分析**：对比内部基准（团队/品类均值），标记偏离程度（正常 / 警告 / 严重）
- **四行动策略生成**：根据偏离项自动映射到 Eliminate/Reduce/Raise/Create 并输出具体行动建议
- **趋势分析**：支持多时间段的成本结构变化追踪
- **预期效果量化**：估算执行策略后的毛利率提升区间与月度节省金额

## 成本结构类别

基于 `order_sale_trend_adv_traffic_inv_set`（`ds_d35ac6f3910c`）数据集字段：

| 成本项 | 字段名 | 优化方向 | 可优化性 |
|--------|--------|---------|---------|
| 采购成本 | `purchase_cost_percent` | Reduce | 高 |
| 头程运费 | `first_leg_percent` | Reduce | 高 |
| 运费 | `freight_percent` | Reduce | 中 |
| 仓租 | `storage_charges_percent` | Reduce / Eliminate | 高 |
| 广告费 | `advertising_fee_percent` | Reduce | 高 |
| 平台手续费 | `fee_percent` | —（固定） | 无 |
| 税金 | `tax_fee_percent` | —（固定） | 无 |
| 固定成本 | `fixed_cost_percent` | —（固定） | 无 |
| 退款/赔偿 | `refund_percent` + `compensate_percent` | Eliminate | 高 |

## 四行动框架

### Eliminate（消除）
- 清理库龄 > 90 天的滞销库存
- 修复导致高退款率的质量问题
- 淘汰毛利率连续 3 月 < 0% 的 SKU

### Reduce（降低）
- 谈判降低采购成本
- 优化头程物流方案
- 降低广告 ACOS
- 合并发货降低运费

### Raise（提升）
- 提升售价（基于竞品价格带分析）
- 增加品牌溢价
- 提高客单价（配件包/套装）

### Create（创造）
- 开发差异化功能避开价格战
- 拓展高毛利变体/颜色/尺寸
- 开发私模产品提升壁垒

## 输入格式

```json
{
  "target": {
    "type": "asin",
    "value": "B08XXXXXX",
    "name": "蓝牙耳机"
  },
  "period": {
    "start": "2025-01-01",
    "end": "2025-01-31"
  },
  "cost_structure": {
    "purchase_cost_percent": 0.285,
    "first_leg_percent": 0.082,
    "freight_percent": 0.0,
    "storage_charges_percent": 0.055,
    "advertising_fee_percent": 0.22,
    "fee_percent": 0.15,
    "tax_fee_percent": 0.08,
    "fixed_cost_percent": 0.03,
    "refund_percent": 0.068,
    "compensate_percent": 0.0
  },
  "benchmark": {
    "purchase_cost_percent": 0.25,
    "first_leg_percent": 0.065,
    "advertising_fee_percent": 0.18,
    "storage_charges_percent": 0.04,
    "refund_percent": 0.035
  },
  "sales_amount": 29990
}
```

### 字段说明

- `target.type`: 分析对象类型，可选 `asin` / `category` / `team`
- `target.value`: 分析对象标识值
- `target.name`: 分析对象名称（可选，用于输出展示）
- `period`: 分析时间范围
- `cost_structure`: 当前成本结构百分比（0~1 小数）
- `benchmark`: 对比基准百分比（可选，不传则使用内部默认值）
- `sales_amount`: 分析周期内销售额（用于计算月度节省金额）

## 输出格式

脚本输出 JSON：

```json
{
  "target": "B08XXXXXX",
  "target_name": "蓝牙耳机",
  "gross_profit_percent": 0.03,
  "period": "2025-01-01 ~ 2025-01-31",
  "deviations": [
    {
      "item": "advertising_fee_percent",
      "item_cn": "广告费",
      "current": 0.22,
      "benchmark": 0.18,
      "deviation": 0.04,
      "severity": "critical",
      "action_category": "Reduce",
      "expected_saving_percent": 0.04
    }
  ],
  "four_actions": {
    "eliminate": ["清理库龄 > 90 天滞销库存", "修复充电口松动导致的 6.8% 退款率"],
    "reduce": ["将广告 ACOS 从 22% 优化至 18%", "头程运费占比从 8.2% 降至 7%"],
    "raise": ["提升售价 10%（当前 $29.99，竞品区间 $35-45）"],
    "create": ["增加主动降噪功能，避开价格战"]
  },
  "expected_impact": {
    "current_margin": 0.03,
    "target_margin_low": 0.15,
    "target_margin_high": 0.18,
    "monthly_value": 3600
  }
}
```

### 终端表格输出示例

```
【分析对象】ASIN B08XXXXXX（蓝牙耳机）
【分析周期】2025-01-01 ~ 2025-01-31
【销售额】$29,990

成本结构拆解：
┌─────────────────────┬──────────┬──────────┬─────────────┐
│ 成本项              │ 当前值   │ 基准值   │ 偏离值      │
├─────────────────────┼──────────┼──────────┼─────────────┤
│ 采购成本            │ 28.5%    │ 25.0%    │ +3.5% ⚠️   │
│ 头程运费            │ 8.2%     │ 6.5%     │ +1.7% ⚠️   │
│ 平台手续费          │ 15.0%    │ 15.0%    │ —          │
│ 广告费              │ 22.0%    │ 18.0%    │ +4.0% 🔴   │
│ 仓租                │ 5.5%     │ 4.0%     │ +1.5% ⚠️   │
│ 税金                │ 8.0%     │ 8.0%     │ —          │
│ 固定成本            │ 3.0%     │ 3.0%     │ —          │
│ 退款/赔偿           │ 6.8%     │ 3.5%     │ +3.3% 🔴   │
├─────────────────────┼──────────┼──────────┼─────────────┤
│ 毛利率              │ 3.0%     │ 17.0%    │ -14.0% 🔴  │
└─────────────────────┴──────────┴──────────┴─────────────┘

四行动策略：
【排除】
  1. 清理库龄 > 90 天滞销库存（预计减少仓租 1.5%）
  2. 修复充电口松动导致的 6.8% 退款率（预计降至 3.5%）

【减少】
  1. 将广告 ACOS 从 22% 优化至 18%（预计节省 $1,200/月）
  2. 头程运费占比从 8.2% 降至 7%（货量整合谈判）

【增加】
  1. 提升售价 10%（当前 $29.99，竞品区间 $35-45）

【创造】
  1. 增加主动降噪功能，避开价格战

【预期效果】
  执行后毛利率可从 3% 提升至 15-18%
```

## 脚本

- `scripts/analyze_cost_structure.py`：接收成本结构 JSON，计算偏离度，应用四行动框架生成策略，输出 JSON

### 使用方式

```bash
# 通过管道传入 JSON
cat input.json | python opscli/skills/templates/ops-profit-structure-analyzer/scripts/analyze_cost_structure.py

# 或通过 echo 传入测试数据
echo '{"target":{"type":"asin","value":"B08XXXXXX","name":"蓝牙耳机"},...}' | \
  python opscli/skills/templates/ops-profit-structure-analyzer/scripts/analyze_cost_structure.py
```

## 数据查询

### 数据集信息

| 数据集 | ID | 类型 |
|--------|-----|------|
| order_sale_trend_adv_traffic_inv_set | `ds_d35ac6f3910c` | 非子查询 |

### 推荐查询方式

使用 `opscli query build` 命令自动生成查询 payload：

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric original_price --metric purchase_cost_percent --metric first_leg_percent \
  --metric advertising_fee_percent --metric fee_percent --metric tax_fee_percent \
  --metric fixed_cost_percent --metric refund_percent --metric gross_profit_percent \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

### 认证流程

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

## 最佳实践

1. **始终与内部基准对比**：使用团队/品类均值作为基准，而非外部猜测值
2. **标记固定成本**：`fee_percent`、`tax_fee_percent`、`fixed_cost_percent` 为不可优化项，不要输出相关建议
3. **聚焦前 3 大偏离项**：避免输出过多行动建议导致执行分散
4. **量化预期效果**：尽可能用美元金额表示预期节省（基于 `sales_amount` 计算）
5. **按偏离严重程度排序**：Critical（🔴）> Warning（⚠️）> Normal（✅）
6. **验证数据完整性**：若成本项之和 + 毛利率明显偏离 100%，提示数据缺失
