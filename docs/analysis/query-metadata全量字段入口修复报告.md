# query metadata 全量字段入口 — 修复/补齐报告

> 日期：2026-07-26 ｜ 账号：张培良(id=59) ｜ 后端：http://ops.cm/api ｜ 分支：release

## 一、背景与问题

规划器内核化（Phase 4）引入了 `metadata_all`（后端 `query-metadata?include_all_fields=1` 全量元数据，经用户级缓存），但它**此前只被规划器 `query plan`/`query flow` 内部调用**，对外**没有独立入口**：

- CLI `opscli query metadata` 只有 `--dataset` / `--table-id`（走单表 `metadata()`），无"全量字段"选项。
- MCP `query_metadata` 工具无 `include_all_fields` 参数。
- 结果：**无法直接触发/查看全量字段索引**，也**难以诊断某个取数后端是否已上线 `include_all_fields`（Phase 0）**——只能靠 `query plan` 间接触发，排查 QA MCP 的"全量数据接口不同"问题时很不方便。

## 二、修复内容

给全量元数据补一个**直连入口**（CLI + MCP 对等，默认关闭、不改变既有行为）：

| 端 | 新增 | 行为 |
| --- | --- | --- |
| **CLI** | `opscli query metadata --all-fields` | 走 `metadata_all`（`_current_email` 读登录账号）；输出 `dataset_count`/`field_count`；`field_count=0` 时提示"后端可能未上线 include_all_fields" |
| **MCP** | `query_metadata(include_all_fields=True)` | 走 `metadata_all`（身份经 `_get_authenticated_user_email` + `_get_credential_dir`，同 `query_plan`）；返回 `{datasets, fields, dataset_count, field_count, stale, from_cache}`；无已验证账号则失败闭合 |

**实现要点**：两端复用已有 `metadata_all`（用户级缓存 + 账号隔离），`include_all_fields`/`--all-fields` 为 True 时忽略 `dataset/table_id/skills_dir`。改动文件：`opscli/mcp/tools/query.py`、`opscli/query/commands/cli.py`。

**代码提交**：`b9bcd17`（合并入 release `d48d14d`，已 push 远端 gitlab）。

## 三、e2e 验收（真实后端 ops.cm）

| 用例 | 结果 |
| --- | --- |
| 核心 `metadata_all`：datasets=44 / fields=1739 / 字段结构含 field_name·field_type·dataset_alias / stale=False | PASS ✅ |
| 一致性：前 5 数据集"全量字段数 == 单表累加" | PASS ✅ |
| MCP `query_metadata(include_all_fields=True)`：success / field_count=1739 / dataset_count=44 / 含 datasets·fields 列表 | PASS ✅ |
| 无回归：默认（不带 include_all_fields）仍是单表行为、不返回 field_count | PASS ✅ |
| CLI `opscli query metadata --all-fields`（真实后端）→ dataset_count=44 field_count=1739 | PASS ✅ |
| 单元测试（CLI --all-fields / MCP include_all_fields / 无账号失败闭合）3 例 + 相关套件 | 3 新增 + 31 passed（仅 catalog/intent 2 既有基线） |

**结论：全部通过。**

## 四、诊断用法（本次补齐的核心价值）

一条命令即可判断**任意取数后端是否支持 `include_all_fields`（Phase 0）**：

```bash
# CLI
opscli query metadata --all-fields
#  → field_count 非 0（如 1739）= 后端已上线 Phase 0；field_count=0 = 未上线（附提示）

# MCP
query_metadata(include_all_fields=True)   # 看返回的 field_count
```

排查 MCP 全量数据问题时的定位流程：
1. 对目标 MCP `list_tools`，确认有无 `query_plan`/`query_flow`（判断是否已部署 Phase 4 内核版）；
2. 用本入口 `--all-fields` / `include_all_fields=True` 对其后端探测 `field_count`：
   - `field_count=0` → 该取数后端未上线 `include_all_fields`（Phase 0），需后端部署；
   - `field_count` 非 0 → 后端已支持，问题不在此。

> 注意：`metadata_all` 与 `skills upgrade`/CSV 无关（内核已解耦）；`include_all_fields` 是**后端接口特性**，不是 MCP 服务器的 skills upgrade 问题。
