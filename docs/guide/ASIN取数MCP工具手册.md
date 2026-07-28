# ASIN 取数 MCP 工具手册

## 1. 使用范围

本文面向配置远程或本地 MCP 的 AI 工具使用者。ASIN 取数只调用四个 MCP Tool：

- `asin_data_live_data`
- `asin_data_fetch_file`
- `asin_data_yicopy_keyword_engine`
- `asin_data_category_top`

AI 不应拼装内部 HTTP 请求，也不得要求用户提供 Polaris JWT、BJX Token、Cookie、Session ID、账号或密码。

## 2. MCP 接入

### 2.1 远程 Streamable HTTP

远程部署不要求用户本地安装 opscli。向 MCP 服务管理员获取服务 URL 和 API Key，在 AI 工具的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "aukeys-ops": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <mcp-api-key>"
      }
    }
  }
}
```

服务端也支持旧式 SSE 端点 `https://mcp.example.com/sse`。新客户端优先使用 `/mcp` Streamable HTTP。API Key 只用于 MCP 连接鉴权，不是 OPS JWT 或 Polaris JWT。

### 2.2 本地 stdio

本地模式需要安装 `aukeys-opscli` 并完成 OPS 登录：

```powershell
python -m pip install --upgrade -i https://test.pypi.org/simple/ aukeys-opscli
opscli auth login
opscli auth token status
```

AI 工具配置：

```json
{
  "mcpServers": {
    "aukeys-ops-local": {
      "command": "opscli-mcp",
      "args": []
    }
  }
}
```

stdio 模式与本地 CLI 共用 `~/.config/opscli` 登录态。不要把命令配置为 shell 字符串，也不要把 Token 写进 `args`。

## 3. Polaris 配置和自动鉴权

本地 stdio 用户若要求按自己的刊登权限获取数据，在配置文件中启用：

```ini
[systems]
polaris_enabled = true
```

远程 MCP 用户无需维护本地 `config.ini`。服务端对刊登接口自动执行：

1. 当前 MCP 用户隔离凭证对应的 Polaris JWT。
2. Polaris `/api/auth/cli-token` 直接 exchange。
3. OPS `/dataMetrics/v1/asin-report-files/polaris-bjx-token` 托管 Token 回退。

仅当三条路径都失败时，工具返回 `POLARIS_USER_AUTH_MISSING`。个人 JWT 成功时不会请求托管 BJX Token，因此优先保留用户自己的刊登权限。MCP API Key、OPS JWT 和 Polaris Token 是三种不同凭据，调用方不得互相替代。

## 4. 统一 MCP envelope

成功：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

失败：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ASIN_BI_REPORT_DATA_BUSINESS_ERROR",
    "message": "Polaris user auth is missing or invalid: RuntimeError; direct token exchange failed: HTTP 500; managed BJX token fallback failed: HTTP 401",
    "business_code": "POLARIS_USER_AUTH_MISSING"
  },
  "feedback": {
    "feedback_type": "bug",
    "severity": "medium",
    "source": "mcp",
    "execution_summary": {
      "summary": "MCP Tool 调用失败，自动构造反馈草案。",
      "failed_calls": []
    }
  }
}
```

协议规则：

- 先判断 `success`，再访问 `data`。
- `success=false` 时 `data` 固定为 `null`。
- 自定义业务异常通常包含 `code`、`message` 和 `business_code`。
- 普通异常的 `error.code` 是异常类名。
- `feedback` 是结构化反馈草案，不是业务数据。按 Agent 规则提交后再继续原任务。
- MCP Tool 通常不抛业务失败给调用方，而是返回失败 envelope；传参类型不符合 MCP schema 时可能由协议层直接拒绝。

## 5. `asin_data_live_data`

### 5.1 用途

实时获取最新基础刊登/爬虫数据和 BI 数据。AI 默认应使用 `return_mode="ai_ready"` 和 `upload_xlsx=true`，先解析数据索引，再按需读取 OSS XLSX。

### 5.2 参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `asin` | string/null | null | 单个 ASIN；与 `input_path` 二选一 |
| `site` | string | `US` | 默认站点和爬虫 `country` |
| `data_scope` | string | `all` | `all/basic/bi/listing/listing_basic` |
| `sales_start` | string/null | null | BI 开始日期 `YYYY-MM-DD` |
| `sales_end` | string/null | null | BI 结束日期 `YYYY-MM-DD` |
| `upload_xlsx` | boolean | true | 上传实时 XLSX 到 OSS |
| `return_mode` | string | `ai_ready` | `content/url_only/both/ai_ready` |
| `run_id` | string/null | null | 可选运行 ID |
| `input_path` | string/null | null | 服务端可访问的 CSV/XLSX/JSON/JSONL 路径 |
| `keywords` | string/list/null | null | 单 ASIN 可选关键词 |
| `asin_column` | string | `asin` | 文件 ASIN 列名 |
| `keyword_column` | string | `keyword` | 文件关键词列名 |
| `site_column` | string | `site` | 文件站点列名 |
| `output_dir` | string | `output/asin-data` | 服务端输出目录 |
| `query_chunk_size` | integer | 100 | BI 批处理大小 |
| `session_id` | string/null | null | 内部兼容参数；普通调用方不要传 |
| `jwt` | string/null | null | 内部兼容参数；普通调用方不要传 |

`data_scope`：

- `basic`：完整基础数据，即刊登基础数据加爬虫补充数据。
- `listing`、`listing_basic`：仅刊登接口数据。
- `bi`：仅 BI。
- `all`：基础加 BI。

`return_mode`：

- `content`：内联完整内容。
- `url_only`：仅文件地址。
- `both`：内容与地址。
- `ai_ready`：统一 metadata、summary、artifacts、datasets、diagnostics；AI 首选。

### 5.3 调用样例

完整基础数据：

```json
{
  "name": "asin_data_live_data",
  "arguments": {
    "asin": "B0FDG9NFQM",
    "site": "US",
    "data_scope": "basic",
    "upload_xlsx": true,
    "return_mode": "ai_ready"
  }
}
```

仅刊登数据：

```json
{
  "name": "asin_data_live_data",
  "arguments": {
    "asin": "B0FDG9NFQM",
    "site": "US",
    "data_scope": "listing_basic",
    "upload_xlsx": true,
    "return_mode": "ai_ready"
  }
}
```

最近 7 天 BI：

```json
{
  "name": "asin_data_live_data",
  "arguments": {
    "asin": "B0FDG9NFQM",
    "site": "US",
    "data_scope": "bi",
    "sales_start": "2026-07-08",
    "sales_end": "2026-07-14",
    "upload_xlsx": true,
    "return_mode": "ai_ready"
  }
}
```

### 5.4 成功样例

```json
{
  "success": true,
  "data": {
    "metadata": {
      "protocol": "asin_data_ai_response",
      "protocol_version": "1.0",
      "tool": "asin_data_live_data",
      "data_scope": "bi",
      "request": {
        "site": "US",
        "sales_start": "2026-07-08",
        "sales_end": "2026-07-14",
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
            "file_key": "bi",
            "format": "xlsx",
            "uri": "https://example.oss/asin-data/B0FDG9NFQM-bi-live-data.xlsx"
          }
        ],
        "datasets": [
          {
            "source_key": "sales_traffic",
            "row_count": 7,
            "preview_rows": [{"ASIN": "B0FDG9NFQM", "日期": "2026-07-14"}],
            "quality": {"empty": false, "has_warnings": false},
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

`preview_rows` 只是预览；完整数据必须从 `artifacts[].uri` 的 XLSX 或 `content` 模式读取。BI 常见 `source_key` 包括 `sales_traffic`、`sp_keyword`、`sp_search_term`、`deals`、`turnover_inventory`。

### 5.5 失败样例

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ASIN_BI_REPORT_DATA_BUSINESS_ERROR",
    "message": "Polaris user auth is missing or invalid: RuntimeError; direct token exchange failed: HTTP 500; managed BJX token fallback failed: HTTP 401",
    "business_code": "POLARIS_USER_AUTH_MISSING"
  },
  "feedback": {
    "feedback_type": "bug",
    "severity": "medium",
    "source": "mcp"
  }
}
```

## 6. `asin_data_fetch_file`

### 6.1 用途和参数

读取已经上传的历史拆包内容。最新基础/BI 应调用实时工具；卖家精灵、竞品和 Rufus 使用本工具。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `asin` | string | required | ASIN |
| `file_key` | string | required | `basic/bi/keyword_reverse/keyword_miner/competitor/rufus` |
| `site` | string | `US` | 站点 |
| `session_id` | string/null | null | 普通调用方不要传 |
| `jwt` | string/null | null | 普通调用方不要传 |

文件类型：`basic`、`bi`、`keyword_reverse`、`keyword_miner`、`competitor`、`rufus`。

### 6.2 调用样例

```json
{
  "name": "asin_data_fetch_file",
  "arguments": {
    "asin": "B0FDG9NFQM",
    "site": "US",
    "file_key": "keyword_reverse"
  }
}
```

### 6.3 成功样例

```json
{
  "success": true,
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

### 6.4 失败样例

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ASIN_REPORT_FILE_NOT_FOUND",
    "message": "ASIN report file not found"
  },
  "feedback": {
    "feedback_type": "bug",
    "severity": "medium",
    "source": "mcp"
  }
}
```

## 7. `asin_data_yicopy_keyword_engine`

### 7.1 参数

该工具无需登录。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `asin` | string/list/null | null | ASIN、含 ASIN 文本或 JSON 字符串数组 |
| `url` | string/list/null | null | Amazon URL |
| `input_path` | string/null | null | 服务端可访问输入文件 |
| `site` | string | `US` | Amazon 站点 |
| `locale` | string | `en_US` | Completion locale |
| `result_format` | string | `keyword-reverse` | `keyword-reverse` 或 `full` |
| `max_asins` | integer/null | null | 最大 ASIN 数 |
| `max_prefixes_per_asin` | integer/null | null | 每 ASIN 最大前缀数 |
| `completion_limit` | integer | 11 | 自动补全上限 |
| `timeout_seconds` | number | 30.0 | 请求超时 |
| `request_delay_seconds` | number | 0.0 | 请求间隔 |
| `output_path` | string/null | null | 可选服务端 JSON 输出路径 |

### 7.2 调用样例

```json
{
  "name": "asin_data_yicopy_keyword_engine",
  "arguments": {
    "asin": ["B0F9F6B6VK"],
    "site": "US",
    "result_format": "keyword-reverse"
  }
}
```

### 7.3 成功样例

```json
{
  "success": true,
  "data": {
    "metadata": {
      "protocol": "asin_data_ai_response",
      "tool": "asin_data_yicopy_keyword_engine",
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

### 7.4 失败样例

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ValueError",
    "message": "请通过 asin、url 或 input_path 传入至少一个 ASIN 或 URL。"
  },
  "feedback": {
    "feedback_type": "bug",
    "severity": "medium",
    "source": "mcp"
  }
}
```

## 8. `asin_data_category_top`

### 8.1 AI 自动确定最小类目流程

用户只提供 ASIN、未直接提供类目时，AI 必须按顺序调用，不能并行：

1. 先调用 `asin_data_live_data`，传入目标 ASIN、`data_scope="listing_basic"`、`return_mode="ai_ready"` 和 `upload_xlsx=true`。
2. 在成功响应的 `data.items[].datasets[]` 中选择 `source_key=listing_basic`，读取行内标准字段 `类目`。如果 `preview_rows` 没有该字段，则读取 `artifacts[].uri` 的基础 XLSX，在“刊登数据”工作表中读取 `类目`，不得改用旧历史基础文件推断。
3. 将 `类目` 按英文逗号 `,` 拆分，对每段去除首尾空白，删除空段，取最后一个非空值作为最小类目。
4. 示例：`Home & Kitchen,Furniture,Home Office Furniture,Bookcases` 必须解析为 `Bookcases`。
5. 再调用 `asin_data_category_top`，将 `category` 设置为最小类目原值；不得翻译、扩写或传上级类目。
6. 没有逗号时，整个非空值就是最小类目。字段缺失、为空或拆分后无有效值时，AI 必须停止并向用户索取类目，不得猜测。
7. 批量 ASIN 对应多个最小类目时，按最小类目分组，每个唯一类目分别调用一次 `asin_data_category_top`。

第一步调用：

```json
{
  "name": "asin_data_live_data",
  "arguments": {
    "asin": "B0TEST1234",
    "site": "US",
    "data_scope": "listing_basic",
    "upload_xlsx": true,
    "return_mode": "ai_ready"
  }
}
```

解析 `类目` 得到 `Bookcases` 后执行第二步：

```json
{
  "name": "asin_data_category_top",
  "arguments": {
    "category": "Bookcases",
    "limit": 10,
    "site": "US",
    "upload": true,
    "enrich": true
  }
}
```

### 8.2 参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `category` | string | required | 精确匹配 `amazon_cat`，如 `Bed Frames` |
| `date_from` | string/null | null | 起始日期；空值取当月 1 日 |
| `date_to` | string/null | null | 截止日期；空值取当天 |
| `limit` | integer | 10 | 1-100 |
| `site` | string | `US` | 默认站点和爬虫 country |
| `upload` | boolean | true | 上传合并文件 |
| `enrich` | boolean | true | 补充刊登和爬虫数据 |
| `return_content` | boolean | false | 内联完整 JSON；大批量不建议开启 |
| `output_dir` | string | `output/asin-data` | 服务端输出目录 |
| `run_id` | string/null | null | 运行 ID |
| `session_id` | string/null | null | 普通调用方不要传 |
| `jwt` | string/null | null | 普通调用方不要传 |

### 8.3 调用样例

```json
{
  "name": "asin_data_category_top",
  "arguments": {
    "category": "Bed Frames",
    "date_from": "2026-07-01",
    "date_to": "2026-07-14",
    "limit": 10,
    "site": "US",
    "upload": true,
    "enrich": true,
    "return_content": false
  }
}
```

### 8.4 成功样例

```json
{
  "success": true,
  "data": {
    "metadata": {
      "protocol": "asin_data_ai_response",
      "tool": "asin_data_category_top",
      "data_scope": "internal_category_top"
    },
    "summary": {
      "status": "success",
      "category": "Bed Frames",
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

### 8.5 失败样例

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ASIN_CATEGORY_TOP_HTTP_ERROR",
    "message": "upstream category service unavailable",
    "status_code": 503
  },
  "feedback": {
    "feedback_type": "bug",
    "severity": "medium",
    "source": "mcp"
  }
}
```

## 9. AI 工具调用策略

| 用户意图 | 工具与关键参数 |
| --- | --- |
| 最新完整基础数据 | `asin_data_live_data(data_scope="basic", upload_xlsx=true, return_mode="ai_ready")` |
| 最新刊登数据 | `asin_data_live_data(data_scope="listing_basic", upload_xlsx=true, return_mode="ai_ready")` |
| 最新 BI | `asin_data_live_data(data_scope="bi", sales_start=..., sales_end=...)` |
| 最新基础和 BI | `asin_data_live_data(data_scope="all", sales_start=..., sales_end=...)` |
| 卖家精灵 | `asin_data_fetch_file(file_key="keyword_reverse"/"keyword_miner")` |
| Rufus | `asin_data_fetch_file(file_key="rufus")` |
| yicopy 销词 | `asin_data_yicopy_keyword_engine(...)` |
| 类目 Top | `asin_data_category_top(...)` |

解析顺序：

1. 检查外层 `success`。
2. 读取 `data.metadata.protocol` 和 `data.summary`。
3. 遍历 `data.items[]`，跳过 `status=failed` 的项目并记录其诊断。
4. 按 `datasets[].source_key` 选择所需数据源。
5. `preview_rows` 仅用于识别结构；完整分析读取 `artifacts[].uri`。
6. 检查全局、item 和 dataset 三层 `diagnostics`，不能静默忽略空集或过滤警告。

## 10. 失败恢复和稳定性

| 失败 | 处理 |
| --- | --- |
| MCP HTTP 401 | API Key 无效或过期；更新 MCP 配置中的 Bearer API Key |
| `POLARIS_USER_AUTH_MISSING` | 三条刊登鉴权路径都失败；远程用户联系服务管理员，本地用户重新登录并检查 Polaris 开关 |
| `FILE_UPLOAD_HTTP_ERROR` | OSS 上传失败；保持参数退避重试，必要时临时 `upload_xlsx=false` 获取内联内容 |
| `ASIN_REPORT_FILE_NOT_FOUND` | 核对 ASIN、站点和 `file_key`；最新基础/BI 改用实时工具 |
| `ExceptionGroup` | 并发子任务异常未被正确归一；提交 `feedback`，保留工具名、参数和原始 error |

推荐重试策略：只对 HTTP 429、502、503、504 和短暂网络错误重试，最多 3 次，间隔 1 秒、2 秒、4 秒；参数错误、无权限和文件不存在不做盲目重试。

工具失败后必须按项目规范使用 `feedback` 草案提交结构化反馈。反馈内容应包含工具名、脱敏参数、原始错误码、原因推测和修复建议，绝不能包含 MCP API Key、JWT、Cookie、Session ID、账号或密码。
