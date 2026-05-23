# ASIN 健康诊断 — 固化查询 Recipe

日常执行时直接使用本文件中的固化命令，不需要重新构造 payload 或搜索字段。只有在字段/权限变化、空结果、新场景时才需要读取 `dataset_fields_mapping.md`。

---

## 1. 主数据集查询（运营指标）

**数据集**：`ds_d35ac6f3910c`（非子查询类型，所有过滤放 `where`）

### CLI 模式 — 单个 ASIN

```bash
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|eq|\"B08XXXXXX\"" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/asin_main.json \
  --run --pretty
```

### CLI 模式 — 批量 ASIN

```bash
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|in|[\"B08XXXXXX\",\"B09YYYYYY\",\"B07ZZZZZZ\"]" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/batch_main.json \
  --run --pretty
```

### MCP 模式 — 单个 ASIN

```python
result = query_build_and_run(
    dataset="ds_d35ac6f3910c",
    dimensions=["asin", "product_name"],
    metrics=[
        "gross_profit_percent:avg",
        "convert_percent:avg",
        "ads_acos:avg",
        "refund_percent:avg",
        "sell_qty_days:avg"
    ],
    where_conditions=[
        'asin|eq|"B08XXXXXX"',
        'date_id|between|["2025-01-01","2025-01-31"]'
    ],
    limit=100,
    session_id="xxx",
    skills_dir="/path/to/skills"
)
```

### MCP 模式 — 批量 ASIN

将 `where_conditions` 中的 `asin|eq|` 改为 `asin|in|["B08X","B09Y","B07Z"]`，`limit` 改为 `1000`。

---

## 2. 辅助数据集查询（星级）

**数据集**：`ds_pdTYjvLRCadv`（非子查询类型）

### CLI 模式

```bash
opscli query build \
  --dataset ds_pdTYjvLRCadv \
  --dimension asin \
  --metric "star:avg:f_star" \
  --where "asin|eq|\"B08XXXXXX\"" \
  --output /tmp/asin_star.json \
  --run --pretty
```

批量时同样改用 `asin|in|[...]` 。

### MCP 模式

```python
star_result = query_build_and_run(
    dataset="ds_pdTYjvLRCadv",
    dimensions=["asin"],
    metrics=["star:avg:f_star"],
    where_conditions=['asin|eq|"B08XXXXXX"'],
    limit=100,
    session_id="xxx",
    skills_dir="/path/to/skills"
)
```

---

## 3. 数据合并与评分计算

### 步骤

1. 从主数据集结果提取：`gross_profit_percent`、`convert_percent`、`ads_acos`、`refund_percent`、`sell_qty_days`（映射为 `inventory_days`）
2. 从辅助数据集结果提取：`star`
3. 按 ASIN 合并
4. 输入 `scripts/calculate_health_score.py` 计算评分

### 合并后的 JSON 格式（脚本输入）

```json
{
  "asin": "B08XXXXXX",
  "product_name": "产品名称",
  "date_range": "2025-01-01 ~ 2025-01-31",
  "metrics": {
    "gross_profit_percent": 0.185,
    "convert_percent": 0.123,
    "ads_acos": 0.221,
    "refund_percent": 0.042,
    "inventory_days": 38,
    "star": 4.5
  }
}
```

批量时输入 JSON 数组，加 `--batch` 参数。

---

## 4. 环比/同比查询

需要对比上期数据时，使用 `dataComparison` 服务端条件聚合，一次 SQL 完成：

**CLI 模式**：`opscli query build` 暂不直接支持 `dataComparison`，需要用 `opscli query run` 传入完整 payload。

**MCP 模式**：使用 `query_build_and_run` 的 `data_comparison` 参数。

对比期字段裂变规则：
- `f_xxx`：当期值
- `last_f_xxx`：上期值
- `diff_f_xxx`：绝对差值
- `pct_f_xxx`：环比变化率

---

## 5. 字段映射速查

| 业务指标 | 字段名 | 数据集 | 聚合方式 | 说明 |
|---------|--------|--------|---------|------|
| ASIN | `asin` | 主+辅 | GROUP BY | 标准识别号 |
| 产品名称 | `product_name` | 主 | GROUP BY | 产品标题 |
| 毛利率 | `gross_profit_percent` | 主 | AVG | 毛利/销售额（公式指标） |
| 转化率 | `convert_percent` | 主 | AVG | 订单数/访问量 |
| ACOS | `ads_acos` | 主 | AVG | 广告费/广告销售额（公式指标） |
| 退款率 | `refund_percent` | 主 | AVG | 退款金额/销售额 |
| 周转天数 | `sell_qty_days` | 主 | AVG | 可售库存/日均销量 |
| 星级 | `star` | 辅 | AVG | 产品评分 1-5 |
| 评论数 | `reviews_qty` | 辅 | SUM | 评论总数 |
| 排名 | `subclass_rank` | 辅 | MIN | 类目排名 |

**注意事项**：
- `gross_profit_percent`、`ads_acos` 为公式指标，聚合时直接使用 `AVG()`
- 权限字段：`ds_d35ac6f3910c` 使用 `channel_uuid, listing_uuid`；`ds_pdTYjvLRCadv` 使用 `asin_ps_uuid`
- `userEmail`、`from.table`、`from.permission` 由 `opscli query build` 自动填充，**禁止手写**

---

## 6. 常见查询问题排查

| 问题 | 原因 | 处理 |
|------|------|------|
| 查询返回空 | ASIN 不存在或日期范围无数据 | 确认 ASIN 和日期范围 |
| 字段不存在 | 本地数据集版本过期 | `opscli skills upgrade ops-dataset-query` |
| 权限拒绝 | 用户无该 ASIN 查看权限 | 确认数据权限配置 |
| 公式指标返回异常 | 聚合方式错误 | 公式指标用 AVG，不要用 SUM |
