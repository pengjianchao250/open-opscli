# data/ 字段索引使用说明（防误用）

> 正常流程不需要读取本目录：字段与口径一律以内核规划器（`opscli query plan` / `opscli query flow`）
> 输出的 `execution_ref` 为准——规划器读取后端授权元数据（经用户级缓存），不读本目录。
> 本目录只服务于 `opscli query metadata` / `catalog` / `intent` 的本地回退缓存，以及图表脚本的字段映射兜底。

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

## VERSION.json 与 Skill 版本是两个概念（不是缺陷）

模板内的 `data/VERSION.json` 只是占位符（`data_state: placeholder`）。安装后执行
`opscli skills upgrade ops-dataset-query` 会用远端拉取的**元数据快照版本**（形如 `v1.1.29`）
整体覆盖本目录，包括 `VERSION.json` 的 `version` 字段。

因此已安装环境里会同时看到两个版本号，语义不同、互不对应：

| 位置 | 含义 | 谁来更新 |
| --- | --- | --- |
| `SKILL.md` frontmatter 的 `version` | **Skill 自身版本**（文档与流程规则的版本），是判断 Skill 新旧的唯一依据 | 随 Skill 发版 |
| `data/VERSION.json` 的 `version` | **元数据快照版本**（后端数据集/字段索引的批次号） | `opscli skills upgrade` 拉取远端元数据时覆盖 |

两者数字不一致属正常现象，不要据此判断 Skill 安装异常或版本回退。
