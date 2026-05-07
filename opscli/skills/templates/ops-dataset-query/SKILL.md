---
name: ops-dataset-query
description: 根据当前环境自动选择 CLI 或 MCP 方式查询本地数据集索引并执行数据查询
version: see data/VERSION.json
---

# ops-dataset-query

用于检索本地缓存的数据集、字段和查询元数据，并通过正式查询入口执行数据查询、图表查询和数据更新。

---

## 何时使用本 Skill

- 需要搜索可用数据集、维度、指标和字段别名
- 需要执行普通聚合查询、数据对比（环比/同比）、MOY 趋势分析
- 需要通过图表 ID 或 chart UUID 直接获取查询结构
- 需要刷新本地缓存的数据集索引和查询元数据

> **简化接口优先**：普通聚合、数据对比、MOY 趋势、子查询等场景，优先使用简化接口（`opscli query simple` / `query_simple`），服务端自动处理 `innerWhere`、`translate`、`MOY` 展开等技术细节。仅当简化接口不满足需求时，才手写完整 payload。
>
> **Catalog 优先选数据集**：当用户只给出自然语言需求、没有指定 dataset 时，优先使用 `opscli query catalog`（CLI）或 `query_catalog`（MCP）读取 dataset catalog 的 `intents`，按使用案例、关键词、场景描述和优先级选择候选数据集；再读取本地 `data/dataset_fields.csv` / `query_metadata.json` 校验字段是否存在并构造查询。仅当本地 CSV/JSON 数据为空时，才回退调用 `opscli query metadata`（CLI）或 `query_metadata`（MCP）获取字段信息。

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

> **【强制】快速判断规则**：
> - 当前工作目录包含 `opscli/` 源码（即 opscli 项目本身） → **必须用 CLI**
> - 当前环境可直接执行 `opscli` 命令（终端 / Claude Code） → **优先用 CLI**
> - 仅当无法执行本地命令时（如 ChatGPT / 纯 MCP 宿主） → 用 MCP

优先级如下：

1. 用户明确指定 → 直接遵循
2. **当前在 `opscli` 项目目录下** → **必须使用 CLI**，读取 `references/cli.md`
3. 当前终端可执行 `opscli` 命令 → 默认使用 CLI，读取 `references/cli.md`
4. 当前任务基于 MCP Tool 协作，或宿主无法执行本地命令 → 使用 MCP，读取 `references/mcp.md`
5. CLI 首次调用失败 → 直接切到 MCP，读取 `references/mcp.md`
6. MCP 也不可用 → 帮助用户安装 `aukeys-opscli`

建议提问方式：

- `当前 CLI 与 MCP 入口都不可用。你希望我先帮你安装 aukeys-opscli，再继续处理吗？`

简化原则：

- **默认优先 CLI**，它是 `opscli` 模块的正式入口，最贴近真实交付路径
- **在 opscli 项目目录下禁止走 MCP**，因为 CLI 一定可用且参数处理更完整
- 不单独检查发行包、命令路径、子命令 help；用”首次正式调用是否可执行”作为唯一验证
- 一旦 CLI 和 MCP 都可行，优先保持单一路径，不要来回切换
- CLI 首次正式调用失败后，直接切到 MCP，不额外询问
- 只有在 MCP 版本也不可用时，才回退为帮助用户安装 `aukeys-opscli`

---

## 阅读入口

- **简化接口说明**：`references/simple-query-guide.md`（推荐优先阅读）
- CLI 模式：继续阅读 `references/cli.md`
- MCP 模式：继续阅读 `references/mcp.md`
- 完整 query payload 规范：`references/data-query-service-dev-guide.md`（仅当简化接口不满足需求时参考）

---

## 使用原则

- **简化接口优先**：普通聚合、数据对比、MOY 趋势、子查询等场景，优先使用简化接口（`opscli query simple` / `query_simple`），参数结构见 `references/simple-query-guide.md`
- 仅当简化接口不满足需求时（如复杂的 `joins`、`union`、自定义子查询），才手写完整 query payload + `opscli query run` / `query_run`
- 所有远端查询动作必须统一走选定模式下的正式查询入口，禁止直接调用后端 HTTP 接口
- 认证检查仍然是强制门禁，具体流程以对应 reference 文档为准
- 用户未指定 dataset 时，优先使用 `opscli query catalog`（CLI）或 `query_catalog`（MCP）读取 dataset catalog 的 `intents` 选择候选数据集；catalog 为空或缺失时，回退到 `datasets.csv` + `dataset_fields.csv` 关键词检索
- 查询前优先检查目标 `dataset_alias`、`field_name`、`global_alias`、`verbose_name` 是否存在于本地索引或 metadata；不要先猜字段再直接构造 payload
- **【强制】本地搜索结果为空时，必须先升级再重试**：无论搜索的是数据集还是字段，只要返回空列表 `[]`，立即执行升级命令后重新搜索一次，不要直接告知用户"找不到"
- 如果字段或数据集不存在，优先执行当前模式下的 Skill 升级，再重新检查一次
- CLI 模式使用 `opscli skills upgrade ops-dataset-query`；MCP 模式使用 `skills_upgrade(name="ops-dataset-query")`
- 升级后若字段仍不存在，应明确告知用户当前本地索引和 metadata 中没有该字段，不要伪造字段名继续查询
- 涉及环比、同比、趋势对比时，优先使用服务端能力，不要默认降级为多次查询后本地拼接
- 处理 chart 查询时，优先采用服务端返回的 `datasets + queries` 双层结构：`datasets` 负责公共字段语义，`queries` 负责执行结构；本地 CSV 仅作字段映射兜底
