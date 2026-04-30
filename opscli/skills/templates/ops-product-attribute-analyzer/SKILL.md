---
name: ops-product-attribute-analyzer
description: 应用三维产品属性标签体系（结构/版型、材料/工艺、设计元素）计算各属性组合的销量加权市场份额，识别供给不足的高价值属性机会。支持 CLI 模式和 MCP 模式。
version: v0.1.1
---

# 产品属性分析器

通过三维标签体系和销量加权市场份额分析产品属性，为产品开发决策提供依据。 支持 CLI 模式和 MCP 无状态模式。

---

## 何时使用本 Skill

- 需要规划产品开发
- 需要分析品类趋势
- 需要优化 SKU 组合
- 需要研究市场属性偏好

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

优先级如下：

1. 如果用户明确要求使用 CLI 或 MCP，直接遵循用户指定
2. 如果当前就在 `opscli` 项目、本地终端可直接执行正式命令，默认使用 CLI，并读取 `references/cli.md`
3. 如果当前任务本身就是基于 MCP Tool 协作，或明显无法直接走本地 CLI，再读取 `references/mcp.md`
4. 如果一开始按 CLI 执行首个正式命令就失败（例如 `opscli query ...` 不可用、当前宿主不适合跑本地命令），直接切换到 MCP 版本，并读取 `references/mcp.md`
5. 如果 MCP 版本也不可用（例如当前没有可用 MCP 服务、查询工具未注册、调用宿主不支持 MCP），再回退为帮助用户安装 `aukeys-opscli`

建议提问方式：

- `当前 CLI 与 MCP 入口都不可用。你希望我先帮你安装 aukeys-opscli，再继续处理吗？`

简化原则：

- 默认优先 CLI，因为它是 `opscli` 模块的正式入口，最贴近真实交付路径
- 不单独检查发行包、命令路径、子命令 help；用“首次正式调用是否可执行”作为唯一验证
- 一旦 CLI 和 MCP 都可行，优先保持单一路径，不要来回切换
- CLI 首次正式调用失败后，直接切到 MCP，不额外询问
- 只有在 MCP 版本也不可用时，才回退为帮助用户安装 `aukeys-opscli`

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

- 三维属性标签化与标准化
- 销量加权市场份额计算
- 属性组合排序与机会识别
- 市场画像生成
- 供给不足机会识别

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| ds_8f24440d149b | `产品属性标签数据（开发类型、SKU 等级等）` | 产品属性标签 |
| ds_d35ac6f3910c | `内部销售数据（销量、销售额、毛利率等）` | 内部销售数据 |

详细字段映射见 `references/dataset_fields_mapping.md`。

---

## 脚本

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/calculate_weighted_share.py` | CLI | 计算单个维度的销量加权市场份额 |
| `scripts/calculate_weighted_share_mcp.py` | MCP | 计算销量加权市场份额（无 opscli 依赖） |
| `scripts/analyze_attribute_combo.py` | CLI | 分析属性组合机会 |
| `scripts/analyze_attribute_combo_mcp.py` | MCP | 分析属性组合机会（无 opscli 依赖） |
| `scripts/generate_market_portrait.py` | CLI | 生成市场画像摘要报告 |
| `scripts/generate_market_portrait_mcp.py` | MCP | 生成市场画像（无 opscli 依赖） |
| `scripts/core.py` | 通用 | 属性分析核心常量和函数 |


## 最佳实践

1. 始终使用销量加权份额，不要使用 ASIN 数量份额
2. 比较 sales_per_asin 以识别供给不足机会
3. 使用 90 天滚动数据平滑季节性影响
4. 过滤销量少于 10 的 ASIN，避免噪音干扰
5. 使用 `opscli query build`（CLI）或 `query_build_and_run`（MCP）构造 payload
6. 查询前必须先完成认证门禁检查
