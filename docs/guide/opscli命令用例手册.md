# opscli 命令用例手册

本文档基于当前仓库代码整理，覆盖 `opscli` 顶级命令、全部子命令、参数说明与常见使用示例。

- 代码基线：`aukeys-opscli` `0.0.35`
- 命令入口：`opscli`
- 主要来源：
  - `opscli/cli.py`
  - `opscli/auth/cli.py`
  - `opscli/amazon/commands/cli.py`
  - `opscli/query/commands/cli.py`
  - `opscli/skills/commands/cli.py`
  - `opscli/seller_sprite/commands/cli.py`
  - `opscli/mcp/cli.py`

## 1. 命令总览

```text
opscli
├── auth
│   ├── login
│   ├── logout
│   ├── doctor
│   ├── token
│   │   ├── status
│   │   ├── get
│   │   ├── check
│   │   └── refresh
│   └── system
│       ├── list
│       ├── sync
│       ├── add
│       └── remove
├── amazon
│   ├── scrape
│   ├── payload
│   ├── search
│   ├── schema
│   └── history
├── query
│   ├── metadata
│   ├── catalog
│   ├── run
│   ├── build
│   ├── simple
│   ├── chart
│   └── chart-doc
├── skills
│   ├── list
│   ├── install
│   ├── status
│   └── upgrade
├── seller-sprite
│   ├── collect
│   ├── frequency
│   ├── keyword-mining
│   ├── keyword-reverse
│   ├── archive
│   ├── login
│   ├── login-status
│   ├── schema
│   └── account
│       ├── save
│       ├── list
│       └── delete
└── mcp
    └── user
        ├── list
        ├── add
        ├── remove
        └── rotate
```

## 2. 通用说明

### 2.1 顶级全局参数

| 参数 | 说明 |
| --- | --- |
| `--version` / `-V` | 输出版本号后退出 |
| `--install-completion` | 为当前 shell 安装自动补全 |
| `--show-completion` | 输出当前 shell 的补全脚本 |
| `--help` | 查看帮助 |

### 2.2 输出风格

| 模块 | 输出风格 |
| --- | --- |
| `auth` | 以 Rich 文本表格和状态提示为主 |
| `auth token get` | 纯文本输出 JWT，适合脚本 |
| `amazon` | 标准 JSON |
| `query` | 标准 JSON |
| `skills` | 标准 JSON；交互安装时会先显示 TUI 选择界面 |
| `seller-sprite` | 标准 JSON |
| `mcp` | 标准 JSON |

### 2.3 通用约定

- 所有命令都支持 `--help`。
- `amazon`、`query`、`skills`、`seller-sprite`、`mcp` 模块普遍支持 `--pretty` 进行 JSON 美化输出。
- `query build` 中 `--dimension`、`--metric`、`--where`、`--having`、`--order-by` 都可以重复传入多次。

## 3. 顶级命令 `opscli`

### 3.1 查看版本

**用法**

```bash
opscli --version
opscli -V
```

**示例**

```bash
opscli -V
```

### 3.2 查看总帮助

**用法**

```bash
opscli --help
```

**示例**

```bash
opscli --help
```

## 4. 认证模块 `opscli auth`

用于登录、退出、诊断、获取系统 JWT、维护系统注册表。

### 4.1 `opscli auth login`

发起 OAuth2 Device Flow 登录，自动尝试打开浏览器；登录成功后会自动同步系统列表。

**用法**

```bash
opscli auth login
```

**参数**

无。

**示例**

```bash
opscli auth login
```

### 4.2 `opscli auth logout`

清除本地所有认证凭证。

**用法**

```bash
opscli auth logout
```

**参数**

无。

**示例**

```bash
opscli auth logout
```

### 4.3 `opscli auth doctor`

检查当前登录状态与各系统 URL 连通性。

**用法**

```bash
opscli auth doctor
```

**参数**

无。

**示例**

```bash
opscli auth doctor
```

### 4.4 `opscli auth token status`

查看当前登录状态、Session 过期时间、各系统 Token 状态及权限范围。

**用法**

```bash
opscli auth token status
```

**参数**

无。

**示例**

```bash
opscli auth token status
```

### 4.5 `opscli auth token get`

获取指定系统 JWT。该命令直接输出纯文本 Token，适合脚本场景。

**用法**

```bash
opscli auth token get --system <alias>
opscli auth token get -s <alias>
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--system` / `-s` | 是 | 系统别名，如 `ops`、`polaris` |

**示例**

```bash
opscli auth token get --system ops
opscli auth token get -s polaris
```

脚本示例：

```bash
TOKEN=$(opscli auth token get -s ops)
echo "$TOKEN"
```

### 4.6 `opscli auth token check`

检测指定系统 JWT 是否有效。

**用法**

```bash
opscli auth token check --system <alias>
opscli auth token check -s <alias>
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--system` / `-s` | 是 | 系统别名 |

**示例**

```bash
opscli auth token check --system ops
opscli auth token check -s polaris
```

### 4.7 `opscli auth token refresh`

刷新单个系统 JWT，或刷新全部系统 JWT。

**用法**

```bash
opscli auth token refresh --system <alias>
opscli auth token refresh -s <alias>
opscli auth token refresh --all
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--system` / `-s` | 否 | 刷新单个系统 |
| `--all` | 否 | 刷新全部系统 |

**说明**

- `--system` 与 `--all` 至少要传一个。
- 不传时命令会报错退出。

**示例**

```bash
opscli auth token refresh --system ops
opscli auth token refresh --all
```

### 4.8 `opscli auth system list`

列出所有已注册系统，包括内置系统和手动添加系统。

**用法**

```bash
opscli auth system list
```

**参数**

无。

**示例**

```bash
opscli auth system list
```

### 4.9 `opscli auth system sync`

从 `ops` 服务端同步系统列表。

**用法**

```bash
opscli auth system sync
```

**参数**

无。

**前置条件**

- 需要先执行 `opscli auth login`。

**示例**

```bash
opscli auth system sync
```

### 4.10 `opscli auth system add`

手动添加一个系统实例。

**用法**

```bash
opscli auth system add --alias <alias> --url <url> [--key <system_key>]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--alias` | 是 | 系统展示别名 |
| `--url` | 是 | 系统 URL |
| `--key` | 否 | 存储键；不传时由 `alias` 自动生成 |

**示例**

```bash
opscli auth system add --alias 数据分析 --url http://analytics.cm
opscli auth system add --alias 财务系统 --url http://finance.cm --key finance
```

### 4.11 `opscli auth system remove`

移除手动添加的系统。

**用法**

```bash
opscli auth system remove --alias <alias>
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--alias` | 是 | 要移除的系统别名 |

**示例**

```bash
opscli auth system remove --alias 数据分析
```

## 5. Amazon 模块 `opscli amazon`

用于 Amazon 商品抓取、本地历史保存、标准 payload 构造和搜索结果抓取。

### 5.1 `opscli amazon scrape`

抓取单个商品详情。

**用法**

```bash
opscli amazon scrape --asin <asin> [--zip-code <zip>] [--save-history/--no-save-history] [--include-raw] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--asin` | 是 | - | 目标 ASIN |
| `--zip-code` | 否 | `10001` | 邮编，用于稳定价格口径 |
| `--save-history` / `--no-save-history` | 否 | `--save-history` | 是否保存本地历史 |
| `--include-raw` | 否 | `false` | 是否输出原始抓取字段 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**示例**

```bash
opscli amazon scrape --asin B09LCJPZ1P
opscli amazon scrape --asin B09LCJPZ1P --zip-code 10001 --include-raw --pretty
opscli amazon scrape --asin B09LCJPZ1P --no-save-history
```

### 5.2 `opscli amazon payload`

抓取商品并输出后续提交给 ops 的标准 payload。

**用法**

```bash
opscli amazon payload --asin <asin> [--zip-code <zip>] [--save-history/--no-save-history] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--asin` | 是 | - | 目标 ASIN |
| `--zip-code` | 否 | `10001` | 邮编 |
| `--save-history` / `--no-save-history` | 否 | `--save-history` | 是否保存本地历史 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**示例**

```bash
opscli amazon payload --asin B09LCJPZ1P
opscli amazon payload --asin B09LCJPZ1P --zip-code 10001 --pretty
```

### 5.3 `opscli amazon search`

抓取 Amazon 搜索结果页。

**用法**

```bash
opscli amazon search --keyword "<keyword>" [--zip-code <zip>] [--limit <1-50>] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--keyword` | 是 | - | 搜索关键词 |
| `--zip-code` | 否 | `10001` | 邮编 |
| `--limit` | 否 | `10` | 最大结果数，范围 `1~50` |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**示例**

```bash
opscli amazon search --keyword "usb c cable"
opscli amazon search --keyword "usb c cable" --zip-code 10001 --limit 5 --pretty
```

### 5.4 `opscli amazon schema`

输出当前 Amazon 抓取模型字段结构及 API 预留字段结构。

**用法**

```bash
opscli amazon schema [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli amazon schema
opscli amazon schema --pretty
```

### 5.5 `opscli amazon history`

读取某个 ASIN 的本地历史快照。

**用法**

```bash
opscli amazon history --asin <asin> [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--asin` | 是 | 目标 ASIN |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli amazon history --asin B09LCJPZ1P
opscli amazon history --asin B09LCJPZ1P --pretty
```

## 6. 查询模块 `opscli query`

用于读取数据集元数据、构造查询 payload、执行远端查询。

### 6.1 `opscli query metadata`

读取指定数据集的查询元数据。

**用法**

```bash
opscli query metadata [--dataset <dataset_alias>] [--table-id <table_id>] [--skills-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset` | 否 | 数据集别名 |
| `--table-id` | 否 | 数据集表 ID |
| `--skills-dir` | 否 | 指定 Skill 目录 |
| `--pretty` | 否 | 美化 JSON 输出 |

**说明**

- 一般通过 `--dataset` 或 `--table-id` 指定目标数据集。
- 当需要显式使用某个 Skill 安装目录时，可补充 `--skills-dir`。

**示例**

```bash
opscli query metadata --dataset sales_order_d --pretty
opscli query metadata --table-id 12345
opscli query metadata --dataset sales_order_d --skills-dir ~/.claude/skills --pretty
```

### 6.2 `opscli query catalog`

读取数据集业务语义索引（dataset catalog）。默认远端优先，远端失败时回退本地缓存。

**用法**

```bash
opscli query catalog [--source remote|local] [--no-fallback-local] [--skills-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--source` | 否 | 数据来源：remote（默认）或 local |
| `--fallback-local / --no-fallback-local` | 否 | 远端失败时是否回退本地缓存 |
| `--skills-dir` | 否 | 指定 Skill 目录 |
| `--pretty` | 否 | 美化 JSON 输出 |

**说明**

- 返回完整的 catalog JSON 结构，包含 version、intent_count、intents 数组和 query_strategy。
- 用于自然语言需求匹配 intents 后选出候选数据集。

**示例**

```bash
opscli query catalog --pretty
opscli query catalog --source local --pretty
opscli query catalog --source remote --no-fallback-local --pretty
opscli query catalog --skills-dir ~/.claude/skills --pretty
```

### 6.3 `opscli query run`

执行一个已经准备好的查询 payload 文件，并转发到服务端执行。

**用法**

```bash
opscli query run --payload <payload.json> [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--payload` | 是 | 查询 JSON 文件路径 |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli query run --payload payload.json
opscli query run --payload ./tmp/sales_query.json --pretty
```

### 6.4 `opscli query build`

基于简化参数构造标准 query payload；也可以直接执行。

**用法**

```bash
opscli query build \
  [--dataset <dataset_alias>] \
  [--table-id <table_id>] \
  [--dimension <field[:alias]>] \
  [--metric <field:aggregation[:alias]>] \
  [--where <field|operator|value_json>] \
  [--where-json '<json>'] \
  [--where-file <where.json>] \
  [--having <expr|operator|value_json>] \
  [--order-by <expr[:asc|desc]>] \
  [--limit <n>] \
  [--offset <n>] \
  [--dry-run] \
  [--output <payload.json>] \
  [--data-comparison <field,start_date,end_date>] \
  [--run] \
  [--skills-dir <dir>] \
  [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--dataset` | 否 | - | 数据集别名 |
| `--table-id` | 否 | - | 表 ID |
| `--dimension` | 否 | - | 维度定义，格式 `field_name[:alias]`，可重复 |
| `--metric` | 否 | - | 指标定义，格式 `field_name:aggregation[:alias]`，可重复 |
| `--where` | 否 | - | 条件定义，格式 `field|operator|value_json`，可重复 |
| `--where-json` | 否 | - | 直接传 where JSON 字符串 |
| `--where-file` | 否 | - | 从文件加载 where JSON |
| `--having` | 否 | - | having 条件，格式 `expr|operator|value_json`，可重复 |
| `--order-by` | 否 | - | 排序定义，格式 `expr[:asc\|desc]`，可重复 |
| `--limit` | 否 | `20` | 返回条数 |
| `--offset` | 否 | `0` | 偏移量 |
| `--dry-run` | 否 | `false` | 仅生成 SQL，不执行 |
| `--output` | 否 | - | 将 payload 写入文件 |
| `--data-comparison` | 否 | - | 数据对比参数，格式 `field,start_date,end_date` |
| `--run` | 否 | `false` | 构造后立即执行 |
| `--skills-dir` | 否 | - | 指定 Skill 目录 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**说明**

- `--dataset` 与 `--table-id` 通常二选一。
- `--where`、`--dimension`、`--metric`、`--having`、`--order-by` 可重复传入。
- `--run` 打开后，命令会直接执行查询，而不是只返回 payload。
- `--output` 适合先生成文件，再配合 `opscli query run` 二次执行。

**示例**

基础构造：

```bash
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric gmv:sum \
  --limit 20 \
  --pretty
```

重复传参与写入文件：

```bash
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --dimension shop_id \
  --metric gmv:sum:total_gmv \
  --metric order_cnt:sum \
  --where 'country_code|=|"US"' \
  --where 'date_id|between|["2026-03-01","2026-03-31"]' \
  --order-by total_gmv:desc \
  --limit 100 \
  --output payload.json \
  --pretty
```

直接执行：

```bash
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric gmv:sum \
  --run \
  --pretty
```

使用 `where-json`：

```bash
opscli query build \
  --dataset sales_order_d \
  --metric gmv:sum \
  --where-json '[{"field":"country_code","operator":"=","value":"US"}]' \
  --pretty
```

使用 `where-file`：

```bash
opscli query build \
  --dataset sales_order_d \
  --metric gmv:sum \
  --where-file ./where.json \
  --pretty
```

使用 `data-comparison`：

```bash
opscli query build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric gmv:sum \
  --data-comparison date_id,2026-03-01,2026-03-22 \
  --pretty
```

### 6.5 `opscli query simple`

基于简化参数构造 simple query payload 并可选执行。支持通过 JSON 文件或 JSON 字符串传入完整的简化查询参数。

**用法**

```bash
opscli query simple --table-id <id> [--payload <file>] [--json '<json>'] [--output <file>] [--run] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--table-id` | 是 | - | 数据集 ID |
| `--payload` | 否 | - | 简化查询 JSON 文件路径（与 `--json` 二选一） |
| `--json` | 否 | - | 简化查询 JSON 字符串（与 `--payload` 二选一） |
| `--output` | 否 | - | 将 payload 写入指定文件 |
| `--run` | 否 | `false` | 构造后立即执行查询 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**说明**

- `--payload` 与 `--json` 只能使用一种，用于传入 dimensions、metrics、filters、dataComparison、orderBy 等简化参数。
- 不传 `--run` 时仅输出构造后的 payload，传 `--run` 后立即执行查询并返回结果。

**示例**

通过 JSON 字符串传参：

```bash
opscli query simple --table-id 1 \
  --json '{"dimensions":[{"field":"dept_name","alias":"f_dept"}],"metrics":[{"field":"fi_first_leg_trailer_fee","aggregation":"SUM","alias":"f_fee_sum"}],"filters":[{"field":"date_id","operator":"between","value":["2026-04-01","2026-04-22"]}],"limit":10}' \
  --run --pretty
```

通过文件传参：

```bash
opscli query simple --table-id 1 --payload ./simple_query.json --run --pretty
```

### 6.6 `opscli query chart`

通过 `chart_uuid` 获取图表的查询结构，可选立即执行所有查询并合并输出。

**用法**

```bash
opscli query chart --uuid <chart_uuid> [--run] [--dry-run] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--uuid` | 是 | - | 图表 UUID（chart_uuid） |
| `--run` | 否 | `false` | 获取后立即执行所有查询并合并输出 |
| `--dry-run` | 否 | `false` | 仅生成 SQL，不执行查询（需配合 `--run`） |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**说明**

- 不传 `--run` 时，仅返回图表的查询结构（可能包含多个 query）。
- 传 `--run` 时，依次执行图表下的所有 query，并自动合并结果。
- 每个 query 独立执行，某个 query 失败不会中断其余 query。
- 合并结果中，每行数据会附加 `_query_index` 字段标识来源 query 序号。
- 后端返回的 chart query 已包含 `tableId`，无需本地 metadata 转换。

**示例**

仅查看图表查询结构：

```bash
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty
```

获取并执行所有查询：

```bash
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --pretty
```

仅生成 SQL 不执行：

```bash
opscli query chart --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --dry-run --pretty
```

**返回结构（--run 时）**

```json
{
  "success": true,
  "command": "query chart-run",
  "data": {
    "chart_uuid": "32f660fd-f62a-45c4-a443-e21f2edb0779",
    "queries": [
      {
        "index": 0,
        "table_id": 1,
        "data_source": "doris_analytics",
        "payload": {...},
        "result": {...},
        "error": null
      }
    ],
    "merged": {
      "rows": [{"_query_index": 0, ...}],
      "meta": {"rowCount": 150, "queryCount": 3, "successCount": 3}
    }
  }
}
```

---

### 6.7 `opscli query chart-doc`

通过 `chart_uuid` 生成图表 API 调用 Markdown 文档，包含查询结构、字段映射、过滤规则与样例。

**用法**

```bash
opscli query chart-doc --uuid <chart_uuid> [--output <file>] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--uuid` | 是 | - | 图表 UUID（chart_uuid） |
| `--output` | 否 | - | 将 Markdown 文档写入指定文件路径 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**说明**

- 该命令通过 `chart_uuid` 获取图表的查询结构，自动生成一份完整 Markdown 文档。
- 生成的文档包含七大章节：使用方式、关键术语、图表概览、API 调用流程、字段明细表、过滤规则、查询拆解与样例。
- 使用 `--output` 可将 Markdown 内容直接写入文件，方便保存和分发。

**示例**

生成文档并在终端查看：

```bash
opscli query chart-doc --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty
```

将文档写入文件：

```bash
opscli query chart-doc --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --output chart-doc.md --pretty
```

**返回结构**

```json
{
  "success": true,
  "command": "query chart-doc",
  "data": {
    "chart_uuid": "32f660fd-f62a-45c4-a443-e21f2edb0779",
    "markdown": "# 图表查询 API 开发文档\n...",
    "query_count": 3,
    "dataset_aliases": ["sales_order_d"],
    "dataset_count": 1,
    "output_path": "/path/to/chart-doc.md"
  },
  "error": null
}
```

## 7. Skill 模块 `opscli skills`

用于扫描已安装 Skill、安装内置模板、查看状态、升级远端版本。

### 7.1 内置 Skill 模板

当前仓库内置以下模板：

| Skill 名称 | 说明 |
| --- | --- |
| `ops-amazon` | Amazon 抓取辅助 Skill |
| `ops-amazon-listing-analysis` | Amazon Listing 表达与一致性优化分析 Skill |
| `ops-asin-health-diagnoser` | ASIN 运行状况诊断 Skill |
| `ops-auth` | 认证授权辅助 Skill |
| `ops-dataset-query` | 数据集查询辅助 Skill |
| `ops-mcp` | MCP Server 管理辅助 Skill |
| `ops-product-attribute-analyzer` | 产品属性标签体系分析 Skill |
| `ops-seller-sprite` | 卖家精灵关键词采集辅助 Skill |
| `ops-skills` | Skills 管理辅助 Skill |

### 7.2 `opscli skills list`

列出已安装 Skill。

**用法**

```bash
opscli skills list [--skills-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--skills-dir` | 否 | 指定扫描目录 |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli skills list
opscli skills list --pretty
opscli skills list --skills-dir ~/.claude/skills --pretty
```

### 7.3 `opscli skills install`

从内置模板安装 Skill 到本地目录。

**用法**

```bash
opscli skills install [NAME] [--skills-dir <dir>] [--runtime <runtime>] [--force] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `NAME` | 否 | Skill 名称；不传时进入交互式安装 |
| `--skills-dir` | 否 | 指定安装目录 |
| `--runtime` | 否 | 指定目标运行时，可传单个或逗号分隔多个值 |
| `--force` | 否 | 覆盖已存在目录 |
| `--pretty` | 否 | 美化 JSON 输出 |

**运行时说明**

- `--runtime` 支持 `claude`、`openclaw`、`codex`、`opencode`，以及逗号分隔多值（如 `claude,codex`）。
- 传 `all` 时，会安装到当前检测到的全部可用运行时目录。
- 不传 `NAME` 时，命令进入 TUI 交互模式，可多选 Skill 和安装目标。

**示例**

```bash
opscli skills install ops-dataset-query
opscli skills install ops-dataset-query --skills-dir ~/.claude/skills
opscli skills install ops-dataset-query --skills-dir ~/.claude/skills --force
opscli skills install ops-auth --runtime claude
opscli skills install ops-skills --runtime claude,codex --force
opscli skills install ops-amazon --runtime all --pretty
```

交互式安装：

```bash
opscli skills install
```

### 7.4 `opscli skills status`

查看本地安装状态，并尝试比对远端版本。

**用法**

```bash
opscli skills status [--skills-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--skills-dir` | 否 | 指定扫描目录 |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli skills status
opscli skills status --pretty
opscli skills status --skills-dir ~/.claude/skills --pretty
```

### 7.5 `opscli skills upgrade`

升级已安装 Skill 到远端最新版本。

**用法**

```bash
opscli skills upgrade [NAME] [--skills-dir <dir>] [--force] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `NAME` | 否 | `ops-dataset-query` | Skill 名称 |
| `--skills-dir` | 否 | - | 指定扫描目录 |
| `--force` | 否 | `false` | 强制覆盖本地版本 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**说明**

- 当前升级逻辑只支持 `ops-dataset-query`。
- 如果本地未安装对应 Skill，会直接报错。

**示例**

```bash
opscli skills upgrade
opscli skills upgrade ops-dataset-query
opscli skills upgrade ops-dataset-query --force
opscli skills upgrade ops-dataset-query --skills-dir ~/.claude/skills --pretty
```

## 8. 卖家精灵模块 `opscli seller-sprite`

用于卖家精灵关键词挖掘、高频词采集、关键词反查、页面归档等数据采集操作。

> 前置依赖：`pip install opscli && playwright install chromium`

### 8.1 `opscli seller-sprite collect`

围绕显式关键词执行完整采集（关键词挖掘 + 高频词）。

**用法**

```bash
opscli seller-sprite collect --keyword <keyword> [选项...]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--keyword` | 是 | - | 卖家精灵关键词挖掘入口词 |
| `--asin` | 否 | - | Amazon ASIN，可选，用于关联后续 Listing 分析对象 |
| `--site` | 否 | `us` | 站点 |
| `--period` | 否 | `30d` | 时间窗口，例如 `30d` 或 `2026-03` |
| `--limit` | 否 | `50` | 关键词采集条数（1~200） |
| `--frequency-phrase-count` | 否 | `1` | 高频词词组个数（1~10） |
| `--trend-limit` | 否 | `0` | 采集前 N 个关键词的历史走势弹窗（0 不采集，最大 50） |
| `--trend-tabs` | 否 | `all` | 历史走势子 tab |
| `--archive` / `--no-archive` | 否 | `--archive` | 是否归档截图、HTML、Markdown 和接口响应 |
| `--output-dir` | 否 | - | 输出目录，默认当前目录下 `seller_sprite_runs` |
| `--account` | 否 | - | 命名账号，未登录时自动登录后继续采集 |
| `--pretty` | 否 | `false` | 格式化输出 |

**示例**

```bash
opscli seller-sprite collect --keyword "usb c cable"
opscli seller-sprite collect --keyword "usb c cable" --asin B09LCJPZ1P --limit 100 --pretty
opscli seller-sprite collect --keyword "usb c cable" --trend-limit 10 --account default --pretty
```

### 8.2 `opscli seller-sprite frequency`

采集高频词。

**用法**

```bash
opscli seller-sprite frequency --keyword <keyword> [选项...]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--keyword` | 是 | - | 卖家精灵关键词挖掘入口词 |
| `--site` | 否 | `us` | 站点 |
| `--period` | 否 | `30d` | 时间窗口 |
| `--frequency-phrase-count` | 否 | `1` | 高频词词组个数（1~10） |
| `--archive` / `--no-archive` | 否 | `--archive` | 是否归档页面证据 |
| `--output-dir` | 否 | - | 输出目录 |
| `--pretty` | 否 | `false` | 格式化输出 |

**示例**

```bash
opscli seller-sprite frequency --keyword "usb c cable" --pretty
opscli seller-sprite frequency --keyword "usb c cable" --frequency-phrase-count 3 --pretty
```

### 8.3 `opscli seller-sprite keyword-mining`

采集关键词挖掘结果。

**用法**

```bash
opscli seller-sprite keyword-mining --keyword <keyword> [选项...]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--keyword` | 是 | - | 卖家精灵关键词挖掘入口词 |
| `--site` | 否 | `us` | 站点 |
| `--period` | 否 | `30d` | 时间窗口 |
| `--limit` | 否 | `50` | 关键词采集条数（1~200） |
| `--trend-limit` | 否 | `0` | 采集前 N 个关键词的历史走势弹窗 |
| `--trend-tabs` | 否 | `all` | 历史走势子 tab |
| `--archive` / `--no-archive` | 否 | `--archive` | 是否归档页面证据 |
| `--output-dir` | 否 | - | 输出目录 |
| `--pretty` | 否 | `false` | 格式化输出 |

**示例**

```bash
opscli seller-sprite keyword-mining --keyword "usb c cable" --pretty
opscli seller-sprite keyword-mining --keyword "usb c cable" --limit 100 --trend-limit 5 --pretty
```

### 8.4 `opscli seller-sprite keyword-reverse`

采集关键词反查结果。

**用法**

```bash
opscli seller-sprite keyword-reverse --asin <asin> [选项...]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--asin` | 是 | - | Amazon ASIN 或产品链接中的 ASIN |
| `--site` | 否 | `us` | 站点 |
| `--period` | 否 | `30d` | 时间窗口 |
| `--limit` | 否 | `50` | 关键词采集条数（1~200） |
| `--trend-limit` | 否 | `0` | 采集前 N 个关键词的历史走势弹窗 |
| `--trend-tabs` | 否 | `all` | 历史走势子 tab |
| `--archive` / `--no-archive` | 否 | `--archive` | 是否归档页面证据 |
| `--output-dir` | 否 | - | 输出目录 |
| `--account` | 否 | - | 命名账号，未登录时自动登录后继续采集 |
| `--pretty` | 否 | `false` | 格式化输出 |

**示例**

```bash
opscli seller-sprite keyword-reverse --asin B09LCJPZ1P --pretty
opscli seller-sprite keyword-reverse --asin B09LCJPZ1P --limit 100 --account default --pretty
```

### 8.5 `opscli seller-sprite archive`

归档指定页面（截图 + HTML + Markdown）。

**用法**

```bash
opscli seller-sprite archive --url <url> [--output-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--url` | 是 | 需要归档的卖家精灵页面 URL |
| `--output-dir` | 否 | 输出目录 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli seller-sprite archive --url "https://www.sellersprite.com/..." --pretty
```

### 8.6 `opscli seller-sprite login`

打开浏览器并手动建立卖家精灵登录态。

**用法**

```bash
opscli seller-sprite login [--pretty]
```

**示例**

```bash
opscli seller-sprite login
```

### 8.7 `opscli seller-sprite login-status`

检查当前浏览器 profile 是否已有卖家精灵登录态。

**用法**

```bash
opscli seller-sprite login-status [--output-dir <dir>] [--pretty]
```

**示例**

```bash
opscli seller-sprite login-status --pretty
```

### 8.8 `opscli seller-sprite schema`

输出当前字段契约。

**用法**

```bash
opscli seller-sprite schema [--pretty]
```

**示例**

```bash
opscli seller-sprite schema --pretty
```

### 8.9 `opscli seller-sprite account save`

保存卖家精灵命名账号，密码写入系统凭据管理器（交互式输入密码）。

**用法**

```bash
opscli seller-sprite account save --name <name> --username <username> [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--name` | 是 | 账号别名，例如 `default` |
| `--username` | 是 | 卖家精灵用户名 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli seller-sprite account save --name default --username myuser@example.com
```

### 8.10 `opscli seller-sprite account list`

列出卖家精灵命名账号，不输出密码。

**用法**

```bash
opscli seller-sprite account list [--pretty]
```

**示例**

```bash
opscli seller-sprite account list --pretty
```

### 8.11 `opscli seller-sprite account delete`

删除卖家精灵命名账号。

**用法**

```bash
opscli seller-sprite account delete --name <name> [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--name` | 是 | 账号别名 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli seller-sprite account delete --name default
```

## 9. MCP 管理模块 `opscli mcp`

用于 MCP Server 多用户模式下的用户注册、删除与 API Key 轮换。

### 9.1 `opscli mcp user list`

列出所有 MCP 用户。

**用法**

```bash
opscli mcp user list [--config-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--config-dir` | 否 | 指定 opscli 配置目录 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli mcp user list --pretty
```

### 9.2 `opscli mcp user add`

创建 MCP 用户并输出只展示一次的 API Key。

**用法**

```bash
opscli mcp user add [--desc <description>] [--config-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--desc` | 否 | 用户描述 |
| `--config-dir` | 否 | 指定 opscli 配置目录 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli mcp user add --desc "开发环境" --pretty
```

### 9.3 `opscli mcp user remove`

删除 MCP 用户，默认同步删除隔离凭证目录。

**用法**

```bash
opscli mcp user remove --id <user_id> [--keep-credentials] [--config-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--id` | 是 | MCP 用户 ID |
| `--keep-credentials` | 否 | 保留凭证目录 |
| `--config-dir` | 否 | 指定 opscli 配置目录 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli mcp user remove --id abc123 --pretty
opscli mcp user remove --id abc123 --keep-credentials --pretty
```

### 9.4 `opscli mcp user rotate`

轮换 MCP 用户 API Key，新 Key 只展示一次。

**用法**

```bash
opscli mcp user rotate --id <user_id> [--config-dir <dir>] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--id` | 是 | MCP 用户 ID |
| `--config-dir` | 否 | 指定 opscli 配置目录 |
| `--pretty` | 否 | 格式化输出 |

**示例**

```bash
opscli mcp user rotate --id abc123 --pretty
```

## 10. 常见组合用例

### 10.1 首次完成认证并查询数据

```bash
opscli auth login
opscli skills install ops-dataset-query
opscli query metadata --dataset sales_order_d --pretty
opscli query build --dataset sales_order_d --dimension date_id --metric gmv:sum --output payload.json --pretty
opscli query run --payload payload.json --pretty
```

### 10.2 检查并刷新某个系统的 Token

```bash
opscli auth token status
opscli auth token check -s ops
opscli auth token refresh -s ops
opscli auth token get -s ops
```

### 10.3 抓取 Amazon 商品并查看历史

```bash
opscli amazon scrape --asin B09LCJPZ1P --include-raw --pretty
opscli amazon payload --asin B09LCJPZ1P --pretty
opscli amazon history --asin B09LCJPZ1P --pretty
```

### 10.4 检查 Skill 是否有更新

```bash
opscli skills list --pretty
opscli skills status --pretty
opscli skills upgrade ops-dataset-query --pretty
```

### 10.5 卖家精灵完整采集流程

```bash
# 1. 保存账号（仅首次）
opscli seller-sprite account save --name default --username myuser@example.com

# 2. 登录（仅首次或 session 失效时）
opscli seller-sprite login

# 3. 完整采集（关键词挖掘 + 高频词）
opscli seller-sprite collect --keyword "usb c cable" --limit 100 --account default --pretty

# 4. 单独关键词反查
opscli seller-sprite keyword-reverse --asin B09LCJPZ1P --account default --pretty
```

### 10.6 MCP 用户管理

```bash
# 1. 添加用户
opscli mcp user add --desc "Claude Code 开发环境" --pretty

# 2. 列出所有用户
opscli mcp user list --pretty

# 3. 轮换 API Key
opscli mcp user rotate --id abc123 --pretty

# 4. 删除用户
opscli mcp user remove --id abc123 --pretty
```

## 11. 快速索引

| 模块 | 命令 |
| --- | --- |
| 顶级 | `opscli --version`、`opscli --help` |
| 认证 | `opscli auth login`、`logout`、`doctor` |
| Token | `opscli auth token status`、`get`、`check`、`refresh` |
| 系统管理 | `opscli auth system list`、`sync`、`add`、`remove` |
| Amazon | `opscli amazon scrape`、`payload`、`search`、`schema`、`history` |
| 查询 | `opscli query metadata`、`catalog`、`run`、`build`、`simple`、`chart`、`chart-doc` |
| Skills | `opscli skills list`、`install`、`status`、`upgrade` |
| 卖家精灵 | `opscli seller-sprite collect`、`frequency`、`keyword-mining`、`keyword-reverse`、`archive`、`login`、`login-status`、`schema` |
| 卖家精灵账号 | `opscli seller-sprite account save`、`list`、`delete` |
| MCP 管理 | `opscli mcp user list`、`add`、`remove`、`rotate` |
