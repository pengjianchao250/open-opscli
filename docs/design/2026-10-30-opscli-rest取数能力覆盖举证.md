# opscli 与 opscli-mcp REST 取数能力覆盖举证

- 核对日期：2026-10-30
- 核对对象：`E:/wwwroot/localProjects/open-opscli`
- 线上服务：`https://mcp.ops.aukeyit.com`
- 线上合同来源：`https://mcp.ops.aukeyit.com/openapi.json`（与 `/docs` 使用同一 OpenAPI）
- 结论状态：已完成静态覆盖核对；未执行需要用户身份的业务取数回归

## 1. 结论摘要

当前 `opscli-mcp` REST API **没有覆盖所有 `opscli` 取数能力**。

已确认覆盖或基本覆盖的能力主要是：

- `opscli query` 的主要规划、元数据、构造、执行和图表查询入口；
- Keepa 的场景列表和场景执行入口；
- 西柚公共操作目录和操作执行入口；
- SellerSprite 的场景、任务、Listing Analysis、状态、结果和导出信息入口。

未在当前线上 REST OpenAPI 中发现对应路由的取数能力包括：

- `opscli asin-data`；
- `opscli google-trends`；
- `opscli sif`；
- `opscli yingyan`；
- `opscli amazon`、`amazon-rufus`、`asin-review`、Amazon reviews；
- `opscli canopy`、`scrape-do` 等远端 MCP 命令面；
- `calculator`、`baiyi`、Shopify、Feedtask 等其他业务命令中的取数入口。

因此，当前不能形成“任意本地 `opscli` 取数命令都可以直接替换为线上 REST”的结论。迁移项目仍需按照实际调用逐项建立兼容报告。

## 2. 核对方法

本次核对比较三类证据：

1. 顶级 CLI 注册表和各业务 CLI 的命令定义；
2. `open-opscli` 内部 FastAPI REST 路由；
3. 线上 `openapi.json` 实际暴露的 HTTP 路径、方法和响应媒体类型。

本次线上 OpenAPI 实际返回的业务路径如下：

```text
/api/v1/auth/ensure
/api/v1/query/plan
/api/v1/query/flow
/api/v1/query/preferences
/api/v1/query/metadata
/api/v1/query/catalog
/api/v1/query/intents/match
/api/v1/query/run
/api/v1/query/build
/api/v1/query/simple
/api/v1/charts/{chart_uuid}
/api/v1/charts/{chart_uuid}/run
/api/v1/charts/{chart_uuid}/doc
/api/v1/keepa/scenarios
/api/v1/keepa/run
/api/v1/xydc/scenarios
/api/v1/xydc/run
/api/v1/seller-sprite/scenarios
/api/v1/seller-sprite/quota
/api/v1/seller-sprite/jobs/status
/api/v1/seller-sprite/jobs
/api/v1/seller-sprite/jobs/{job_id}
/api/v1/seller-sprite/jobs/{job_id}/result
/api/v1/seller-sprite/jobs/{job_id}/export
/api/v1/seller-sprite/listing-analysis/jobs
/api/v1/seller-sprite/listing-analysis/jobs/{job_id}
/api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result
```

本次没有提交带真实用户凭证的查询请求，因此以下“覆盖”表示静态合同和路由覆盖，不能替代真实用户权限、参数、分页、返回字段和错误语义回归。

## 3. CLI 与 REST 覆盖矩阵

### 3.1 Query

CLI 来源：[`opscli/query/commands/cli.py`](E:/wwwroot/localProjects/open-opscli/opscli/query/commands/cli.py)

| CLI 能力 | REST 入口 | 覆盖判断 |
|---|---|---|
| `plan` | `POST /api/v1/query/plan` | 已覆盖 |
| `flow` | `POST /api/v1/query/flow` | 已覆盖 |
| `preferences` | `GET /api/v1/query/preferences` | 已覆盖 |
| `metadata` | `GET /api/v1/query/metadata` | 已覆盖，线上参数不暴露本地路径 |
| `catalog` | `GET /api/v1/query/catalog` | 已覆盖，但需确认线上是否允许本地回退 |
| `intent` | `POST /api/v1/query/intents/match` | 已覆盖 |
| `run` | `POST /api/v1/query/run` | 已覆盖 |
| `build` | `POST /api/v1/query/build` | 已覆盖 |
| `simple` | `POST /api/v1/query/simple` | 已覆盖 |
| `chart` | `GET /api/v1/charts/{chart_uuid}` | 已覆盖 |
| `chart --run` | `POST /api/v1/charts/{chart_uuid}/run` | 已覆盖 |
| `chart-doc` | `GET /api/v1/charts/{chart_uuid}/doc` | 已覆盖 |

Query 的 REST 路由与 CLI/MCP 共用 `QueryManager`，因此是当前最适合迁移项目优先适配的能力。但 CLI 的 `--result-file`、`--save-result`、`--skills-dir`、`--result-dir` 等本地文件选项不属于 REST 合同，需要由站点自行决定分页、持久化和导出。

### 3.2 Keepa

CLI 来源：[`opscli/keepa/cli.py`](E:/wwwroot/localProjects/open-opscli/opscli/keepa/cli.py)

| CLI 能力 | REST 入口 | 覆盖判断 |
|---|---|---|
| `scenarios` | `GET /api/v1/keepa/scenarios` | 已覆盖 |
| `run` | `POST /api/v1/keepa/run` | 已覆盖主要执行入口 |
| `quota-status` | 当前 OpenAPI 无对应路由 | 未覆盖 |
| `job-status` | 当前 OpenAPI 无独立路由 | 部分能力可能包含在 `run` 返回中，需行为验证 |
| `export` | 当前 OpenAPI 无独立路由 | 未覆盖为独立 REST 操作 |

Keepa 不能仅凭 `POST /api/v1/keepa/run` 就认定全部 CLI 能力等价。需要确认长任务、任务复用、导出格式和文件下载信息是否都在该接口响应中完成。

### 3.3 西柚

CLI 来源：[`opscli/xiyou/cli.py`](E:/wwwroot/localProjects/open-opscli/opscli/xiyou/cli.py)

| CLI 能力 | REST 入口 | 覆盖判断 |
|---|---|---|
| `operations` | `GET /api/v1/xydc/scenarios` | 基本覆盖，名称不同但均返回公共操作目录 |
| `call` | `POST /api/v1/xydc/run` | 基本覆盖，需逐项核对 operation 和 payload 合同 |

西柚的 REST 路由将 AppHub 身份和调用用户传入西柚内核，但具体 operation 的参数、返回结构和供应商额度仍需要按场景回归。

### 3.4 SellerSprite

CLI 来源：[`opscli/seller_sprite/cli.py`](E:/wwwroot/localProjects/open-opscli/opscli/seller_sprite/cli.py)

| CLI 能力 | REST 入口 | 覆盖判断 |
|---|---|---|
| `scenarios` | `GET /api/v1/seller-sprite/scenarios` | 已覆盖 |
| `quota-status` | `GET /api/v1/seller-sprite/quota` | 已覆盖 |
| `run` | `POST /api/v1/seller-sprite/jobs` | 已覆盖 |
| `jobs-status` | `POST /api/v1/seller-sprite/jobs/status` | 已覆盖 |
| `job-status` | `GET /api/v1/seller-sprite/jobs/{job_id}` | 已覆盖 |
| `export` | `GET /api/v1/seller-sprite/jobs/{job_id}/export` | 已覆盖为导出信息接口 |
| `listing-analysis-submit` | `POST /api/v1/seller-sprite/listing-analysis/jobs` | 已覆盖 |
| `listing-analysis-status` | `GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}` | 已覆盖 |
| `listing-analysis-result` | `GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result` | 已覆盖 |

SellerSprite 的 REST 路由对 JSON 结果有专门的内联合同；XLS/XLSX 任务通常返回导出信息，而不是直接在 HTTP 响应中返回二进制文件。迁移项目仍需处理任务轮询、结果落库和导出文件生命周期。

### 3.5 未发现对应 REST 路由的取数模块

以下命令在 CLI 或 MCP 注册中存在，但当前线上 OpenAPI 没有对应业务路由：

| 模块 | 本地/远端能力示例 | 当前 REST 判断 |
|---|---|---|
| `asin-data` | `basic`、`bi`、`collect`、`category-top`、`live-data`、报告文件 | 未覆盖 |
| `google-trends` | `scenarios`、`run`、`job-status`、`export` | 未覆盖 |
| `sif` | 查销量、查流量、排名、时光机、对比 | 未覆盖 |
| `yingyan` | 数据集、只读 SQL、相似词、报告任务 | 未覆盖 |
| `amazon` | 商品抓取、搜索、历史快照 | 未覆盖 |
| `amazon-rufus` | 浏览器状态、问答采集、远程授权 | 未覆盖 |
| `asin-review` | ASIN 复盘查询 | 未覆盖 |
| `canopy` / `scrape-do` | 远端 MCP 场景和任务 | 未覆盖 |
| `calculator` / `baiyi` | 产品数据、计算器数据 | 未覆盖 |

这里的“未覆盖”是指当前 REST OpenAPI 没有对应路径，不代表底层系统永远无法提供能力；如果迁移项目依赖这些模块，需要新增正式 REST 合同或采用其他经过确认的线上方案。

## 4. 返回值边界：JSON 与文件

### 4.1 本地 `opscli` CLI

本地 CLI **不是统一只返回 JSON，也不是统一直接返回文件**，取决于命令和参数：

- Query、Keepa、SellerSprite 等正式远端命令通常向 stdout 输出 JSON 信封；
- Query 可通过 `--result-file`、`--save-result` 把结果写入本地 JSON 文件；
- Keepa、SellerSprite、Google Trends 等任务型命令可以返回导出信息，并通过 `export` 获取 XLS/XLSX 等文件；
- `asin-data` 可能生成或上传 XLSX、JSON、报告文件，并返回文件路径、URL 或文件索引；
- Amazon 抓取命令还可能写入本地历史 JSONL；
- 本地命令的 `output_dir`、`result_dir`、`skills_dir` 等选项会产生本地文件副作用。

所以迁移时要记录两个维度：

```text
业务结果格式：JSON / rows / columns / 对象
交付载体：stdout / 本地文件 / 下载 URL / OSS 文件 / 数据库
```

### 4.2 `opscli-mcp` REST

当前线上 OpenAPI 中，业务 REST 接口的响应媒体类型均为 `application/json`。REST 通常返回统一信封：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

因此当前 REST 的直接响应是 JSON：

- Query 直接返回查询结果、行数据、元数据或图表结构；
- Keepa 和西柚返回场景结果及任务/额度信息；
- SellerSprite 的 JSON 任务可以返回内联 `columns + rows`；
- XLS/XLSX 等文件任务通常返回文件元数据、导出状态或下载信息；
- 当前 OpenAPI 未显示直接返回 `application/octet-stream` 的二进制下载路由。

这意味着“REST 返回 JSON”不等于“所有业务结果都是 JSON”。文件型结果可能由 JSON 描述文件名、状态、下载地址或文件索引，调用方还需要按合同取得文件。

### 4.3 对迁移适配的影响

迁移项目不能只做如下替换：

```text
opscli command → REST URL
```

还必须确认：

1. 原 CLI 需要的是 JSON 数据还是文件；
2. 原页面依赖哪些字段和嵌套结构；
3. REST 返回的是内联 JSON、任务状态还是文件信息；
4. 是否需要轮询、下载、解压、解析或落库；
5. 文件下载 URL 是否带当前用户权限和有效期；
6. 结果写入缓存、SQLite、JSON、Excel 后是否需要用户隔离。

## 5. 对迁移项目的判定规则

迁移项目的 REST 兼容状态建议按“实际页面依赖”判定，而不是按模块数量判定：

| 状态 | 判定条件 |
|---|---|
| `rest_ready` | 页面所需取数调用均有正式 REST 合同，参数、权限、结果和错误已验证 |
| `rest_partial` | 核心页面可运行，但非核心导出、历史或辅助功能未覆盖 |
| `snapshot_only` | 关键数据没有 REST 实时入口，只能使用快照或预计算 |
| `rest_blocked` | 核心页面依赖没有线上等价能力的 CLI/MCP 能力 |

只有项目实际依赖的核心路径达到 `rest_ready` 或明确采用 `snapshot_only`，才能进入后续用户数据隔离实施。用户数据隔离命令仍保持独立，不把所有 REST 能力覆盖率作为新建或迁移流程的全局门禁。

## 6. 后续验证建议

静态核对之后，按迁移项目逐项做最小业务回归：

1. 扫描项目源码中的 `opscli` CLI、MCP Tool、远端 URL 和本地文件读写；
2. 将每个调用匹配到本矩阵或标记为未知；
3. 对 `query`、Keepa、西柚、SellerSprite 先验证请求参数、当前用户鉴权和返回结构；
4. 对文件型结果验证任务状态、下载信息和文件内容；
5. 对未覆盖模块明确选择新增 REST、快照或人工适配；
6. 只有线上取数基线稳定后，再执行用户数据隔离的 `inspect → plan → apply → verify`。

## 7. 证据文件索引

- CLI 总注册表：[`opscli/cli.py`](E:/wwwroot/localProjects/open-opscli/opscli/cli.py)
- Query REST：[`opscli/api/routers/query.py`](E:/wwwroot/localProjects/open-opscli/opscli/api/routers/query.py)
- Keepa REST：[`opscli/api/routers/keepa.py`](E:/wwwroot/localProjects/open-opscli/opscli/api/routers/keepa.py)
- 西柚 REST：[`opscli/api/routers/xydc.py`](E:/wwwroot/localProjects/open-opscli/opscli/api/routers/xydc.py)
- SellerSprite REST：[`opscli/api/seller_sprite.py`](E:/wwwroot/localProjects/open-opscli/opscli/api/seller_sprite.py)
- MCP 注册总入口：[`opscli/mcp/server.py`](E:/wwwroot/localProjects/open-opscli/opscli/mcp/server.py)
- REST API 调用规范：[`OPSCLI_API调用规范.md`](E:/wwwroot/localProjects/open-opscli/opscli/skills/templates/ops-app-build-spec/assets/backend/docs/开发指南/OPSCLI_API调用规范.md)

