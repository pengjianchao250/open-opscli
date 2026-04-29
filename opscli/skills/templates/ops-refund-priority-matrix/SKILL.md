---
name: ops-refund-priority-matrix
description: None
  分析退款数据和运营建议，将问题划分为
  Critical / Important / Nice-to-have 三档优先级，并输出按 ROI 排序的
  改进动作清单。触发场景包括：退款优先级、退款分析、退款原因、
  优先级矩阵、运营建议排序、退款率诊断、
  Critical / Important / Nice-to-have 分类、改进清单、ROI 排序。
---

# 退款优先级矩阵

分析退款原因和运营建议数据，按严重程度与频率将问题分类为 Critical / Important / Nice-to-have 三级，并计算每项修复的 ROI 排序输出。

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

- **单 ASIN 退款问题分析**：分析单个 ASIN 的退款原因分布、严重程度和改进优先级
- **批量 ASIN 优先级排序**：同时分析多个 ASIN，输出跨 ASIN 的问题优先级总榜
- **运营建议严重程度映射**：将运营建议数据集中的问题映射到三级优先级
- **预期效果量化**：基于退款金额和毛利率，估算修复每项问题的预期节省金额
- **跨数据集交叉验证**：结合 `custom_refund_place_set`、`custom_operation_suggest_suggestions_set` 和 `order_sale_trend_adv_traffic_inv_set` 进行数据校验

## 优先级分类

### Critical（P0，严重）
- **判断标准**：严重性=高AND（退款率>10%或频率>20%）
- **处理时限**：7 天内修复
- **典型示例**：漏水（leaking）、到货破损（broken on arrival）、尺寸严重不符（size mismatch）

### Important（P1，重要）
- **判定标准**：Severity = Medium AND（Refund Rate 5-10% OR Frequency 10-20%）
- **处理时限**：30 天内修复
- **典型示例**：保温效果差（poor insulation）、难清洗（difficult cleaning）、色差（color mismatch）

### Nice-to-have（P2，可选优化）
- **判定标准**：Severity = Low AND（Refund Rate < 5% OR Frequency < 10%）
- **处理时限**：资源允许时处理
- **典型示例**：颜色选择少（limited colors）、包装简单（simple packaging）、轻微划痕（minor scratches）

## 数据来源

### 主数据源：custom_refund_place_set（`ds_y5EoxUyLf6Aq`）
- `refund_reason`: 退款原因文本
- `overseas_origin_suffix`: 产品产地
- `order_status`: 订单状态
- `refund_amount`: 退款金额

### 辅助数据源：custom_operation_suggest_suggestions_set（`ds_zY0BAi0Txsga`）
- `issue_type`: 问题类别
- `severity`: 严重程度
- `operation_stage`: 运营阶段
- `suggestion`: 改进建议

### 校验数据源：order_sale_trend_adv_traffic_inv_set（`ds_d35ac6f3910c`）
- `refund_percent`: 整体退款率
- `gross_profit`: 利润影响

## 输入格式

```json
{
  "target": {
    "type": "asin",
    "value": "B08XXXXXX"
  },
  "period": {
    "start": "2025-01-01",
    "end": "2025-01-31"
  },
  "refund_data": [
    {"reason": "leaking", "count": 23, "amount": 1200},
    {"reason": "size_mismatch", "count": 15, "amount": 800},
    {"reason": "poor_insulation", "count": 19, "amount": 600}
  ],
  "operation_suggestions": [
    {"issue_type": "quality", "severity": "high", "suggestion": "Fix seal"},
    {"issue_type": "design", "severity": "medium", "suggestion": "Add size chart"}
  ],
  "financial_context": {
    "refund_percent": 0.185,
    "category_avg_refund": 0.082,
    "monthly_sales": 15000,
    "gross_profit_percent": 0.15
  }
}
```

### 字段说明

- `target.type`: 分析对象类型，可选 `asin` / `category` / `batch`
- `target.value`: 分析对象标识
- `period`: 分析时间范围
- `refund_data`: 退款原因列表，每项包含 reason（原因）、count（次数）、amount（金额）
- `operation_suggestions`: 运营建议列表，每项包含 issue_type（问题类型）、severity（严重程度）、suggestion（建议内容）
- `financial_context`: 财务上下文，用于 ROI 计算和效果量化

## 输出格式

脚本输出 JSON：

```json
{
  "target": "B08XXXXXX",
  "overall_refund_percent": 0.185,
  "category_benchmark": 0.082,
  "period": "2025-01-01 ~ 2025-01-31",
  "total_refund_amount": 2600,
  "priority_matrix": {
    "critical": [
      {
        "issue": "leaking",
        "frequency": 0.23,
        "count": 23,
        "severity": "high",
        "monthly_loss": 1200,
        "recommended_action": "排查密封圈和焊接工艺，修复漏水问题",
        "expected_saving": 800,
        "roi_score": 95,
        "priority": "P0"
      }
    ],
    "important": [...],
    "nice_to_have": [...]
  },
  "sorted_actions": [
    {
      "rank": 1,
      "action": "排查密封圈和焊接工艺，修复漏水问题",
      "issue": "leaking",
      "roi_score": 95,
      "priority": "P0",
      "expected_saving": 800
    }
  ],
  "summary": {
    "critical_count": 1,
    "important_count": 1,
    "nice_to_have_count": 1,
    "total_monthly_loss": 2600,
    "total_expected_saving": 1500
  }
}
```

### 终端表格输出示例

```
【分析对象】ASIN B08XXXXXX（保温杯）
【分析周期】2025-01-01 ~ 2025-01-31
【总退款率】18.5%（高于品类均值 8.2%，危险）

优先级矩阵：
┌─────────────────────┬──────────┬──────────┬──────────────────────────────┐
│ 问题                │ 严重程度 │ 频率     │ 预估损失 / 预期节省             │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 临界（P0） │ │ │ │
│ 漏水（leaking）     │ 高       │ 23%      │ 损失：$1,200/月 | 节省：$800/月│
│ 容量虚标            │ 高       │ 15%      │ 损失：$800/月  | 节省：$400/月 │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 重要事项（P1） │ │ │ │
│ 保温时间短          │ 中       │ 19%      │ 损失：$600/月  | 节省：$300/月 │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 锦上添花（P2） │ │ │ │
│ 颜色选择少          │ 低       │ 8%       │ 损失：$100/月  | 节省：$50/月  │
└─────────────────────┴──────────┴──────────┴──────────────────────────────┘

行动建议（按 ROI 排序）：
1. 【Critical|P0】排查漏水原因（密封圈/焊接工艺）
   → 预计修复后退款率从 18.5% 降至 10%
   → 预计月节省损失 $800
   → ROI 评分：95

2. 【Critical|P0】修正容量标注，增加实物对比图
   → 预计降低 "尺寸不符" 退款 50%
   → 预计月节省损失 $400
   → ROI 评分：85

3. 【Important|P1】升级保温材料或调整用户预期
   → 预计提升 rating 0.3-0.5 星
   → 预计月节省损失 $300
   → ROI 评分：70
```

## 脚本

- `scripts/calculate_priority_matrix.py`：接收退款数据和运营建议，计算三级优先级矩阵和 ROI 排序，输出 JSON

### 使用方式

```bash
# 通过管道传入 JSON
cat input.json | python opscli/skills/templates/ops-refund-priority-matrix/scripts/calculate_priority_matrix.py

# 或通过 echo 传入测试数据
echo '{"target":{"type":"asin","value":"B08XXXXXX"},...}' | \
  python opscli/skills/templates/ops-refund-priority-matrix/scripts/calculate_priority_matrix.py
```

## 数据查询

### 数据集信息

| 数据集 | ID | 类型 | 用途 |
|--------|-----|------|------|
| custom_refund_place_set | `ds_y5EoxUyLf6Aq` | 非子查询 | 主数据源：退款原因和金额 |
| order_sale_trend_adv_traffic_inv_set | `ds_d35ac6f3910c` | 非子查询 | 验证：整体退款率和利润 |
| custom_operation_suggest_suggestions_set | `ds_zY0BAi0Txsga` | 非子查询 | 辅助：运营建议映射 |

### 推荐查询方式

使用 `opscli query build` 命令自动生成查询 payload：

#### 退款数据查询

```bash
opscli query build \
  --dataset ds_y5EoxUyLf6Aq \
  --dimension asin --dimension refund_reason \
  --metric refund_amount --metric order_status \
  --output payload_refund.json

opscli query run --payload payload_refund.json
```

#### 整体退款率验证

```bash
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin \
  --metric refund_percent --metric gross_profit \
  --output payload_sales.json

opscli query run --payload payload_sales.json
```

#### 运营建议查询

```bash
opscli query build \
  --dataset ds_zY0BAi0Txsga \
  --dimension asin --dimension issue_type \
  --metric severity --metric suggestion \
  --output payload_suggest.json

opscli query run --payload payload_suggest.json
```

### 认证流程

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

## 最佳实践

1. **始终交叉验证**：退款原因与运营建议数据应相互印证，若出现矛盾需人工复核
2. **量化预期效果**：当 `gross_profit_percent` 和 `monthly_sales` 可用时，用美元金额表示预期节省
3. **考虑修复成本 vs 预期收益**：ROI 排序时应纳入修复成本估算（可参考 severity_scoring_guide.md）
4. **产地相关问题时升级**：若 `overseas_origin_suffix` 指向特定工厂，需标记到对应 dev_team_name 进行供应商沟通
5. **Critical 问题不漏报**：任何 High Severity + 高频率的组合必须进入 Critical 列表
6. **Nice-to-have 不误报**：低频率（< 10%）+ Low Severity 的问题不要过度升级
7. **支持扩展**：新增退款原因和分类规则时，同步更新 refund_reasons_catalog.md
