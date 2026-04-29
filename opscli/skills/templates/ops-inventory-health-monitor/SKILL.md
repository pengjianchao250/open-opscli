---
name: ops-inventory-health-monitor
description: 监控库存周转天数、库龄分布和断货风险，识别滞销和缺货 SKU，并生成补货、清仓和调拨建议。支持 CLI 模式和 MCP 模式。
version: v0.1.0
---

# 库存健康监控器

跟踪库存健康指标，并生成可执行的补货、清仓和调拨建议。 支持 CLI 模式和 MCP 无状态模式。

---

## 何时使用本 Skill

- 需要管理库存水平
- 需要制定补货计划
- 需要清理死库存
- 需要分析库存周转健康度

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
- 无论哪种模式，都需要参考 `references/dataset_fields_mapping.md`
- 复杂查询场景需同步参考 `references/data-query-service-dev-guide.md`

---

## 使用原则

- 所有远端查询动作必须统一走选定模式下的正式查询入口，禁止直接调用后端 HTTP 接口
- 认证检查仍然是强制门禁，具体流程以对应 reference 文档为准
- 分析计算核心逻辑在 `scripts/core.py`（通用），CLI 和 MCP 脚本分别复用核心逻辑
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

- 库存周转分析
- 库龄分布跟踪
- 断货风险预测
- 滞销 SKU 识别
- 补货量计算
- 跨仓调拨建议

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| ds_97zj6R0KDKpB | `库存周转数据（可售天数、平台库存、海外仓库存等）` | 库存周转数据 |
| ds_d35ac6f3910c | `辅助数据（总库存、FBA 库存等）` | 辅助数据 |

详细字段映射见 `references/dataset_fields_mapping.md`。

---

## 脚本

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/calculate_inventory_health.py` | CLI | 计算库存健康评级和风险识别 |
| `scripts/calculate_inventory_health_mcp.py` | MCP | 计算库存健康评级和风险识别（无 opscli 依赖） |
| `scripts/generate_replenishment_plan.py` | CLI | 生成补货数量与时机建议 |
| `scripts/generate_replenishment_plan_mcp.py` | MCP | 生成补货数量与时机建议（无 opscli 依赖） |
| `scripts/core.py` | 通用 | 库存健康计算核心常量和函数 |

## 阈值参考

| 指标 | 健康 | 预警 | 严重 |
|--------|---------|----------|
| 周转天数 | < 45 | 45-90 | > 90 |
| 可售+在途天数 | < 60 | 60-120 | > 120 |
| 平台库存 | > 7 天销量 | 3-7 天 | < 3 天 |
| 海外仓可售 | > 14 天销量 | 7-14 天 | < 7 天 |
| 锁定库存占比 | < 20% | 20-50% | > 50% |


## 最佳实践

1. 在补货计算中始终考虑在途库存
2. 标记锁定库存并调查原因
3. 使用 30 天滚动平均销量平滑波动
4. 季节性产品需要调整目标库存天数
5. 使用 `opscli query build`（CLI）或 `query_build_and_run`（MCP）构造 payload
6. 查询前必须先完成认证门禁检查
