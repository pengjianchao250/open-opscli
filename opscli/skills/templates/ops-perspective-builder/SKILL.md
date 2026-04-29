---
name: ops-perspective-builder
description: 从多个数据集中自动选择维度、指标和过滤条件，构建 BI 透视表和图表配置，输出可直接用于 Superset/Metabase 的配置方案。支持 CLI 模式和 MCP 模式。
version: v0.1.0
---

# 透视视图构建助手

根据用户选择的分析主题和数据集，自动构建 BI 透视图的维度、指标、过滤条件配置方案。 支持 CLI 模式和 MCP 无状态模式。

---

## 何时使用本 Skill

- 需要创建运营看板
- 需要设计下钻分析视图
- 需要配置周报
- 需要构建销售趋势透视或利润结构拆解视图

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

- 标准透视图配置：12 个内置标准透视图模板
- 自定义透视图设计：从零开始设计自定义透视图
- 维度与指标推荐：基于分析目标智能推荐
- 下钻路径设计：设计从集团到 ASIN 的多级下钻
- 过滤条件与阈值配置：配置过滤条件和阈值高亮规则
- 跨数据集 Join 建议：跨数据集分析时推荐 Join Key 和关联方案

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| ds_d35ac6f3910c | `主数据集（销售、毛利、退款等）` | 主数据集 |
| ds_0759e20F0DrG | `广告活动数据集（子查询）` | 广告活动数据集 |
| ds_fE0flP7WonsJ | `SP 广告类型数据集` | SP 广告类型数据集 |
| ds_97zj6R0KDKpB | `库存周转数据集` | 库存周转数据集 |
| ds_pdTYjvLRCadv | `竞品 Listing 快照数据集` | 竞品 Listing 快照 |
| ds_y5EoxUyLf6Aq | `退款数据集` | 退款数据集 |
| ds_xsTOkHIpr3ad | `搜索词数据集` | 搜索词数据集 |
| ds_8f24440d149b | `产品属性标签数据集` | 产品属性标签 |

详细字段映射见 `references/dataset_fields_mapping.md`。

---

## 脚本

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/build_perspective_config.py` | CLI | 根据用户输入生成完整透视图配置 JSON |
| `scripts/build_perspective_config_mcp.py` | MCP | 生成透视图配置 JSON（无 opscli 依赖） |
| `scripts/core.py` | 通用 | 透视图模板和核心构建逻辑 |


## 最佳实践

1. **优先使用 `ds_d35ac6f3910c`** 进行跨域分析
2. **使用 `date_id` 作为主要时间维度**
3. **至少包含一个组织维度**用于下钻
4. **为关键指标添加阈值高亮**
5. **跨数据集分析前先验证 Join Key**
6. **公式指标必须使用完整表达式格式**
