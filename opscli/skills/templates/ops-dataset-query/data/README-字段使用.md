# data/ 字段索引使用说明（防误用）

> 正常流程不需要读取本目录：字段与口径一律以 `python3 scripts/query_plan.py` 输出的
> `execution_ref` 为准。本说明只服务于确需直接查看索引文件的排错场景。

## dataset_fields.csv 列语义（最容易踩的坑）

| 列 | 含义 | 能否用于查询 payload 的 `field` |
|----|------|------|
| `field_name`（第4列） | **真实查询字段名** | ✅ 唯一正确来源 |
| `verbose_name`（第5列） | 中文展示名 | ❌ 仅展示用 |
| `global_alias`（第6列，`f_` 开头哈希） | 全局别名索引 | ❌ **禁止**——部分数据集提交会报「字段不存在」（e2e 实测踩坑） |

## 其他文件

- `datasets.csv`：数据集卡片（`table_id`/`dataset_alias`/中文名 `description`）。
- `dataset_select_columns.csv`：可显式筛选列 → 组件数据集 alias 的关系（枚举入口）。
- `VERSION.json`：元数据版本。存在两种形状：updater 形状（含 `data_state`）与
  技能广场发布包形状（含 `dataset_count`，无 `data_state`），组合入口已兼容两者。
