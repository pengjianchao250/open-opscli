---
name: ops-advertising-efficiency-optimizer
description: 使用 CLI 模式查询本地数据集索引并执行广告效率分析数据查询
version: v0.1.0
---

# ops-advertising-efficiency-optimizer (CLI 模式)

使用 `opscli` 命令行工具查询广告运营数据，通过本地缓存索引辅助字段检索，使用脚本计算广告效率指标。

---

## 调用前置要求

> **【强制】每次使用本 Skill 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现"未登录 / 未授权 / Token 过期 / expired / 401"等状态，必须立即调用 `ops-auth` Skill
- 只有认证状态确认正常后，才允许继续读取本地索引、执行查询或运行分析脚本

**标准前置流程：**

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

> **【强制】使用本 Skill 前，必须先阅读 `references/data-query-service-dev-guide.md`**

---

## 使用原则

- 本 Skill 负责字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 `opscli query` 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `opscli skills upgrade ops-dataset-query` 再重试查询
- 广告效率分析通过 `scripts/analyze_ads_efficiency.py` 完成
- ROAS/ACOS 计算通过 `scripts/calculate_roas_acos.py` 完成
- 预算分配通过 `scripts/ads_budget_allocator.py` 完成

---

## 典型工作流

### 广告活动级诊断

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 查询广告活动级数据（子查询类型）
opscli query build \
  --dataset ds_0759e20F0DrG \
  --dimension campaign_name --dimension ad_group_name --dimension ads_type \
  --metric advertising_fee --metric ads_sales_cny --metric ads_clicks --metric ads_impressions \
  --where "asin|eq|\"B08XXXXXX\"" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/ads_campaign.json \
  --run --pretty

# 2. 查询广告类型组合数据（非子查询类型）
opscli query build \
  --dataset ds_fE0flP7WonsJ \
  --dimension ad_type \
  --metric ads_sp --metric ads_sd --metric ads_sb --metric ads_sbv --metric ads_sales_cny \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/ads_type.json \
  --run --pretty

# 3. 合并数据并运行广告效率分析
python scripts/analyze_ads_efficiency.py < /tmp/ads_merged.json
```

### ROAS/ACOS 快速计算

```bash
# 从 stdin 读取 JSON 数据
echo '{"cost": 5200, "sales": 22000, "clicks": 3500, "impressions": 120000, "conversions": 420}' | \
  python scripts/calculate_roas_acos.py
```

### 预算重新分配

```bash
echo '{"campaigns": [{"name": "SP-Exact", "current_spend": 5200, "sales": 22000}, {"name": "SB-Brand", "current_spend": 2100, "sales": 10000}], "total_budget": 10000}' | \
  python scripts/ads_budget_allocator.py
```

---

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

详细字段映射和 payload 模板见 `references/dataset_fields_mapping.md`。

---

## 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案：**

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①②均因工具限制无法使用时 | 多次 `opscli query run` + 客户端合并 |

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 检查拼写或 `opscli skills upgrade` 同步最新数据集 |
| 未登录 | 调用 `ops-auth` Skill，执行 `opscli auth login` |
| Token 过期 | 优先 `opscli auth token refresh --all`；刷新失败再 `opscli auth login` |
| opscli 未找到 | 激活虚拟环境或设置 `OPSCLI_BIN` |
| 分析结果异常 | 检查输入广告数据是否完整，补全缺失指标后重算 |

---

## 安装与管理

```bash
opscli skills install ops-advertising-efficiency-optimizer            # 安装
opscli skills install ops-advertising-efficiency-optimizer --force     # 强制重装
opscli skills status --pretty                                # 查看版本
opscli skills upgrade ops-advertising-efficiency-optimizer             # 升级
```