---
name: ops-advertising-efficiency-optimizer
description: 跨广告系列、广告组和广告类型 (SP/SD/SB/SBV) 维度分析广告效率。识别高 ACOS 问题并生成字级、活动级和时间段优化建议。支持 CLI 模式和 MCP 模式。在评估广告效率、优化广告预算、比较广告类型效果或诊断广告浪费时使用。
version: v0.1.1
---

# 广告效率优化器

诊断广告效果问题并生成跨多个维度的优化策略。支持 CLI 模式和 MCP 无状态模式。

---

## 何时使用本 Skill

- 需要诊断广告活动 ACOS 偏高问题
- 需要对比不同广告类型（SP/SD/SB/SBV）的效率
- 需要重新分配广告预算
- 需要追踪 ROAS 与 CPC 趋势
- 需要自定义广告效率基准和阈值

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
- 广告效率计算核心逻辑在 `scripts/core.py`（通用）、`scripts/analyze_ads_efficiency.py`（CLI）和 `scripts/analyze_ads_efficiency_mcp.py`（MCP）
- ROAS/ACOS 计算通过 `scripts/calculate_roas_acos.py`（CLI）和 `scripts/calculate_roas_acos_mcp.py`（MCP）
- 预算分配通过 `scripts/ads_budget_allocator.py`（CLI）和 `scripts/ads_budget_allocator_mcp.py`（MCP）
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

- 活动级 ACOS 诊断
- 广告类型对比（SP、SD、SB、SBV）
- 关键词效果分析
- 预算重新分配建议
- 时间段有效性分析
- ROAS 与 CPC 趋势跟踪

---

## 核心指标

| 指标 | 公式 | 健康 | 预警 | 严重 |
|--------|---------|---------|---------|----------|
| ACOS | 广告成本 / 广告销售额 | < 20% | 20-30% | > 30% |
| ROAS | 广告销售额 / 广告成本 | > 5.0 | 3.3-5.0 | < 3.3 |
| CPC | 广告成本 / 点击量 | < $1.5 | $1.5-2.5 | > $2.5 |
| CTR | 点击量 / 曝光量 | > 0.3% | 0.2-0.3% | < 0.2% |
| 转化率 | 订单数 / 点击量 | > 10% | 5-10% | < 5% |

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| 广告活动数据集 | `ds_0759e20F0DrG` | 活动级 ACOS/ROAS 诊断（子查询类型） |
| SP 广告类型数据集 | `ds_fE0flP7WonsJ` | 广告类型对比分析（非子查询类型） |

详细字段映射见 `references/dataset_fields_mapping.md`。

---

## 输入格式

- ASIN 级别：`"B08XXXXXX"`
- 活动级别：`"campaign_name = 'Water-Bottle-SP-Exact'"`
- 广告类型：`"分析 SP 与 SB"`
- 日期范围：`"过去 30 天"`

---

## 输出格式

```
【分析对象】ASIN B08XXXXXX（保温水瓶）
【分析周期】2025-01-01 ~ 2025-01-31
【总广告费】$8,500 | 【总广告销售额】$35,000 | 【综合 ACOS】24.3%

广告类型对比：
┌──────────┬─────────┬───────────┬───────┬────────┐
│ 广告类型 │ 支出 │ 销售 │ ACOS │ ROAS │
├──────────┼─────────┼───────────┼───────┼────────┤
│ SP       │ $5,200  │ $22,000   │ 23.6% │ 4.23   │
│ SB       │ $2,100  │ $10,000   │ 21.0% │ 4.76   │
│ SD       │ $1,000  │ $2,500    │ 40.0% │ 2.50 🔴│
│ SBV │ $200 │ $500 │ 40.0% │ 2.50 🔴│
└──────────┴─────────┴───────────┴───────┴────────┘

问题诊断：
🔴 SD 广告 ACOS 40%（目标 < 25%）
   └─ 原因：受众定位过宽，展示量高但转化低
   └─ 建议：缩小受众范围，暂停低转化受众组

🔴 SBV 广告 ACOS 40%
   └─ 原因：视频完播率仅 15%（均值 35%）
   └─ 建议：前 3 秒加入产品核心卖点，缩短视频至 15 秒

优化建议（按预期 ROI 排序）：
1. [P0] 暂停 SD 受众组 "Broad-Interest"（月节省 $400）
2. [P0] 将 SBV 视频前 3 秒改为 "Keep Cold 24h"（预计完播率提升至 30%）
3. [P1] SP 大词 "water bottle" 降低竞价 15%（ACOS 从 28% 降至 23%）
4. [P1] 将节省的 $600 预算转移至 SP 长尾词组（预期 ROAS 6.0+）
```

---

## 脚本

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/core.py` | 通用 | 广告效率计算核心逻辑（常量、基准、核心函数） |
| `scripts/analyze_ads_efficiency.py` | CLI | 读取 stdin JSON，调用 opscli 查询后分析广告效率 |
| `scripts/analyze_ads_efficiency_mcp.py` | MCP | 读取 MCP Tool 输入，分析广告效率（无 opscli 依赖） |
| `scripts/calculate_roas_acos.py` | CLI | 快速 ROAS/ACOS 计算 |
| `scripts/calculate_roas_acos_mcp.py` | MCP | 快速 ROAS/ACOS 计算（无 opscli 依赖） |
| `scripts/ads_budget_allocator.py` | CLI | 预算重新分配优化器 |
| `scripts/ads_budget_allocator_mcp.py` | MCP | 预算重新分配优化器（无 opscli 依赖） |

---

## 最佳实践

1. 始终在广告系列+广告组级别进行分析，而不仅仅是帐户级别
2. 将 ACOS 与类别基准进行比较，而不仅仅是绝对目标
3. 对于新营销活动（< 14 天），使用宽松的阈值
4. 在评估品牌活动时考虑有机销售提升
5. 使用 `opscli query build`（CLI）或 `query_build_and_run`（MCP）构造 payload，而不是手写 SQL
6. 查询前必须先完成认证门禁检查
