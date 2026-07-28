# opscli 命令用例手册

本文档基于当前仓库代码整理，覆盖 `opscli` 顶级命令、全部子命令、参数说明与常见使用示例。

- 代码基线：`aukeys-opscli` `0.0.37`
- 命令入口：`opscli`
- 主要来源：
  - `opscli/cli.py`
  - `opscli/auth/cli.py`
  - `opscli/amazon/commands/cli.py`
  - `opscli/asin_data/cli.py`
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
├── asin-data
│   └── collect
├── feedback
│   ├── schema
│   ├── submit
│   └── detail
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
│   ├── upgrade
│   ├── edit
│   ├── publish
│   ├── unpublish
│   ├── sync-exclude
│   │   ├── add
│   │   ├── remove
│   │   └── list
│   └── marketplace
│       ├── categories
│       ├── list
│       ├── search
│       ├── info
│       ├── versions
│       └── rate
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
| `asin-data` | 标准 JSON；`--url-only` 时输出纯 URL |
| `query` | 标准 JSON |
| `skills` | 标准 JSON；交互安装时会先显示 TUI 选择界面 |
| `seller-sprite` | 标准 JSON |
| `feedback` | 标准 JSON |
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
| `ops-dashboard-ai-bridge` | 仪表盘页面编辑与写后核验 Skill，仅在仪表盘页面上下文中运行 |
| `ops-dashboard-data-analysis` | 仪表盘业务数据只读分析 Skill，依赖 `ops-dataset-query` |
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

安装仪表盘分析与编辑 Skill 时，先安装数据查询依赖：

```bash
opscli skills install ops-dataset-query
opscli skills install ops-dashboard-data-analysis
opscli skills install ops-dashboard-ai-bridge
```

两项仪表盘 Skill 只在运营系统仪表盘编辑页注入 `dashboard_*` 工具后具备执行能力；普通终端会话只能安装和读取 Skill 规范。

### 7.3 `opscli skills install`

安装 Skill — 支持内置模板和远程技能广场两种来源；也可通过 `--sync-market` 将市场安装记录同步到本地。

**用法**

```bash
opscli skills install [NAME|IDENTIFIER] [--skills-dir <dir>] [--runtime <runtime>]
                      [--force] [--sync-market] [--dry-run] [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `NAME` / `IDENTIFIER` | 否 | Skill 名称（内置模板）或 `username@skill_name`（广场远程安装）；不传时进入交互式安装 |
| `--skills-dir` | 否 | 指定安装目录 |
| `--runtime` | 否 | 指定目标运行时，可传单个或逗号分隔多个值 |
| `--force` | 否 | 覆盖已存在目录 |
| `--sync-market` | 否 | 从技能市场同步安装记录：补装本地缺失的技能，升级版本落后的技能；不可与 `NAME` 同时使用 |
| `--dry-run` | 否 | 预览同步计划，不实际执行安装/升级（需配合 `--sync-market`） |
| `--pretty` | 否 | 美化 JSON 输出 |

**运行时说明**

- `--runtime` 支持 `claude`、`openclaw`、`codex`、`opencode`，以及逗号分隔多值（如 `claude,codex`）。
- 传 `all` 时，会安装到当前检测到的全部可用运行时目录。
- 不传 `NAME` 时，命令进入 TUI 交互模式，可多选 Skill 和安装目标。

**远程安装说明**（`username@skill_name` 格式）

1. 从广场获取技能元数据与下载地址
2. 下载 zip 包并解压到 `~/.opscli/skills/<skill_name>/`
3. 自动软链接到 `~/.claude/skills/`、`~/.openclaw/skills/` 等全局 AI 工具目录
4. 回调广场记录安装次数

**市场同步说明**（`--sync-market`）

1. 从服务端拉取当前用户的市场安装记录队列（排除同步黑名单中的技能）
2. 逐项与本地已安装版本对比：
   - 本地未安装 → 自动补装
   - 本地版本落后 → 强制升级到市场最新版
   - 本地版本相同或更新 → 跳过
3. 配合 `--dry-run` 可仅打印同步计划，不执行任何写操作

**示例**

```bash
# 安装内置模板
opscli skills install ops-dataset-query
opscli skills install ops-dataset-query --skills-dir ~/.claude/skills
opscli skills install ops-dataset-query --skills-dir ~/.claude/skills --force
opscli skills install ops-auth --runtime claude
opscli skills install ops-skills --runtime claude,codex --force
opscli skills install ops-amazon --runtime all --pretty

# 从技能广场远程安装
opscli skills install pengjianchao@ops-auth
opscli skills install pengjianchao@ops-auth --force
opscli skills install pengjianchao@ops-auth --runtime claude

# 市场同步（补装 + 升级）
opscli skills install --sync-market --pretty

# 预览市场同步计划，不实际执行
opscli skills install --sync-market --dry-run --pretty
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

### 7.6 `opscli skills publish`

将本地 Skill 目录打包（zip）发布到技能广场。首次发布自动创建技能，再次发布时追加新版本。

技能目录须包含 `SKILL.md` 和 `data/VERSION.json`。

**用法**

```bash
opscli skills publish [--dir <dir>] [--title <title>] [--summary <summary>]
                      [--desc <desc>] [--tags <tags>] [--category <id>]
                      [--share-type <type>] [--changelog <text>] [--json]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--dir` / `-d` | 否 | `.`（当前目录） | Skill 目录 |
| `--title` | 否 | SKILL.md 中的 title | 技能标题 |
| `--summary` | 否 | SKILL.md 中的 summary | 技能一句话摘要（显示在列表卡片中） |
| `--desc` | 否 | SKILL.md 中的 description | 技能详细简介 |
| `--tags` | 否 | SKILL.md 中的 tags | 标签，逗号分隔 |
| `--category` | 否 | SKILL.md 中的 category_id；未指定时自动匹配 | 分类 ID |
| `--share-type` | 否 | `personal` | 分享范围：`personal`（仅自己）/ `department`（部门）/ `company`（全公司） |
| `--changelog` | 否 | - | 本次版本变更说明 |
| `--json` | 否 | `false` | 输出原始 JSON |

> **自动分类匹配**：若未通过 `--category` 或 `SKILL.md frontmatter` 的 `category_id` 指定分类，发布时会自动从广场获取所有分类，根据技能名称、标题、标签和描述进行关键词得分匹配，选出最合适的分类后自动填充。终端会显示 `已自动匹配分类：<name>`。若无匹配则不传分类参数。

**share-type 说明**

| 值 | 说明 |
| --- | --- |
| `personal` | 仅自己可见（默认），适合私有工作流 |
| `department` | 部门内可见，适合团队共享 |
| `company` | 全公司可见，适合推广到广场 |

**示例**

```bash
# 发布当前目录下的 Skill（个人可见）
opscli skills publish

# 指定目录，并附带变更说明
opscli skills publish --dir ./my-skill --changelog "修复了某个 bug"

# 附带完整元数据并指定分享范围
opscli skills publish --title "我的技能" --summary "一句话描述" --desc "技能详细描述" \
                      --tags "ai,ops" --share-type company --changelog "初始版本"

# 发布为部门共享
opscli skills publish --share-type department --changelog "v2.0 新功能"

# JSON 模式输出（适合脚本）
opscli skills publish --json
```

---

### 7.7 `opscli skills unpublish`

下架已发布的技能（软删除，不影响已安装到本地的用户）。

**用法**

```bash
opscli skills unpublish <IDENTIFIER> [--force] [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--force` / `-f` | 否 | 跳过交互确认提示 |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
opscli skills unpublish pengjianchao@ops-auth
opscli skills unpublish pengjianchao@ops-auth --force
opscli skills unpublish pengjianchao@ops-auth --json
```

---

### 7.8 `opscli skills edit`

在线编辑已发布到广场的技能元数据（标题、摘要、简介、分享范围等），无需重新打包发布。

**用法**

```bash
opscli skills edit <IDENTIFIER> [--title <title>] [--summary <summary>]
                   [--desc <desc>] [--tags <tags>] [--category <id>]
                   [--share-type <type>] [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--title` | 否 | 新的技能标题 |
| `--summary` | 否 | 新的一句话摘要 |
| `--desc` | 否 | 新的详细简介 |
| `--tags` | 否 | 新的标签，逗号分隔 |
| `--category` | 否 | 新的分类 ID；未指定时自动匹配 |
| `--share-type` | 否 | 新的分享范围：`personal` / `department` / `company` |
| `--json` | 否 | 输出原始 JSON |

**说明**

- 只能编辑自己发布的技能，不可编辑他人技能。
- 只传需要修改的字段，未传字段保持原值不变。
- 不影响版本历史和已安装用户。
- `--category` 未传时会自动调用分类列表接口，根据技能名称/标题/标签做关键词匹配并自动填充最合适的分类。

**示例**

```bash
# 修改技能标题和摘要
opscli skills edit pengjianchao@ops-auth --title "认证授权管理 v2" --summary "支持多系统 JWT 管理"

# 扩大分享范围
opscli skills edit pengjianchao@ops-auth --share-type company

# 更新标签
opscli skills edit pengjianchao@ops-auth --tags "auth,jwt,ops"

# JSON 模式输出
opscli skills edit pengjianchao@ops-auth --share-type department --json
```

---

### 7.9 `opscli skills sync-exclude`

管理技能市场同步黑名单。加入黑名单的技能在执行 `opscli skills install --sync-market` 时将被跳过。

#### `opscli skills sync-exclude add`

将指定技能加入不同步排除名单。

**用法**

```bash
opscli skills sync-exclude add <IDENTIFIER> [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
opscli skills sync-exclude add pengjianchao@ops-auth
opscli skills sync-exclude add pengjianchao@ops-auth --json
```

#### `opscli skills sync-exclude remove`

将指定技能移出不同步排除名单。

**用法**

```bash
opscli skills sync-exclude remove <IDENTIFIER> [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
opscli skills sync-exclude remove pengjianchao@ops-auth
opscli skills sync-exclude remove pengjianchao@ops-auth --json
```

#### `opscli skills sync-exclude list`

查看当前不同步排除名单。

**用法**

```bash
opscli skills sync-exclude list [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
opscli skills sync-exclude list
opscli skills sync-exclude list --json
```

**输出示例（表格模式）**

```
╭────────────────────────────────────────────────────────────╮
│                      同步排除名单                          │
│  标识符                         标题         简介    加入时间 │
│  pengjianchao@ops-auth          认证授权管理  …      2026-05 │
╰────────────────────────────────────────────────────────────╯
共 1 个技能被排除在自动同步之外
```

---

## 7.10 技能广场子命令 `opscli skills marketplace`

浏览和搜索广场上的公开技能。

### `opscli skills marketplace categories`

查看所有技能分类，返回每个分类的 **ID、slug 和中文名称**。

> 发布或编辑技能时，若未传 `--category`，opscli 会自动调用此接口并进行关键词匹配，自动填充最合适的分类。

**用法**

```bash
opscli skills marketplace categories [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
# 查看所有分类（富文本表格）
opscli skills marketplace categories

# JSON 模式（脚本场景）
opscli skills marketplace categories --json
```

**典型输出（表格模式）：**

```
┌─ Skill 技能分类 ──────────────────────────┐
│ ID   Slug              分类名称            │
│ 1    auth              认证授权            │
│ 2    data-query        数据查询            │
│ 3    ops-tools         运营工具            │
└──────────────────── 共 3 个分类 ──────────┘
共 3 个分类，使用 --category <slug> 筛选技能列表，发布时自动匹配最合适的分类
```

---

### `opscli skills marketplace list`

浏览广场技能列表，支持按范围（个人 / 广场）、分类、排序等多维过滤。

**用法**

```bash
opscli skills marketplace list [--scope <personal|all>] [--sub <mine|shared_with_me>]
                                [--category <id>] [--sort <field>] [--order <asc|desc>]
                                [--page <n>] [--limit <n>] [--official] [--json]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--scope` | 否 | - | 查询范围：`personal`（个人相关）/ `all`（技能广场，仅 department + company 共享技能） |
| `--sub` | 否 | - | `--scope personal` 的子筛选：`mine`（我创建的）/ `shared_with_me`（分享给我的）；不传则同时返回两类 |
| `--category` | 否 | - | 按分类 ID 筛选 |
| `--sort` | 否 | `downloads` | 排序字段：`downloads` / `rating` / `created_at` |
| `--order` | 否 | `desc` | 排序方向：`asc` / `desc` |
| `--page` | 否 | `1` | 页码 |
| `--limit` | 否 | `20` | 每页条数，最大 50 |
| `--official` | 否 | - | 只显示官方技能 |
| `--json` | 否 | `false` | 输出原始 JSON |

**scope 与 sub 说明**

| `--scope` | `--sub` | 返回内容 |
| --- | --- | --- |
| *(不传)* | *(不传)* | 当前用户可见的全部技能（默认行为，含 visibleTo 过滤） |
| `personal` | *(不传)* | 我创建的 + 分享给我的（安装过但非本人创建） |
| `personal` | `mine` | 仅我创建的技能 |
| `personal` | `shared_with_me` | 仅分享给我的技能（他人创建，我有安装记录） |
| `all` | *(不传)* | 全广场公开技能（`share_type` 为 department 或 company） |

**示例**

```bash
# 默认列表（全部可见技能）
opscli skills marketplace list

# 查看我的个人技能（我创建的 + 分享给我的）
opscli skills marketplace list --scope personal

# 只看我自己创建的技能
opscli skills marketplace list --scope personal --sub mine

# 只看分享给我的技能（他人发布、我已安装）
opscli skills marketplace list --scope personal --sub shared_with_me

# 浏览全公司广场技能，按下载量降序
opscli skills marketplace list --scope all --sort downloads --order desc --limit 10

# 按分类 + 只看官方
opscli skills marketplace list --category 1 --official

# JSON 输出
opscli skills marketplace list --scope personal --json
```

---

### `opscli skills marketplace search`

按关键词搜索技能广场。

**用法**

```bash
opscli skills marketplace search <KEYWORD> [--sort <field>] [--page <n>] [--limit <n>] [--json]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `KEYWORD` | 是 | - | 搜索关键词 |
| `--sort` | 否 | `downloads` | 排序字段 |
| `--page` | 否 | `1` | 页码 |
| `--limit` | 否 | `20` | 每页条数 |
| `--json` | 否 | `false` | 输出原始 JSON |

**示例**

```bash
opscli skills marketplace search ops-auth
opscli skills marketplace search "数据查询" --limit 5 --json
```

---

### `opscli skills marketplace info`

查看指定技能的详细信息。

**用法**

```bash
opscli skills marketplace info <IDENTIFIER> [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
opscli skills marketplace info pengjianchao@ops-auth
opscli skills marketplace info pengjianchao@ops-auth --json
```

---

### `opscli skills marketplace versions`

查看指定技能的历史版本列表。

**用法**

```bash
opscli skills marketplace versions <IDENTIFIER> [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--json` | 否 | 输出原始 JSON |

**示例**

```bash
opscli skills marketplace versions pengjianchao@ops-auth
opscli skills marketplace versions pengjianchao@ops-auth --json
```

---

### `opscli skills marketplace rate`

对已安装的广场技能进行评分（1–5 星）并留下评价文字。

**用法**

```bash
opscli skills marketplace rate <IDENTIFIER> --score <1-5> [--comment <text>] [--json]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `IDENTIFIER` | 是 | 技能标识符，格式 `username@skill_name` |
| `--score` | 是 | 评分，整数 1–5 |
| `--comment` | 否 | 评价文字（可选） |
| `--json` | 否 | 输出原始 JSON |

**说明**

- 只能对已安装过的技能评分，不能评分自己发布的技能。
- 同一技能可重复评分，最新评分会覆盖之前的记录。

**示例**

```bash
# 5 星好评
opscli skills marketplace rate pengjianchao@ops-auth --score 5

# 带评价文字
opscli skills marketplace rate pengjianchao@ops-auth --score 4 --comment "功能完善，文档清晰"

# JSON 模式
opscli skills marketplace rate pengjianchao@ops-auth --score 5 --json
```

---

## 8. ASIN 批量取数模块 `opscli asin-data`

用于按单个 ASIN 或 ASIN 表格批量采集卖家精灵、Amazon 抓取、BI 销售、爬虫 Listing 和 Rufus 数据，并输出前端可直接消费的数据包。

详细使用说明见 `docs/guide/ASIN批量取数服务使用说明.md`。

### 8.1 `opscli asin-data collect`

执行 ASIN 批量取数，并写出标准前端数据文件。

**用法**

```bash
opscli asin-data collect (--input <file> | --asin <ASIN>) [选项...]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--input` / `-i` | 与 `--asin` 二选一 | - | CSV/XLSX/JSON/JSONL 输入文件 |
| `--asin` | 与 `--input` 二选一 | - | 单个 ASIN |
| `--keyword` | 否 | - | 单个 ASIN 的关键词，可重复传入 |
| `--asin-column` | 否 | `asin` | 输入文件中的 ASIN 列名 |
| `--keyword-column` | 否 | `keyword` | 输入文件中的关键词列名 |
| `--site-column` | 否 | `site` | 输入文件中的站点列名 |
| `--site` | 否 | `US` | 默认站点 |
| `--output-dir` | 否 | `output/asin-data` | 输出根目录 |
| `--run-id` | 否 | 自动生成 | 本次运行 ID |
| `--dry-run` | 否 | `false` | 只生成计划和输出骨架，不执行远端取数 |
| `--skip-seller-sprite` | 否 | `false` | 跳过卖家精灵数据 |
| `--skip-keyword-miner` | 否 | `false` | 跳过关键词挖掘 |
| `--skip-listing-analysis` | 否 | `false` | 跳过卖家精灵 AI 全景分析 |
| `--skip-amazon` | 否 | `false` | 跳过 Amazon 页面抓取 |
| `--skip-query` | 否 | `false` | 跳过全部 BI/query 数据 |
| `--skip-sales-query` | 否 | `false` | 跳过 BI 销售数据 |
| `--skip-crawler-query` | 否 | `false` | 跳过爬虫 Listing 数据 |
| `--skip-rufus` | 否 | `false` | 跳过 Rufus 优化建议 |
| `--seller-sprite-period` | 否 | `30d` | 卖家精灵周期 |
| `--keyword-source` | 否 | `reverse_top` | 关键词来源策略：`input_only` / `reverse_top` / `skip` |
| `--max-miner-keywords` | 否 | `1` | 每个 ASIN 最多挖掘的关键词数 |
| `--rufus-question` | 否 | 默认题库 | Rufus 问题，可重复传入，支持 `{{asin}}` |
| `--sales-start` | 否 | - | BI 销售开始日期 |
| `--sales-end` | 否 | - | BI 销售结束日期 |
| `--sales-table-id` | 否 | - | BI 销售数据 table_id |
| `--sales-dataset-alias` | 否 | `ds_d35ac6f3910c` | BI 销售数据集 alias |
| `--sales-field-mode` | 否 | `full` | 销售字段模式：`full` / `compatible` |
| `--crawler-table-id` | 否 | - | 爬虫 Listing table_id；`custom_crawler_amazon_details` 已验证为 `43` |
| `--crawler-dataset-alias` | 否 | `ds_icw50TLOFu4F` | 爬虫 Listing 数据集 alias |
| `--crawler-field-mode` | 否 | `full` | 爬虫字段模式：`full` / `compatible` |
| `--query-chunk-size` | 否 | `100` | BI/爬虫每批 ASIN 数 |
| `--upload/--no-upload` | 否 | `--upload` | 是否上传 `frontend-data.json` 并返回 URL |
| `--url-only` | 否 | `false` | 只输出上传后的 URL |
| `--pretty` | 否 | `false` | 格式化 JSON 输出 |

**示例**

```bash
# 先 dry-run 检查计划
opscli asin-data collect --input ./asins.csv --sales-start 2026-05-01 --sales-end 2026-05-31 --dry-run --pretty

# 批量正式执行
opscli asin-data collect --input ./asins.csv --sales-start 2026-05-01 --sales-end 2026-05-31 --pretty

# 单个 ASIN
opscli asin-data collect --asin B0BY8Y5766 --site US --keyword "bed frame" --pretty

# 只查 BI 和爬虫数据
opscli asin-data collect --input ./asins.csv --skip-seller-sprite --skip-amazon --skip-rufus --pretty

# 只输出上传 URL
opscli asin-data collect --asin B0BY8Y5766 --site US --keyword "bed frame" --url-only
```

**输出**

默认写入：

```text
output/asin-data/<run_id>/
```

主要文件：

- `frontend-data.json`：前端优先读取的数据包
- `frontend-data.md`：人工可读交接文件
- `frontend-data.html`：本地 HTML 预览文件，不上传
- `asin-data.jsonl`：每个 ASIN 一行的完整记录
- `manifest.json`：运行参数和文件索引
- `commands.jsonl`：数据源执行日志
- `errors.jsonl`：失败来源和错误信息

---

## 9. 卖家精灵模块 `opscli seller-sprite`

用于卖家精灵关键词挖掘、高频词采集、关键词反查、页面归档等数据采集操作。

> 前置依赖：`pip install opscli && playwright install chromium`

### 9.1 `opscli seller-sprite collect`

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

### 9.2 `opscli seller-sprite frequency`

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

### 9.3 `opscli seller-sprite keyword-mining`

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

### 9.4 `opscli seller-sprite keyword-reverse`

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

### 9.5 `opscli seller-sprite archive`

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

### 9.6 `opscli seller-sprite login`

打开浏览器并手动建立卖家精灵登录态。

**用法**

```bash
opscli seller-sprite login [--pretty]
```

**示例**

```bash
opscli seller-sprite login
```

### 9.7 `opscli seller-sprite login-status`

检查当前浏览器 profile 是否已有卖家精灵登录态。

**用法**

```bash
opscli seller-sprite login-status [--output-dir <dir>] [--pretty]
```

**示例**

```bash
opscli seller-sprite login-status --pretty
```

### 9.8 `opscli seller-sprite schema`

输出当前字段契约。

**用法**

```bash
opscli seller-sprite schema [--pretty]
```

**示例**

```bash
opscli seller-sprite schema --pretty
```

### 9.9 `opscli seller-sprite account save`

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

### 9.10 `opscli seller-sprite account list`

列出卖家精灵命名账号，不输出密码。

**用法**

```bash
opscli seller-sprite account list [--pretty]
```

**示例**

```bash
opscli seller-sprite account list --pretty
```

### 9.11 `opscli seller-sprite account delete`

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

## 10. MCP 管理模块 `opscli mcp`

用于 MCP Server 多用户模式下的用户注册、删除与 API Key 轮换。

### 10.1 `opscli mcp user list`

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

### 10.2 `opscli mcp user add`

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

### 10.3 `opscli mcp user remove`

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

### 10.4 `opscli mcp user rotate`

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

## 11. 反馈模块 `opscli feedback`

用于提交结构化用户反馈和查询反馈详情。反馈数据保存到 `polaris_ops_metrics.dm_user_feedbacks`。

> 前置条件：需先执行 `opscli auth login` 完成认证。

### 自动触发规则

当 AI Agent（Codex）调用 CLI 命令失败时，根据 AGENTS.md 铁律，**必须**立即自动提交反馈：

1. CLI 命令返回非 0 退出码或错误 JSON
2. 从错误输出提取 `code` 和 `message`
3. 调用 `opscli feedback submit` 提交，execution_summary 中记录失败的命令和参数
4. 将 `feedback_uuid` 返回给用户，然后继续处理原任务

### 11.1 `opscli feedback schema`

输出反馈 payload 的 schema 定义。

**用法**

```bash
opscli feedback schema [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli feedback schema --pretty
```

### 11.2 `opscli feedback submit`

提交用户反馈。

**用法**

```bash
opscli feedback submit --file <file> [--pretty]
opscli feedback submit --type <type> --title <title> --content <content> [选项...] [--pretty]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--file` | 否 | - | 完整反馈 JSON 文件路径（与字段参数互斥） |
| `--type` / `--feedback-type` | 条件 | - | 反馈类型：`bug`/`feature`/`data_issue`/`ux`/`docs`/`other` |
| `--title` | 条件 | - | 反馈标题，最多 200 字符 |
| `--content` | 条件 | - | 反馈正文 |
| `--severity` | 否 | `medium` | 严重度：`low`/`medium`/`high`/`critical` |
| `--source` | 否 | `cli` | 来源：`cli`/`mcp`/`skill`/`api` |
| `--payload` | 否 | - | 原始结构化反馈 JSON 字符串 |
| `--payload-file` | 否 | - | 原始结构化反馈 JSON 文件 |
| `--context` | 否 | - | 执行上下文 JSON 字符串 |
| `--context-file` | 否 | - | 执行上下文 JSON 文件 |
| `--execution-summary` | 否 | - | 执行总结 JSON 字符串 |
| `--execution-summary-file` | 否 | - | 执行总结 JSON 文件 |
| `--attachments` | 否 | - | 附件引用 JSON 数组字符串 |
| `--attachments-file` | 否 | - | 附件引用 JSON 数组文件 |
| `--skill-name` | 否 | - | Skill 名称 |
| `--skill-version` | 否 | - | Skill 版本 |
| `--command-name` | 否 | - | CLI 命令名称 |
| `--mcp-tool-name` | 否 | - | MCP Tool 名称 |
| `--client-name` | 否 | `opscli` | 客户端名称 |
| `--system` | 否 | `ops` | 系统别名 |
| `--pretty` | 否 | `false` | 美化 JSON 输出 |

**说明**

- `--file` 与字段参数（`--type`、`--title`、`--content` 等）只能使用一种。
- 传 `--file` 时，文件内容必须是完整的 JSON 对象，包含所有必要字段。
- `execution_summary` 中的 `failed_calls` 若存在，每项必须包含 `tool` 和 `error_message`。

**示例**

通过文件提交：

```bash
opscli feedback submit --file feedback.json --pretty
```

通过字段提交：

```bash
opscli feedback submit \
  --type bug \
  --severity medium \
  --title "query simple 返回字段缺失" \
  --content "执行后字段为空" \
  --execution-summary-file summary.json \
  --pretty
```

### 11.3 `opscli feedback detail`

按 `feedback_uuid` 查询当前用户反馈详情。

**用法**

```bash
opscli feedback detail --uuid <feedback_uuid> [--pretty]
```

**参数**

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--uuid` / `--feedback-uuid` | 是 | 反馈 UUID |
| `--pretty` | 否 | 美化 JSON 输出 |

**示例**

```bash
opscli feedback detail --uuid xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx --pretty
```

## 12. 常见组合用例

### 12.1 首次完成认证并查询数据

```bash
opscli auth login
opscli skills install ops-dataset-query
opscli query metadata --dataset sales_order_d --pretty
opscli query build --dataset sales_order_d --dimension date_id --metric gmv:sum --output payload.json --pretty
opscli query run --payload payload.json --pretty
```

### 12.2 检查并刷新某个系统的 Token

```bash
opscli auth token status
opscli auth token check -s ops
opscli auth token refresh -s ops
opscli auth token get -s ops
```

### 12.3 抓取 Amazon 商品并查看历史

```bash
opscli amazon scrape --asin B09LCJPZ1P --include-raw --pretty
opscli amazon payload --asin B09LCJPZ1P --pretty
opscli amazon history --asin B09LCJPZ1P --pretty
```

### 12.4 检查 Skill 是否有更新

```bash
opscli skills list --pretty
opscli skills status --pretty
opscli skills upgrade ops-dataset-query --pretty
```

### 12.5 卖家精灵完整采集流程

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

### 12.6 MCP 用户管理

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

### 12.7 技能广场完整使用流程

```bash
# 1. 浏览广场全量公开技能
opscli skills marketplace list --scope all

# 2. 查看我的个人技能（我创建的 + 分享给我的）
opscli skills marketplace list --scope personal

# 3. 搜索特定技能
opscli skills marketplace search ops-auth

# 4. 查看详情与版本历史
opscli skills marketplace info pengjianchao@ops-auth
opscli skills marketplace versions pengjianchao@ops-auth

# 5. 远程安装
opscli skills install pengjianchao@ops-auth

# 6. 强制覆盖安装（升级）
opscli skills install pengjianchao@ops-auth --force

# 7. 评分
opscli skills marketplace rate pengjianchao@ops-auth --score 5 --comment "非常好用"

# 8. 查看所有可用分类（发布前可先了解）
opscli skills marketplace categories

# 9. 发布自己的技能（先登录）
#    未传 --category 时会自动从分类列表匹配最合适的分类
cd my-skill/
opscli skills publish --summary "一句话描述" --share-type company --changelog "初始版本"

# 10. 发布新版本
# 修改 data/VERSION.json 中的 version 字段后
opscli skills publish --changelog "修复了 xxx 问题"

# 11. 编辑元数据（无需重新发布版本）
#     未传 --category 时同样会自动匹配最合适的分类
opscli skills edit pengjianchao@my-skill --share-type department

# 12. 下架技能
opscli skills unpublish pengjianchao@my-skill --force
```

### 12.8 市场同步工作流（多设备 / 换机场景）

当你在新设备上登录，或希望将市场安装记录自动同步到本地时：

```bash
# 1. 先完成认证登录
opscli auth login

# 2. 预览同步计划（不实际安装）
opscli skills install --sync-market --dry-run --pretty

# 3. 确认无误后执行实际同步
opscli skills install --sync-market --pretty

# 4. 验证本地安装结果
opscli skills list --pretty
```

**典型同步输出**

```
[补装] pengjianchao@ops-amazon        → v1.2.0  ✓
[升级] pengjianchao@ops-dataset-query   1.0.0 → 1.3.0  ✓
[跳过] pengjianchao@ops-auth            1.1.0（本地版本 ≥ 市场版本）
同步完成：2 项变更，1 项跳过
```

### 12.9 同步黑名单管理

当某些技能不希望被 `--sync-market` 自动安装/升级时，加入排除名单：

```bash
# 1. 查看当前黑名单
opscli skills sync-exclude list

# 2. 将技能加入黑名单
opscli skills sync-exclude add pengjianchao@ops-auth

# 3. 再次同步时该技能会被跳过
opscli skills install --sync-market --dry-run --pretty
# 输出示例：[跳过（黑名单）] pengjianchao@ops-auth

# 4. 将技能移出黑名单，重新纳入同步
opscli skills sync-exclude remove pengjianchao@ops-auth

# 5. 再次同步即可补装
opscli skills install --sync-market --pretty
```

### 12.10 提交工具调用失败的结构化反馈

```bash
# 1. 查看 schema
opscli feedback schema --pretty

# 2. 构造 feedback.json
cat > feedback.json << 'EOF'
{
  "source": "cli",
  "feedback_type": "bug",
  "severity": "medium",
  "title": "ops-dataset-query simple 字段不存在",
  "content": "使用 simple 查询时字段 original_price 无法识别，已改用 build 完成。",
  "execution_summary": {
    "summary": "本次通过 ops-dataset-query 查询数据，simple 接口因字段识别失败，最终改用 build。",
    "failed_calls": [
      {
        "tool": "Bash → opscli query simple --table-id 1 --json '...' --run --pretty",
        "call_params": {"table_id": 1, "metrics": [{"field": "original_price", "aggregation": "SUM"}]},
        "error_message": "REMOTE_BUSINESS_ERROR: 字段不存在: original_price",
        "reason": "简化接口的 field 参数传了 field_name，但服务端未能识别。",
        "fix_suggestion": "改用 opscli query build 的 --dimension/--metric 参数形式。"
      }
    ],
    "final_resolution": "已通过 build 查询完成任务。"
  }
}
EOF

# 3. 提交反馈
opscli feedback submit --file feedback.json --pretty

# 4. 查询反馈详情
opscli feedback detail --uuid <feedback_uuid> --pretty
```

## 13. 快速索引

| 模块 | 命令 |
| --- | --- |
| 顶级 | `opscli --version`、`opscli --help` |
| 认证 | `opscli auth login`、`logout`、`doctor` |
| Token | `opscli auth token status`、`get`、`check`、`refresh` |
| 系统管理 | `opscli auth system list`、`sync`、`add`、`remove` |
| Amazon | `opscli amazon scrape`、`payload`、`search`、`schema`、`history` |
| ASIN 批量取数 | `opscli asin-data collect` |
| 查询 | `opscli query metadata`、`catalog`、`run`、`build`、`simple`、`chart`、`chart-doc` |
| 反馈 | `opscli feedback schema`、`submit`、`detail` |
| Skills | `opscli skills list`、`install [--sync-market] [--dry-run]`、`status`、`upgrade`、`edit`、`publish`、`unpublish` |
| 同步黑名单 | `opscli skills sync-exclude add`、`remove`、`list` |
| 技能广场 | `opscli skills marketplace categories`、`list [--scope] [--sub]`、`search`、`info`、`versions`、`rate` |
| 卖家精灵 | `opscli seller-sprite collect`、`frequency`、`keyword-mining`、`keyword-reverse`、`archive`、`login`、`login-status`、`schema` |
| 卖家精灵账号 | `opscli seller-sprite account save`、`list`、`delete` |
| MCP 管理 | `opscli mcp user list`、`add`、`remove`、`rotate` |
