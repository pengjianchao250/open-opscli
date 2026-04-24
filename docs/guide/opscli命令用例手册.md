# opscli 命令用例手册

本文档基于当前仓库代码整理，覆盖 `opscli` 顶级命令、全部子命令、参数说明与常见使用示例。

- 代码基线：`aukeys-opscli` `0.0.7`
- 命令入口：`opscli`
- 主要来源：
  - `opscli/cli.py`
  - `opscli/auth/cli.py`
  - `opscli/amazon/commands/cli.py`
  - `opscli/query/commands/cli.py`
  - `opscli/skills/commands/cli.py`

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
│   ├── run
│   └── build
└── skills
    ├── list
    ├── install
    ├── status
    └── upgrade
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

### 2.3 通用约定

- 所有命令都支持 `--help`。
- `amazon`、`query`、`skills` 模块普遍支持 `--pretty` 进行 JSON 美化输出。
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

### 6.2 `opscli query run`

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

### 6.3 `opscli query build`

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

## 7. Skill 模块 `opscli skills`

用于扫描已安装 Skill、安装内置模板、查看状态、升级远端版本。

### 7.1 内置 Skill 模板

当前仓库内置以下模板：

| Skill 名称 | 说明 |
| --- | --- |
| `ops-amazon` | Amazon 抓取辅助 Skill |
| `ops-auth` | 认证授权辅助 Skill |
| `ops-dataset-query` | 数据集查询辅助 Skill |
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

- `--runtime` 的帮助文本当前写的是 `claude、openclaw、all`。
- 实际代码还支持 `codex`、`opencode`，并支持逗号分隔多值，例如 `claude,codex`。
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

## 8. 常见组合用例

### 8.1 首次完成认证并查询数据

```bash
opscli auth login
opscli skills install ops-dataset-query
opscli query metadata --dataset sales_order_d --pretty
opscli query build --dataset sales_order_d --dimension date_id --metric gmv:sum --output payload.json --pretty
opscli query run --payload payload.json --pretty
```

### 8.2 检查并刷新某个系统的 Token

```bash
opscli auth token status
opscli auth token check -s ops
opscli auth token refresh -s ops
opscli auth token get -s ops
```

### 8.3 抓取 Amazon 商品并查看历史

```bash
opscli amazon scrape --asin B09LCJPZ1P --include-raw --pretty
opscli amazon payload --asin B09LCJPZ1P --pretty
opscli amazon history --asin B09LCJPZ1P --pretty
```

### 8.4 检查 Skill 是否有更新

```bash
opscli skills list --pretty
opscli skills status --pretty
opscli skills upgrade ops-dataset-query --pretty
```

## 9. 快速索引

| 模块 | 命令 |
| --- | --- |
| 顶级 | `opscli --version`、`opscli --help` |
| 认证 | `opscli auth login`、`logout`、`doctor` |
| Token | `opscli auth token status`、`get`、`check`、`refresh` |
| 系统管理 | `opscli auth system list`、`sync`、`add`、`remove` |
| Amazon | `opscli amazon scrape`、`payload`、`search`、`schema`、`history` |
| 查询 | `opscli query metadata`、`run`、`build` |
| Skills | `opscli skills list`、`install`、`status`、`upgrade` |
