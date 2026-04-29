---
name: ops-asin-health-diagnoser
description: 通过使用内部运营数据计算gross_profit_percent、convert_percent、ads_acos、refund_percent、inventory_turnaround_days 和星级的综合分数来诊断 Amazon ASIN 运行状况。在评估产品性能、识别表现不佳的 ASIN、确定运营干预的优先顺序或准备每周审核报告时使用。
---

# ASIN 健康诊断器

使用 opscli 数据集中的内部运营数据计算 Amazon ASIN 的综合运行状况评分 (0-100)。

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

- 单一ASIN深度诊断6大核心指标
- 批量ASIN健康度排名和过滤
- 部门/团队级别的健康概览
- 具有预期影响的优先行动建议
- 支持自定义权重和阈值

## 健康评分公式

```
分数 = w1 * 标准化(gross_profit_percent) +
        w2 * 标准化(convert_percent) +
        w3 * 标准化(1 - ads_acos) +
        w4 * 标准化(1 - 退款率) +
        w5 * 标准化(1 / 库存天数) +
        w6 * 标准化（星号 / 5）
```

默认权重：`[0.30, 0.20, 0.20, 0.15, 0.10, 0.05]`

## 阈值参考

> **字段映射说明**：数据集 `ds_d35ac6f3910c` 中的 `sell_qty_days` 字段对应本 Skill 中的 `inventory_days` 指标，`ads_acos` 对应 `ads_acos`，`convert_percent` 对应转化率字段。

| 指标 | 数据集字段 | 健康 | 预警 | 严重 |
|--------|---------|---------|----------|
|毛利率 | > 20% | 10-20% | < 10% |
|转化率 | > 10% | 5-10% | < 5% |
|广告 ACOS | < 20% | 20-30% | > 30% |
|退款率 | < 5% | 5-10% | > 10% |
|库存天数 | < 45 | 45-90 | 45-90 > 90 |
|星级| > 4.3 | 4.0-4.3 | < 4.0 |

## 输入格式

- 单个 ASIN：`"B08XXXXXX"`
- 多个 ASIN：`"B08XXXXXX, B09YYYYYY"`
- 团队过滤器：`"team_name = 'Kitchen-Team-A'"`
- 日期范围：`"last 30 days"`、`"2025-01-01 to 2025-01-31"`

## 输出格式

对于每个 ASIN：

```
【ASIN】B08XXXXXX（产品名称）
【健康度评分】72/100（良好）
【分项指标】
  ├─ 毛利率：18.5% ⚠️（预警，目标>20%）
  ├─ 转化率：12.3% ✅（健康）
  ├─ ACOS：22.1% ⚠️（预警，目标<20%）
  ├─ 退款率：4.2% ✅（健康）
  ├─ 库存周转：38天 ✅（健康）
  └─ 星级：4.5⭐ ✅（健康）
【主要问题】ACOS 偏高、毛利率低于目标
【建议行动】
  1. [P1] 优化广告投放，将 ACOS 从 22% 降至 18%
  2. [P1] 评估采购成本，谈判降低 2-3%
【数据时间】2025-01-01 ~ 2025-01-31
```

## 脚本

- `scripts/calculate_health_score.py`：根据 JSON 输入计算综合健康评分

## 使用方式

### 第一步：查询数据

使用 opscli 查询命令获取 ASIN 指标：

```bash
# 构建查询负载
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --output payload.json

# 运行查询
opscli query run --payload payload.json
```

### 第二步：执行诊断

```bash
echo '{"asin": "B08XXXXXX", "metrics": {...}}' | python scripts/calculate_health_score.py
```

## 最佳实践

1. 始终与团队/类别平均值进行比较，而不仅仅是绝对阈值
2. 当星级缺失时，将其排除在计算之外并记下差距
3. 对于新产品（< 30 天），使用宽松的阈值
4. 标记具有多个关键指标的任何 ASIN，以便立即引起注意
5. 使用 `opscli query build` 构造 payload，而不是手写 SQL
