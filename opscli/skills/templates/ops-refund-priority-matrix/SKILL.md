---
name: ops-refund-priority-matrix
description: 分析退款数据和运营建议，将问题划分为 Critical/Important/Nice-to-have 三档优先级，并输出按 ROI 排序的改进动作清单。支持 CLI 模式和 MCP 模式。
version: v0.1.0
---

# 退款优先级矩阵

分析退款原因和运营建议数据，按严重程度与频率将问题分类为 Critical/Important/Nice-to-have 三级，并计算每项修复的 ROI 排序输出。 支持 CLI 模式和 MCP 无状态模式。

---

## 何时使用本 Skill

- 需要分析退款优先级
- 需要进行退款原因分析
- 需要制定改进清单
- 需要对运营建议进行 ROI 排序
- 需要进行退款率诊断

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

- 单 ASIN 退款问题分析
- 批量 ASIN 优先级排序
- 运营建议严重程度映射
- 预期效果量化
- 跨数据集交叉验证

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| ds_y5EoxUyLf6Aq | `退款数据（退款原因、金额等）` | 退款数据 |
| ds_zY0BAi0Txsga | `运营建议数据（问题类型、严重程度等）` | 运营建议数据 |
| ds_d35ac6f3910c | `校验数据（整体退款率、利润等）` | 校验数据 |

详细字段映射见 `references/dataset_fields_mapping.md`。

---

## 脚本

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/calculate_priority_matrix.py` | CLI | 接收退款数据和运营建议，计算三级优先级矩阵和 ROI 排序 |
| `scripts/calculate_priority_matrix_mcp.py` | MCP | 优先级矩阵计算（无 opscli 依赖） |
| `scripts/core.py` | 通用 | 优先级矩阵核心常量和函数 |


## 最佳实践

1. **始终交叉验证**：退款原因与运营建议数据应相互印证
2. **量化预期效果**：当 `gross_profit_percent` 和 `monthly_sales` 可用时，用美元金额表示预期节省
3. **考虑修复成本 vs 预期收益**：ROI 排序时应纳入修复成本估算
4. **产地相关问题时升级**：若 `overseas_origin_suffix` 指向特定工厂，需标记到对应团队
5. **Critical 问题不漏报**：High Severity + 高频率的组合必须进入 Critical 列表
6. **Nice-to-have 不误报**：低频率 + Low Severity 的问题不要过度升级
