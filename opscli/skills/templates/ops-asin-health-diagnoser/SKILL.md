---
name: ops-asin-health-diagnoser
description: 通过使用内部运营数据计算 gross_profit_percent、convert_percent、ads_acos、refund_percent、inventory_turnaround_days 和星级的综合分数来诊断 Amazon ASIN 运行状况。支持 CLI 模式和 MCP 模式。在评估产品性能、识别表现不佳的 ASIN、确定运营干预的优先顺序或准备每周审核报告时使用。
version: v0.1.0
---

# ASIN 健康诊断器

使用 opscli 数据集中的内部运营数据计算 Amazon ASIN 的综合运行状况评分 (0-100)。支持 CLI 模式和 MCP 无状态模式。

---

## 何时使用本 Skill

- 需要对单一 ASIN 进行深度健康诊断（6 大核心指标）
- 需要对批量 ASIN 进行健康度排名和过滤
- 需要部门/团队级别的健康概览
- 需要基于数据驱动的优先行动建议
- 需要自定义权重和阈值

---

## 运行模式判断

进入本 Skill 后，先判断当前环境使用哪种模式。

优先级如下：

1. 如果用户明确要求使用 CLI 或 MCP，直接遵循用户指定
2. 否则先检测是否安装了 `aukeys-opscli` Python 发行包
3. 再检测 `opscli` 命令是否可执行
4. 如果以上检测通过，读取 `references/cli.md`
5. 如果任一检测失败，读取 `references/mcp.md`

推荐检测脚本：

```bash
python - <<'PY'
from importlib import metadata
import shutil
import subprocess

dist_ok = False
opscli_ok = False

try:
    metadata.version("aukeys-opscli")
    dist_ok = True
except metadata.PackageNotFoundError:
    pass

opscli_ok = shutil.which("opscli") is not None
if opscli_ok:
    opscli_ok = subprocess.run(
        ["opscli", "query", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

print({
    "dist_ok": dist_ok,
    "opscli_ok": opscli_ok,
    "mode": "cli" if dist_ok and opscli_ok else "mcp",
})
PY
```

---

## 阅读入口

- CLI 模式：继续阅读 `references/cli.md`
- MCP 模式：继续阅读 `references/mcp.md`
- 无论哪种模式，都需要参考 `references/threshold_reference.md` 和 `references/dataset_fields_mapping.md`
- 复杂查询场景需同步参考 `references/data-query-service-dev-guide.md`

---

## 使用原则

- 所有远端查询动作必须统一走选定模式下的正式查询入口，禁止直接调用后端 HTTP 接口
- 认证检查仍然是强制门禁，具体流程以对应 reference 文档为准
- 健康评分计算核心逻辑在 `scripts/calculate_health_score.py`（CLI）和 `scripts/calculate_health_score_mcp.py`（MCP）
- 字段搜索、payload 构造、数据查询都以对应模式文档和 `references/data-query-service-dev-guide.md` 为准
- 涉及环比、同比、趋势对比时，优先使用服务端能力，不要默认降级为多次查询后本地拼接

---

## 强制认证与环境门禁

进入本 Skill 后，必须先完成环境与认证检查；检查通过前，禁止直接开始抓取、查询、运行脚本或读取数据样本。

**CLI 模式**标准前置流程：

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

**MCP 模式**标准前置流程：

```python
# 1. 先检查 session 是否有效
auth_is_authenticated(session_id="xxx")

# 2. 如 session_id 缺失或过期，重新 Device Flow 授权
auth_login_start()                     # 获取 device_code / user_code
auth_login_poll(device_code="xxx")     # 轮询直到 authorized，获取新 session_id

# 3. 登录后再次确认
auth_is_authenticated(session_id="新session_id")
```

禁止事项：

- 禁止跳过认证检查，直接执行查询或分析脚本
- 禁止在未登录状态下直接运行本 Skill 的任何脚本
- 禁止手写、复用或拼接过期 Token 绕过认证

---

## 能力范围

- 单一 ASIN 深度诊断 6 大核心指标
- 批量 ASIN 健康度排名和过滤
- 部门/团队级别的健康概览
- 具有预期影响的优先行动建议
- 支持自定义权重和阈值

---

## 健康评分公式

```
分数 = w1 * 标准化(gross_profit_percent) +
        w2 * 标准化(convert_percent) +
        w3 * 标准化(1 - ads_acos) +
        w4 * 标准化(1 - 退款率) +
        w5 * 标准化(1 / 库存天数) +
        w6 * 标准化(星级 / 5)
```

默认权重：`[0.30, 0.20, 0.20, 0.15, 0.10, 0.05]`

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| 主数据集 | `ds_d35ac6f3910c` | ASIN 运营指标（毛利率、转化率、ACOS、退款率、周转天数） |
| 辅助数据集 | `ds_pdTYjvLRCadv` | ASIN Listing 快照（星级、评论数、排名） |

详细字段映射见 `references/dataset_fields_mapping.md`。

---

## 输入格式

- 单个 ASIN：`"B08XXXXXX"`
- 多个 ASIN：`"B08XXXXXX, B09YYYYYY"`
- 团队过滤器：`"team_name = 'Kitchen-Team-A'"`
- 日期范围：`"last 30 days"`、`"2025-01-01 to 2025-01-31"`

---

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

---

## 脚本

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/core.py` | 通用 | 健康评分计算核心逻辑 |
| `scripts/calculate_health_score.py` | CLI | 读取 stdin JSON，调用 opscli 查询后计算评分 |
| `scripts/calculate_health_score_mcp.py` | MCP | 读取 MCP Tool 输入，计算评分（无 opscli 依赖） |

---

## 阈值参考

| 指标 | 健康 | 预警 | 严重 |
|--------|---------|----------|
| 毛利率 | > 20% | 10-20% | < 10% |
| 转化率 | > 10% | 5-10% | < 5% |
| 广告 ACOS | < 20% | 20-30% | > 30% |
| 退款率 | < 5% | 5-10% | > 10% |
| 库存天数 | < 45 | 45-90 | > 90 |
| 星级 | > 4.3 | 4.0-4.3 | < 4.0 |

详细阈值和权重配置见 `references/threshold_reference.md`。

---

## 最佳实践

1. 始终与团队/类别平均值进行比较，而不仅仅是绝对阈值
2. 当星级缺失时，将其排除在计算之外并记下差距
3. 对于新产品（< 30 天），使用宽松的阈值
4. 标记具有多个关键指标的任何 ASIN，以便立即引起注意
5. 使用 `opscli query build`（CLI）或 `query_build_and_run`（MCP）构造 payload，而不是手写 SQL
6. 查询前必须先完成认证门禁检查