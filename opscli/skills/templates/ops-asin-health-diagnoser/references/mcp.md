---
name: ops-asin-health-diagnoser
mcp-version: v0.2.0
description: ASIN 健康诊断 MCP 模式操作手册
---

# ASIN 健康诊断（MCP 无状态模式）

使用 MCP Tool 查询 ASIN 运营数据，通过 `scripts/calculate_health_score.py` 计算健康评分。无状态模式：服务器不保存 OAuth 凭证，认证信息由调用方传入。

> 认证门禁和运行模式判断见主 `SKILL.md`，本文件只补充 MCP 特有 Tool 调用。

---

## MCP Tool 调用参考

### 查询主数据集指标

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

### 查询辅助数据集（星级）

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

### 批量查询

将 `where_conditions` 中 `asin|eq|` 改为 `asin|in|["B08X","B09Y","B07Z"]`，`limit` 改为 `1000`。

---

## 计算评分

```python
# 合并数据后写入 JSON，调用脚本
import json, subprocess

input_data = {
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

result = subprocess.run(
    ["python", "scripts/calculate_health_score.py", "--pretty"],
    input=json.dumps(input_data),
    capture_output=True, text=True
)
health_result = json.loads(result.stdout)
```

---

## 比较类查询

| 优先级 | 方案 | 说明 |
|--------|------|------|
| 1 | `dataComparison`（服务端条件聚合） | 一次 SQL |
| 2 | `MOY` 高级计算 | 服务端窗口函数 |
| 3 | 多次 `query_build_and_run` + 客户端合并 | 兜底 |

---

## MCP 认证工具速查

```python
# 检查 session
auth_is_authenticated(session_id="xxx")

# 获取 JWT
auth_get_token(system="ops", session_id="xxx")
```

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `skills_upgrade(name="ops-dataset-query")` |
| dataset_alias 不存在 | 检查拼写或 `skills_upgrade` |
| session 无效 | `auth_login_start()` → 浏览器授权 → `auth_login_poll()` |

---

## 安装与管理

```python
skills_install(name="ops-asin-health-diagnoser", skills_dir="/path/to/skills")
skills_install(name="ops-asin-health-diagnoser", force=True, skills_dir="/path/to/skills")
skills_status(skills_dir="/path/to/skills")
skills_upgrade(name="ops-asin-health-diagnoser", skills_dir="/path/to/skills")
```
