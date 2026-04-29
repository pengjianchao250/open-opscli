# 广告效率优化器数据集字段映射

## 主数据集：advertising_list_set (ds_0759e20F0DrG)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| 活动名称 | `campaign_name` | STRING | GROUP BY | 广告活动名称 |
| 广告组名称 | `ad_group_name` | STRING | GROUP BY | 广告组名称 |
| 广告类型 | `ads_type` | STRING | GROUP BY | SP/SD/SB/SBV |
| 广告费 | `advertising_fee` | DECIMAL | SUM | 广告花费 |
| 广告销售额 | `ads_sales_cny` | DECIMAL | SUM | 广告销售额（人民币） |
| 点击量 | `ads_clicks` | INT | SUM | 点击量 |
| 曝光量 | `ads_impressions` | INT | SUM | 曝光量 |
| 转化订单 | `ads_conversions` | INT | SUM | 广告订单数 |
| 日期 | `date_id` | DATE | FILTER | 数据日期 |

## 辅助数据集：custom_sp_ads_set (ds_fE0flP7WonsJ)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| 广告类型 | `ad_type` | STRING | GROUP BY | SP/SD/SB/SBV 分类 |
| SP花费 | `ads_sp` | DECIMAL | SUM | Sponsored Products 花费 |
| SD花费 | `ads_sd` | DECIMAL | SUM | Sponsored Display 花费 |
| SB花费 | `ads_sb` | DECIMAL | SUM | Sponsored Brands 花费 |
| SBV花费 | `ads_sbv` | DECIMAL | SUM | Sponsored Brands Video 花费 |
| 广告销售额 | `ads_sales_cny` | DECIMAL | SUM | 广告销售额 |
| 日期 | `date_id` | DATE | FILTER | 数据日期 |

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

### 广告活动级诊断（ds_0759e20F0DrG，子查询类型，inner_where_enabled=true）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_0759e20F0DrG",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_0759e20F0DrG.campaign_name", "alias": "f_campaign" },
      { "expr": "ds_0759e20F0DrG.ad_group_name", "alias": "f_ad_group" },
      { "expr": "ds_0759e20F0DrG.ads_type", "alias": "f_ad_type" },
      { "expr": "SUM(ds_0759e20F0DrG.advertising_fee)", "alias": "f_cost" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_sales_cny)", "alias": "f_sales" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_clicks)", "alias": "f_clicks" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_impressions)", "alias": "f_impressions" },
      { "expr": "SUM(ds_0759e20F0DrG.ads_conversions)", "alias": "f_conversions" }
    ],
    "innerWhere": [
      { "operator": "AND", "conditions": [] },
      { "operator": "AND", "conditions": [
        { "field": "ds_0759e20F0DrG.campaign_name", "operator": "eq", "value": "Water-Bottle-SP-Exact" }
      ]}
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_0759e20F0DrG.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_campaign", "f_ad_group", "f_ad_type"],
    "limit": 1000
  }
}
```

### 广告类型组合分析（ds_fE0flP7WonsJ，非子查询类型）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_fE0flP7WonsJ",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_fE0flP7WonsJ.ad_type", "alias": "f_ad_type" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sp)", "alias": "f_sp_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sd)", "alias": "f_sd_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sb)", "alias": "f_sb_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sbv)", "alias": "f_sbv_spend" },
      { "expr": "SUM(ds_fE0flP7WonsJ.ads_sales_cny)", "alias": "f_total_sales" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_fE0flP7WonsJ.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ad_type"],
    "limit": 1000
  }
}
```

### 公式指标查询示例

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_0759e20F0DrG",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_0759e20F0DrG.campaign_name", "alias": "f_campaign" },
      { "expr": "ROUND(SUM(ds_0759e20F0DrG.advertising_fee) / SUM(ds_0759e20F0DrG.ads_sales_cny), 4)", "alias": "f_acos" },
      { "expr": "ROUND(SUM(ds_0759e20F0DrG.ads_sales_cny) / SUM(ds_0759e20F0DrG.advertising_fee), 2)", "alias": "f_roas" }
    ],
    "innerWhere": [
      { "operator": "AND", "conditions": [] },
      { "operator": "AND", "conditions": [] }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_0759e20F0DrG.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_campaign"],
    "limit": 1000
  }
}
```

## 注意事项

1. **子查询类型数据集**：`ds_0759e20F0DrG` 为**子查询类型**（`inner_where_enabled=true`）：
   - 维度过滤条件（如 campaign_name）应放 `innerWhere[1]`
   - 日期等全局条件放 `where`
   - `innerWhere[0]` 通常保留空条件数组，供系统内部使用
2. **非子查询类型数据集**：`ds_fE0flP7WonsJ` 为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。
3. **字段别名**：返回结果中字段别名为 `f_[随机哈希]`，业务逻辑中应通过映射关系识别，禁止硬编码。
4. **自动生成字段**：`userEmail`、`from.table`、`from.permission`、`from.database` 等字段由 `opscli query build` 命令根据当前登录用户和数据集 metadata 自动生成，**禁止在 Skill 文档或脚本中手写这些字段**。
5. **公式指标**：ACOS、ROAS 等公式指标必须使用完整表达式格式，禁止额外传 `aggregation` 导致二次聚合。
