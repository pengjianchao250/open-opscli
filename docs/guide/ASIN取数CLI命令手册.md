# ASIN 取数 CLI 命令手册

## 1. 使用范围

本文面向本地终端用户和调用本地 CLI 的 AI Skill，只使用以下四个公开入口：

- `opscli asin-data live-data`：实时获取基础刊登、爬虫补充数据和 BI 数据，可生成并上传 XLSX。
- `opscli asin-data fetch-file`：读取服务端已经生成的历史拆包文件，适用于卖家精灵、竞品和 Rufus。
- `opscli asin-data yicopy-keyword-engine`：实时执行 yicopy 销词引擎。
- `opscli asin-data category-top`：获取内部类目 Top ASIN，并按需补充刊登和爬虫数据。

实时基础数据和 BI 数据必须使用 `live-data`；历史卖家精灵和 Rufus 文件必须使用 `fetch-file`。不要用其他批量采集入口替代这两个取数入口。

## 2. 安装与升级

未安装测试版时：

```powershell
python -m pip install --upgrade -i https://test.pypi.org/simple/ aukeys-opscli
```

同时存在 `opscli` 和 `aukeys-opscli` Python 包时，优先升级并使用 `aukeys-opscli` 提供的 `opscli` 可执行命令。检查版本和命令：

```powershell
opscli --version
opscli asin-data --help
```

安装或更新 AI Skills：

```powershell
opscli skills install --yes --runtime all
opscli skills upgrade
```

## 3. 登录和 Polaris 鉴权

### 3.1 首次登录

```powershell
opscli auth login
opscli auth token status
opscli auth token check --system ops
```

`live-data`、`fetch-file` 和 `category-top` 需要有效 OPS 登录。`yicopy-keyword-engine` 不依赖 OPS 登录。

### 3.2 开启个人 Polaris 权限

配置文件位置：

- Windows：`%USERPROFILE%\.config\opscli\config.ini`
- macOS/Linux：`~/.config/opscli/config.ini`

写入：

```ini
[systems]
polaris_enabled = true
```

也可只对当前进程设置：

```powershell
$env:OPSCLI_POLARIS_ENABLED = "true"
```

启用后检查或刷新个人 Polaris Token：

```powershell
opscli auth token check --system polaris
opscli auth token refresh --system polaris
```

### 3.3 自动回退顺序

默认刊登鉴权按以下顺序执行，用户无需输入 Token、Cookie、Session ID、账号或密码：

1. 当前登录用户的 Polaris JWT，保留个人刊登数据权限。
2. 使用本地登录 Session 调用 Polaris `/api/auth/cli-token`。
3. 前两步失败后，通过 OPS 接口 `/dataMetrics/v1/asin-report-files/polaris-bjx-token` 获取托管 BJX Token。
4. 三步都失败才返回 `POLARIS_USER_AUTH_MISSING`。

若 `polaris_enabled` 关闭或 Polaris 系统未注册，实时刊登取数仍会尝试第 2、3 步；此时结果可能使用托管账号权限。要求严格按个人权限返回时，必须开启 Polaris 并完成个人登录。

## 4. 统一 CLI 返回协议

所有命令向标准输出写一个 JSON 对象。`--pretty` 只改变缩进，不改变字段。

成功，进程退出码为 `0`：

```json
{
  "success": true,
  "command": "asin-data live-data",
  "data": {},
  "error": null
}
```

失败，进程退出码为 `1`：

```json
{
  "success": false,
  "command": "asin-data live-data",
  "data": null,
  "error": {
    "code": "POLARIS_USER_AUTH_MISSING",
    "message": "Polaris user auth is missing or invalid: RuntimeError; direct token exchange failed: HTTP 500; managed BJX token fallback failed: HTTP 401",
    "business_code": "POLARIS_USER_AUTH_MISSING"
  }
}
```

调用方必须先判断 `success`，失败时读取 `error.code`、`error.business_code` 和 `error.message`，不得把失败对象当作数据继续解析。

## 5. `live-data` 实时取数

### 5.1 选择数据范围

`--data-scope` 支持：

| 值 | 返回范围 | 推荐场景 |
| --- | --- | --- |
| `all` | 完整基础数据和 BI 数据 | 一次生成完整巡检材料 |
| `basic` | 刊登基础数据和爬虫补充数据 | Listing 巡检；A+ 内容仍来自爬虫补充数据 |
| `listing` | 仅刊登接口数据 | 只核对当前北极星刊登字段 |
| `listing_basic` | 与 `listing` 等价的兼容名称 | AI Skill 明确请求基础刊登接口 |
| `bi` | 仅 BI 数据 | 最近 7 天销售、广告、库存和 Deal 分析 |

`--return-mode` 支持：

| 值 | 含义 |
| --- | --- |
| `content` | 返回内联数据内容；数据大时响应较大 |
| `url_only` | 只保留上传后的 XLSX 地址；必须同时使用 `--upload-xlsx` |
| `both` | 同时返回内联内容和文件地址 |
| `ai_ready` | 返回统一协议、文件索引、数据集预览、质量诊断；推荐 AI 使用 |

### 5.2 常用参数

| 参数 | 类型/默认值 | 说明 |
| --- | --- | --- |
| `--asin` | string | 单个 ASIN，与 `--input` 二选一 |
| `--input`, `-i` | path | CSV/XLSX/JSON/JSONL 批量输入 |
| `--site` | `US` | 默认站点，同时传给爬虫接口的 `country` |
| `--data-scope` | `all` | `all/basic/bi/listing/listing_basic` |
| `--sales-start` | date/null | BI 开始日期，`YYYY-MM-DD` |
| `--sales-end` | date/null | BI 结束日期，`YYYY-MM-DD` |
| `--upload-xlsx` | false | 上传实时 basic/bi XLSX 到 OSS |
| `--return-mode` | `content` | `content/url_only/both/ai_ready` |
| `--output-dir` | `output/asin-data` | 本地运行目录 |
| `--run-id` | null | 自定义运行 ID，便于追踪 |
| `--query-chunk-size` | `100` | 批量 BI 每批 ASIN 数量 |
| `--asin-column` | `asin` | 输入文件 ASIN 列 |
| `--site-column` | `site` | 输入文件站点列 |
| `--keyword` | repeatable | 单 ASIN 的可选关键词 |
| `--pretty` | false | 格式化 JSON |

日期未传时由数据源使用自身默认范围。巡检 BI 建议显式传最近 7 天，避免数据量过大和时间口径不明确。

### 5.3 单独获取完整基础数据并上传 XLSX

```powershell
opscli asin-data live-data --asin B0FDG9NFQM --site US --data-scope basic --upload-xlsx --return-mode ai_ready --pretty
```

### 5.4 单独获取基础刊登数据

```powershell
opscli asin-data live-data --asin B0FDG9NFQM --site US --data-scope listing_basic --upload-xlsx --return-mode ai_ready --pretty
```

### 5.5 单独获取最近 7 天 BI 数据

```powershell
opscli asin-data live-data --asin B0FDG9NFQM --site US --data-scope bi --sales-start 2026-07-08 --sales-end 2026-07-14 --upload-xlsx --return-mode ai_ready --pretty
```

### 5.6 同时获取基础和 BI 数据

```powershell
opscli asin-data live-data --asin B0FDG9NFQM --site US --data-scope all --sales-start 2026-07-08 --sales-end 2026-07-14 --upload-xlsx --return-mode ai_ready --pretty
```

### 5.7 批量输入

输入文件至少包含 `asin`，多站点时增加 `site`：

```csv
asin,site
B0FDG9NFQM,US
B0GZVCTNB3,CA
```

```powershell
opscli asin-data live-data --input .\asins.csv --data-scope basic --upload-xlsx --return-mode ai_ready --pretty
```

### 5.8 `ai_ready` 成功样例

```json
{
  "success": true,
  "command": "asin-data live-data",
  "data": {
    "metadata": {
      "protocol": "asin_data_ai_response",
      "protocol_version": "1.0",
      "tool": "asin_data_live_data",
      "data_scope": "basic",
      "request": {
        "site": "US",
        "return_mode": "ai_ready"
      }
    },
    "summary": {
      "requested_asin_count": 1,
      "success_asin_count": 1,
      "failed_asin_count": 0
    },
    "items": [
      {
        "asin": "B0FDG9NFQM",
        "site": "US",
        "status": "success",
        "artifacts": [
          {
            "file_key": "basic",
            "format": "xlsx",
            "uri": "https://example.oss/asin-data/B0FDG9NFQM-basic-live-data.xlsx"
          }
        ],
        "datasets": [
          {
            "source_key": "listing_basic",
            "row_count": 1,
            "preview_rows": [
              {
                "ASIN": "B0FDG9NFQM",
                "产品标题": "Example title"
              }
            ],
            "quality": {
              "empty": false,
              "has_warnings": false
            },
            "diagnostics": []
          }
        ],
        "diagnostics": []
      }
    ],
    "diagnostics": [],
    "preferred_fields": [
      "items[].artifacts",
      "items[].datasets",
      "items[].diagnostics"
    ]
  },
  "error": null
}
```

字段含义：

- `artifacts[].uri`：优先交给文件读取器的 OSS 地址。
- `datasets[].source_key`：数据源标识，如 `listing_basic`、`crawler_details`、`sales_traffic`、`sp_search_term`。
- `preview_rows`：AI 快速识别用预览，不代表完整 XLSX 全部行。
- `row_count`：完整数据集行数。
- `quality.empty`：是否为空集。
- `diagnostics`：缺日期、空数据、过滤未验证、编码异常等质量提示。

### 5.9 失败样例

```json
{
  "success": false,
  "command": "asin-data live-data",
  "data": null,
  "error": {
    "code": "ASIN_BI_REPORT_DATA_BUSINESS_ERROR",
    "message": "Polaris user auth is missing or invalid: RuntimeError; direct token exchange failed: HTTP 500; managed BJX token fallback failed: HTTP 401",
    "business_code": "POLARIS_USER_AUTH_MISSING"
  }
}
```

## 6. `fetch-file` 历史拆包文件

### 6.1 文件类型

`--file` 必须是：

| 值 | 内容 |
| --- | --- |
| `basic` | 历史基础 XLSX |
| `bi` | 历史 BI XLSX |
| `keyword_reverse` | 卖家精灵关键词反查 |
| `keyword_miner` | 卖家精灵关键词挖掘 |
| `competitor` | 竞品文件 |
| `rufus` | Rufus Markdown/结果文件 |

基础和 BI 的最新数据优先使用 `live-data`。`fetch-file` 中的 `basic`、`bi` 仅用于回看已生成的历史包。

### 6.2 命令

```powershell
opscli asin-data fetch-file --asin B0FDG9NFQM --site US --file keyword_reverse --pretty
opscli asin-data fetch-file --asin B0FDG9NFQM --site US --file keyword_miner --pretty
opscli asin-data fetch-file --asin B0FDG9NFQM --site US --file competitor --pretty
opscli asin-data fetch-file --asin B0FDG9NFQM --site US --file rufus --pretty
```

成功样例：

```json
{
  "success": true,
  "command": "asin-data fetch-file",
  "data": {
    "asin": "B0FDG9NFQM",
    "site": "US",
    "file_key": "keyword_reverse",
    "file_url": ["https://example.oss/asin-data/keyword_reverse.xlsx"],
    "content": {
      "Sheet1": [
        ["关键词", "搜索量"],
        ["bed frame", 1000]
      ]
    }
  },
  "error": null
}
```

失败样例：

```json
{
  "success": false,
  "command": "asin-data fetch-file",
  "data": null,
  "error": {
    "code": "ASIN_REPORT_FILE_NOT_FOUND",
    "message": "ASIN report file not found"
  }
}
```

XLSX 内容按工作表转换为 `{sheet_name: [row_array]}`；第一行通常是表头。Markdown 文件返回文本。调用方应以实际 `content` 类型为准。

## 7. `yicopy-keyword-engine`

### 7.1 参数

| 参数 | 类型/默认值 | 说明 |
| --- | --- | --- |
| `--asin`, `-a` | repeatable | ASIN 或包含 ASIN 的文本 |
| `--url`, `-u` | repeatable | Amazon 商品 URL |
| `--input-file`, `-i` | path | JSON、JSON 数组或文本输入 |
| `--site` | `US` | Amazon 站点 |
| `--locale` | `en_US` | Completion API locale |
| `--result-format` | `keyword-reverse` | `keyword-reverse` 或 `full` |
| `--max-asins` | null | 最大 ASIN 数 |
| `--max-prefixes-per-asin` | null | 每个 ASIN 最大标题前缀数 |
| `--completion-limit` | `11` | 每次自动补全上限 |
| `--timeout-seconds` | `30.0` | HTTP 超时 |
| `--request-delay-seconds` | `0.0` | 请求间隔 |
| `--output-file`, `-o` | null | 写入 UTF-8 JSON；设置后响应不内联完整 `result` |

```powershell
opscli asin-data yicopy-keyword-engine --asin B0F9F6B6VK --site US --result-format keyword-reverse --output .\output\yicopy.json --pretty
```

成功样例：

```json
{
  "success": true,
  "command": "asin-data yicopy-keyword-engine",
  "data": {
    "metadata": {
      "protocol": "asin_data_ai_response",
      "tool": "asin-data yicopy-keyword-engine",
      "data_scope": "yicopy_keyword_reverse"
    },
    "summary": {
      "requested_asin_count": 1,
      "success_asin_count": 1
    },
    "items": [
      {
        "asin": "B0F9F6B6VK",
        "status": "success",
        "datasets": [
          {
            "source_key": "yicopy_keyword_reverse",
            "row_count": 1,
            "preview_rows": [{"keyword": "wireless mouse"}]
          }
        ],
        "diagnostics": []
      }
    ],
    "diagnostics": []
  },
  "error": null
}
```

失败样例：

```json
{
  "success": false,
  "command": "asin-data yicopy-keyword-engine",
  "data": null,
  "error": {
    "code": "ASIN_DATA_ERROR",
    "message": "请通过 --asin、--url 或 --input-file 传入至少一个 ASIN 或 URL。"
  }
}
```

## 8. `category-top`

### 8.1 参数和命令

| 参数 | 类型/默认值 | 说明 |
| --- | --- | --- |
| `--category` | required string | 精确匹配平台类目 `amazon_cat` |
| `--date-from` | null | 开始日期；空值由后端取当月 1 日 |
| `--date-to` | null | 结束日期；空值由后端取当天 |
| `--limit` | `10` | Top 数，范围 1-100 |
| `--site` | `US` | 无法从渠道推断时的默认站点/爬虫 country |
| `--upload/--no-upload` | true | 上传合并后的 XLSX 到 OSS；本地同时保留 JSON 旁车文件 |
| `--enrich/--no-enrich` | true | 补充 `listing_basic` 和 `crawler_details` |
| `--return-content` | false | 响应内联完整内容；大批量不建议开启 |
| `--output-dir` | `output/asin-data` | 本地输出目录 |
| `--run-id` | null | 运行 ID |

```powershell
opscli asin-data category-top --category "Bed Frames" --date-from 2026-07-01 --date-to 2026-07-14 --limit 10 --site US --upload --enrich --pretty
```

成功样例：

```json
{
  "success": true,
  "command": "asin-data category-top",
  "data": {
    "metadata": {
      "protocol": "asin_data_ai_response",
      "tool": "asin_data_category_top",
      "data_scope": "internal_category_top"
    },
    "summary": {
      "category": "Bed Frames",
      "status": "success",
      "asin_count": 10,
      "top_count": 10,
      "failed_asin_count": 0,
      "file_url": "https://example.oss/asin-data/internal-category-top-asin-data.xlsx"
    },
    "items": [
      {
        "asin": "B0TEST1234",
        "status": "success",
        "datasets": [
          {"source_key": "category_top", "row_count": 1, "preview_rows": []},
          {"source_key": "listing_basic", "row_count": 1, "preview_rows": []},
          {"source_key": "crawler_details", "row_count": 1, "preview_rows": []}
        ],
        "diagnostics": []
      }
    ],
    "diagnostics": []
  },
  "error": null
}
```

失败样例：

```json
{
  "success": false,
  "command": "asin-data category-top",
  "data": null,
  "error": {
    "code": "ASIN_CATEGORY_TOP_HTTP_ERROR",
    "message": "upstream category service unavailable",
    "status_code": 503
  }
}
```

## 9. AI Skill 取数决策

| 用户需求 | 必须调用 |
| --- | --- |
| 最新完整基础数据 | `live-data --data-scope basic --upload-xlsx --return-mode ai_ready` |
| 最新北极星刊登字段 | `live-data --data-scope listing_basic --upload-xlsx --return-mode ai_ready` |
| 最新 BI | `live-data --data-scope bi`，显式给出日期范围 |
| 最新基础 + BI | `live-data --data-scope all`，显式给出 BI 日期范围 |
| 卖家精灵反查/挖词 | `fetch-file --file keyword_reverse` 或 `keyword_miner` |
| Rufus 历史结果 | `fetch-file --file rufus` |
| yicopy 实时销词 | `yicopy-keyword-engine` |
| 内部类目 Top ASIN | `category-top` |

AI 读取顺序：先判断 `success`，再读 `data.metadata` 和 `data.summary`，然后按 `items[].datasets` 分析；需要完整明细时读取 `items[].artifacts[].uri` 对应文件。不得把 `preview_rows` 误认为完整数据。

## 10. 常见错误与恢复

| 错误 | 含义 | 恢复动作 |
| --- | --- | --- |
| `POLARIS_USER_AUTH_MISSING` | 个人 JWT、直接 exchange、BJX Token 都失败 | 检查网络和 OPS 登录；开启 Polaris；重新登录后重试 |
| `ASIN_BI_REPORT_DATA_HTTP_ERROR` | 上游 BI/刊登接口 HTTP 失败 | 保持相同参数退避重试；持续失败时提交反馈 |
| `ASIN_REPORT_FILE_NOT_FOUND` | 历史拆包不存在 | 核对 ASIN、站点和文件类型；最新基础/BI 改用实时入口 |
| `FILE_UPLOAD_HTTP_ERROR` | OSS 上传服务失败或未授权 | 检查 OPS Token，刷新后重试；可先用 `--no-upload-xlsx --return-mode content` 验证取数 |
| `ASIN_DATA_ERROR` | 参数或本地输入错误 | 检查必填参数、输入路径和日期格式 |

认证恢复顺序：

```powershell
opscli auth token status
opscli auth token check --system ops
opscli auth token refresh --system ops
opscli auth login
```

任何 CLI 失败都应保留原始命令参数和 `error` 对象，并按项目规范提交结构化反馈；不得在反馈中附带 JWT、Cookie、Session ID、账号或密码。
