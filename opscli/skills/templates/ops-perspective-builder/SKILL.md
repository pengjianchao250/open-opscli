---
name: ops-perspective-builder
description: 从多个数据集中自动选择维度、指标和过滤条件，构建 BI 透视表和图表配置，输出可直接用于 Superset/Metabase 的配置方案。适用于创建运营看板、设计下钻分析视图、配置周报、构建销售趋势透视或利润结构拆解视图。
---

# 透视视图构建助手

运营透视图构建助手：根据用户选择的分析主题和数据集，自动构建 BI 透视图的维度、指标、过滤条件配置方案，输出可直接在 BI 工具中执行的配置清单。

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

- **标准透视图配置**：12 个内置标准透视图模板，覆盖销售、广告、库存、退款等核心运营场景
- **自定义透视图设计**：从零开始设计自定义透视图，支持任意维度组合
- **维度与指标推荐**：基于分析目标智能推荐维度和指标
- **下钻路径设计**：设计从集团到 ASIN 的多级下钻路径
- **过滤条件与阈值配置**：配置过滤条件和阈值高亮规则
- **跨数据集 Join 建议**：跨数据集分析时推荐 Join Key 和关联方案

## 工作流模式

```
┌─────────────────────────────────────────────────────────────┐
│                   四阶段工作流                           │
├─────────────────────────────────────────────────────────────┤
│ 阶段 1：需求分析                                │
│   ├── 理解分析目标（销售趋势/利润结构/广告效率等）              │
│   ├── 识别相关数据集（从 41 个可用数据集中筛选）                │
│   ├── 确定行维度、列维度、下钻维度                             │
│   └── 选择指标和聚合方式                                       │
│                                                              │
│ 阶段 2：配置设计                                │
│   ├── 将维度映射到数据集字段                                   │
│   ├── 设计指标计算（SUM/AVG/COUNT/公式）                       │
│   ├── 配置过滤条件和阈值                                       │
│   └── 选择合适图表类型                                         │
│                                                              │
│ 阶段 3：校验                                          │
│   ├── 验证字段存在于目标数据集                                  │
│   ├── 检查跨数据集 Join Key 兼容性                             │
│   ├── 验证公式语法正确性                                       │
│   └── 审查输出格式                                             │
│                                                              │
│ 阶段 4：结果生成                                   │
│   ├── 生成 JSON/YAML 配置                                      │
│   ├── 提供 SQL 查询模板                                        │
│   └── 包含 BI 工具导入说明                                     │
└─────────────────────────────────────────────────────────────┘
```

## 决策树：选择哪种透视图？

```
你的分析目标是什么？
├── 销售/利润总览
│   ├── 时间趋势 → 透视图 1（销售趋势多维透视）
│   └── 成本拆解 → 透视图 2（利润结构拆解）
├── 广告
│   ├── 活动诊断 → 透视图 4（广告效率多维分析）
│   └── 类型对比 → 透视图 5（广告类型对比）
├── 流量/转化
│   ├── 漏斗分析 → 透视图 6（流量与转化漏斗）
│   └── 设备拆分 → 透视图 7（设备流量拆分）
├── 库存
│   ├── 周转健康度 → 透视图 8（库存周转健康）
│   └── 结构分布 → 透视图 9（库存结构分布）
├── 运营
│   ├── 退款质量 → 透视图 3（退款与售后）
│   ├── 促销 ROI → 透视图 10（促销效果）
│   └── 团队排行 → 透视图 11（组织绩效排名）
└── 产品
    └── 健康诊断 → 透视图 12（ASIN 健康分）
```

## 12 个标准透视图

| # | 透视图名称 | 数据集 | 图表类型 | 复杂度 |
|---|-----------------|---------|-----------|------------|
| 1 | 销售趋势多维透视 | `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`) | Pivot + Line | P0 |
| 2 | 利润结构拆解 | `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`) | Pivot + Stacked Bar | P0 |
| 3 | 退款与售后 | `order_sale_trend_*` + `custom_refund_place_set` | Pivot + Heatmap | P1 |
| 4 | 广告效率多维分析 | `advertising_list_set` + `custom_type_*` | Pivot + Combo | P0 |
| 5 | 广告类型对比 | `custom_sp/sd/sb_ads_set` | Pivot + Bar | P2 |
| 6 | 流量与转化漏斗 | `custom_asin_sales_traffic_set` + `order_sale_trend_*` | Pivot + Funnel | P1 |
| 7 | 设备流量拆分 | `custom_type_asin_sales_traffic` | Pivot + Pie/Donut | P3 |
| 8 | 库存周转健康 | `custom_inventory_turnover_wk_set` (`ds_97zj6R0KDKpB`) | Pivot + Heatmap | P1 |
| 9 | 库存结构分布 | `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`) | Pivot + Stacked Area | P3 |
| 10 | 促销效果 | `custom_merge_deals` + `order_sale_trend_*` | Pivot + Timeline | P2 |
| 11 | 组织绩效排名 | `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`) | Pivot + Bar | P2 |
| 12 | ASIN 健康分 | `order_sale_trend_*` + `custom_crawler_listing_snapshot` (`ds_pdTYjvLRCadv`) | Pivot + Radar/Scatter | P3 |

## 输入格式

```json
{
  "goal": "分析销售趋势",
  "scope": "team_name = 'Kitchen-Team-A'",
  "time_range": "last_90_days",
  "dimensions": ["date_id", "dept_name", "platform_name", "country_name"],
  "metrics": ["original_price", "orders", "gross_profit"],
  "chart_type": "line_chart",
  "drill_down": true
}
```

## 输出格式

```json
{
  "perspective_name": "销售趋势多维透视",
  "datasets": ["ds_d35ac6f3910c"],
  "row_dimensions": [
    {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
    {"field": "dept_name", "alias": "部门"},
    {"field": "large_team_name", "alias": "大组"}
  ],
  "column_dimensions": [
    {"field": "platform_name", "alias": "平台"},
    {"field": "country_name", "alias": "国家"}
  ],
  "drill_dimensions": [
    {"field": "team_name", "alias": "销售小组"},
    {"field": "asin", "alias": "ASIN"}
  ],
  "metrics": [
    {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"},
    {"field": "orders", "aggregation": "SUM", "alias": "订单数"},
    {"field": "order_qty", "aggregation": "SUM", "alias": "销量"}
  ],
  "derived_metrics": [
    {"formula": "SUM(original_price) / SUM(orders)", "alias": "客单价", "format": "$#,##0.00"},
    {"formula": "(SUM(original_price) - LAG(SUM(original_price))) / LAG(SUM(original_price))", "alias": "环比增长率", "format": "0.00%"}
  ],
  "filters": [
    {"field": "date_id", "operator": "between", "value": "last_90_days"},
    {"field": "level_name", "operator": "in", "value": ["A", "B"]}
  ],
  "chart_config": {
    "primary_chart": "pivot_table",
    "secondary_chart": "line_chart",
    "x_axis": "date_id",
    "y_axis": "original_price",
    "series": "platform_name"
  },
  "thresholds": [
    {"field": "gross_profit_percent", "condition": "< 0.10", "format": "red_background"}
  ],
  "query_payload": {
    "dataset": "ds_d35ac6f3910c",
    "dimensions": ["date_id", "dept_name", "large_team_name", "platform_name", "country_name"],
    "metrics": ["original_price", "orders", "order_qty"],
    "filters": {
      "date_range": ["last_90_days"],
      "level_name": ["A", "B"]
    }
  },
  "sql_template": "SELECT ...",
  "setup_instructions": "在 Superset 中导入配置..."
}
```

## 脚本

| 脚本 | 用途 | 输入 | 输出 |
|--------|---------|-------|--------|
| `scripts/build_perspective_config.py` | 根据用户输入生成完整透视图配置 JSON | `goal`, `scope`, `time_range`, `dimensions`, `metrics` | 完整配置 JSON |

### 脚本使用方式

```bash
# 生成透视图配置
cat <<'EOF' | python opscli/skills/templates/ops-perspective-builder/scripts/build_perspective_config.py
{
  "goal": "销售趋势分析",
  "scope": "dept_name = 'Kitchen'",
  "time_range": "last_90_days",
  "dimensions": ["date_id", "dept_name", "platform_name"],
  "metrics": ["original_price", "orders"],
  "chart_type": "line_chart"
}
EOF
```

## 最佳实践

1. **优先使用 `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)** 进行跨域分析，该数据集覆盖销售、广告、流量、库存四大领域
2. **使用 `date_id` 作为主要时间维度**，支持日/周/月多级聚合
3. **至少包含一个组织维度**（dept_name / large_team_name / team_name）用于下钻
4. **为关键指标添加阈值高亮**，如毛利率低于 10% 标红
5. **跨数据集分析前先验证 Join Key**，确保字段类型和值域兼容
6. **公式指标必须使用完整表达式格式**，禁止同时传 `aggregation` 导致二次聚合

## 参考文档

- `reference/perspective_catalog.md` — 12 个标准透视图详细目录
- `reference/dataset_fields_mapping.md` — 数据集字段映射与 payload 模板
