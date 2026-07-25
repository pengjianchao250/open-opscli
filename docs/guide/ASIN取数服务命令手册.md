# ASIN取数服务命令手册

> 适用命令：`opscli asin-data basic`、`opscli asin-data bi`、`opscli asin-data category-top`
> 更新日期：2026-07-16

## 1. 服务概览

| 中文服务 | CLI 命令 | 必填查询项 | 默认结果 |
| --- | --- | --- | --- |
| 基础数据查询 | `opscli asin-data basic` | ASIN | 刊登基础数据和爬虫补充数据 JSON |
| BI数据查询 | `opscli asin-data bi` | ASIN | 最近30天全部 BI 数据域 JSON |
| 类目Top查询 | `opscli asin-data category-top` | 类目名称 | 当月类目 Top 10 JSON |

`basic`、`bi`、`category-top` 只返回 JSON，不生成 Excel、不上传 OSS。

快速示例：

```powershell
opscli asin-data basic --asin B086M58PQ3 --site US
opscli asin-data bi --asin B086M58PQ3 --site US --domain sqp
opscli asin-data category-top --category "Bed Frames" --site US --limit 10
```

## 2. 公共输入规则

### 2.1 ASIN输入

单个 ASIN：

```powershell
opscli asin-data basic --asin B086M58PQ3
```

重复传入多个 ASIN：

```powershell
opscli asin-data basic `
  --asin B086M58PQ3 `
  --asin B0TEST1234
```

使用 JSON 数组批量传入：

```powershell
opscli asin-data basic `
  --asins '["B086M58PQ3","B0TEST1234"]'
```

约束：

- `--asin` 与 `--asins` 至少传入一个。
- `--asin` 可以重复使用，也可以与 `--asins` 同时使用。
- ASIN 会自动去除首尾空格、转为大写并去重。
- ASIN 必须是10位字母或数字。

### 2.2 站点

所有主命令均支持 `--site`，默认 `US`。

| 站点 | 代码 | 站点 | 代码 |
| --- | --- | --- | --- |
| 美国 | `US` | 英国 | `UK` |
| 加拿大 | `CA` | 德国 | `DE` |
| 法国 | `FR` | 意大利 | `IT` |
| 西班牙 | `ES` | 日本 | `JP` |
| 澳大利亚 | `AU` | 墨西哥 | `MX` |
| 巴西 | `BR` | 阿联酋 | `AE` |
| 沙特 | `SA` |  |  |

### 2.3 日期

- 格式固定为 `YYYY-MM-DD`。
- `date_from` 不能晚于 `date_to`。
- 日期范围不能包含未来日期。

### 2.4 格式化JSON

所有命令支持 `--pretty`：

```powershell
opscli asin-data basic --asin B086M58PQ3 --pretty
```

## 3. 基础数据查询

### 3.1 命令格式

```text
opscli asin-data basic [--asin ASIN] [--asins JSON] [--site SITE]
                       [--source listing|crawler] [--pretty]
```

### 3.2 参数

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--asin` | 条件必填 | - | 单个 ASIN，可重复传入 |
| `--asins` | 条件必填 | - | ASIN JSON 数组 |
| `--site` | 否 | `US` | Amazon站点代码 |
| `--source` | 否 | 全部 | 可重复传入 `listing`、`crawler` |
| `--pretty` | 否 | `false` | 格式化输出 JSON |

### 3.3 数据范围

| source | 内部数据源 | 可获取数据 |
| --- | --- | --- |
| `listing` | `listing_basic` | 标题、五点、产品描述、商品亮点、品牌、类目等刊登字段 |
| `crawler` | `crawler_details` | A+图片、A+描述、QA、Review List 等爬虫补充字段 |

不传 `--source` 时同时查询 `listing` 和 `crawler`。

刊登渠道未明确时，服务先按 SC 的 `account_type=1` 查询；未找到后自动按 VC 的 `account_type=2` 重试。用户不需要传入 `account_type`。

### 3.4 取数来源

| 数据 | 来源接口 |
| --- | --- |
| 刊登列表和 listing ID | `https://bi.api.xenkee.com/listing/getAmazonListing` |
| 刊登详情 | `https://bi.api.xenkee.com/listing/amazonlisdet` |
| 刊登模板字段 | `https://bi.api.xenkee.com/amazon/feed/getTemplate` |
| 爬虫补充数据 | `/dataMetrics/v1/asin-report-files/crawler-details` |

### 3.5 使用示例

查询完整基础数据：

```powershell
opscli asin-data basic --asin B086M58PQ3 --site US
```

只查刊登数据：

```powershell
opscli asin-data basic --asin B086M58PQ3 --source listing
```

只查爬虫补充数据：

```powershell
opscli asin-data basic --asin B086M58PQ3 --source crawler
```

### 3.6 返回结构

```json
{
  "success": true,
  "command": "asin-data basic",
  "data": {
    "status": "success",
    "asins": ["B086M58PQ3"],
    "site": "US",
    "source_count": 2,
    "row_count": 2,
    "sources": {
      "listing_basic": {
        "status": "success",
        "row_count": 1,
        "rows": []
      },
      "crawler_details": {
        "status": "success",
        "row_count": 1,
        "rows": []
      }
    }
  },
  "error": null
}
```

## 4. BI数据查询

### 4.1 命令格式

```text
opscli asin-data bi [--asin ASIN] [--asins JSON] [--site SITE]
                    [--date-from DATE] [--date-to DATE]
                    [--domain DOMAIN] [--pretty]
```

### 4.2 参数

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--asin` | 条件必填 | - | 单个 ASIN，可重复传入 |
| `--asins` | 条件必填 | - | ASIN JSON 数组 |
| `--site` | 否 | `US` | Amazon站点代码 |
| `--date-from` | 否 | 当天往前29天 | 开始日期 |
| `--date-to` | 否 | 当天 | 结束日期 |
| `--domain` | 否 | 全部 | BI数据域，可重复传入 |
| `--pretty` | 否 | `false` | 格式化输出 JSON |

默认日期范围包含当天在内共30天。

### 4.3 数据域

| domain | 可获取数据 | 来源接口 |
| --- | --- | --- |
| `sales_traffic` | 销售、库存、广告、流量 | `/dataMetrics/v1/asin-report-files/sales-traffic-data` |
| `sp_search_term` | SP广告搜索词 | `/api/v1/sp-search-term/query` |
| `sqp` | Brand Analytics Search Query Performance | `/api/v1/brand-analytics-search-query/query` |
| `deals` | 活动数据 | `/dataMetrics/v1/asin-report-files/deals-data` |
| `turnover_inventory` | 物控版库存和周转 | `/dataMetrics/v1/asin-report-files/turnover-inventory-data` |

不传 `--domain` 时，新的 `bi` 命令查询以上全部数据域。

### 4.4 使用示例

查询默认最近30天全部 BI 数据：

```powershell
opscli asin-data bi --asin B086M58PQ3 --site US
```

指定日期范围：

```powershell
opscli asin-data bi `
  --asin B086M58PQ3 `
  --date-from 2026-07-01 `
  --date-to 2026-07-15
```

只查 SQP：

```powershell
opscli asin-data bi --asin B086M58PQ3 --domain sqp
```

查询多个数据域：

```powershell
opscli asin-data bi `
  --asin B086M58PQ3 `
  --domain sales_traffic `
  --domain sqp `
  --domain deals
```

### 4.5 SQP请求说明

`sqp` 使用 POST `/api/v1/brand-analytics-search-query/query`。多个 ASIN 会合并为一个逗号分隔的 `asins` 参数，并传入 `start_date` 和 `end_date`，减少远程请求次数。

### 4.6 返回结构

```json
{
  "success": true,
  "command": "asin-data bi",
  "data": {
    "status": "success",
    "asins": ["B086M58PQ3"],
    "site": "US",
    "source_count": 1,
    "row_count": 10,
    "sources": {
      "sqp": {
        "key": "sqp",
        "status": "success",
        "row_count": 10,
        "rows": []
      }
    },
    "date_from": "2026-07-01",
    "date_to": "2026-07-15",
    "domains": ["sqp"]
  },
  "error": null
}
```

## 5. 类目Top查询

### 5.1 命令格式

```text
opscli asin-data category-top --category CATEGORY [--site SITE]
                                [--date-from DATE] [--date-to DATE]
                                [--limit NUMBER] [--pretty]
```

### 5.2 参数

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--category` | 是 | - | 内部平台类目 `amazon_cat` 精确名称 |
| `--site` | 否 | `US` | Amazon站点代码 |
| `--date-from` | 否 | 当月1日 | 开始日期 |
| `--date-to` | 否 | 当天 | 结束日期 |
| `--limit` | 否 | `10` | 返回数量，范围1至100 |
| `--pretty` | 否 | `false` | 格式化输出 JSON |

### 5.3 数据范围与来源

只返回指定站点、类目和日期范围内的 `category_top` 排名数据，不查询刊登、爬虫或 BI 数据。

来源接口：

```text
/dataMetrics/v1/asin-report-files/internal-category-top10
```

### 5.4 使用示例

查询当月 Top 10：

```powershell
opscli asin-data category-top `
  --category "Bed Frames" `
  --site US
```

指定日期和数量：

```powershell
opscli asin-data category-top `
  --category "Bed Frames" `
  --site US `
  --date-from 2026-07-01 `
  --date-to 2026-07-15 `
  --limit 20
```

### 5.5 返回结构

```json
{
  "success": true,
  "command": "asin-data category-top",
  "data": {
    "category": "Bed Frames",
    "site": "US",
    "date_from": "2026-07-01",
    "date_to": "2026-07-15",
    "limit": 10,
    "row_count": 10,
    "category_top": []
  },
  "error": null
}
```

## 6. 状态与错误处理

顶层成功结构：

```json
{
  "success": true,
  "command": "asin-data basic",
  "data": {},
  "error": null
}
```

顶层失败结构：

```json
{
  "success": false,
  "command": "asin-data basic",
  "data": null,
  "error": {
    "code": "ASIN_DATA_ERROR",
    "message": "ASIN 格式无效"
  }
}
```

失败时 CLI 退出码为 `1`。

数据源状态可能为：

| 状态 | 含义 |
| --- | --- |
| `success` | 数据源查询成功 |
| `partial` | 部分 ASIN 或部分数据源失败 |
| `failed` | 数据源查询失败 |

常见错误：

- ASIN格式不是10位字母数字。
- 未传入 `--asin` 或 `--asins`。
- `--asins` 不是合法JSON数组。
- 站点不在支持范围内。
- 日期格式不正确、开始日期晚于结束日期或包含未来日期。
- `--source` 或 `--domain` 不在允许范围内。

## 7. 请求检测与日志

### 7.1 本地结构化日志

每次执行 `basic`、`bi`、`category-top` 都会写入：

```text
~/.config/opscli/asin-data/usage.jsonl
```

Windows默认路径：

```text
C:\Users\<用户名>\.config\opscli\asin-data\usage.jsonl
```

记录字段包括：

- UTC时间。
- 命令名称。
- 成功或失败状态。
- 执行耗时。
- 实际请求参数。
- 失败时的错误码和错误信息。

敏感字段如 JWT、Session ID、Authorization、Cookie、Password、Token、Secret、API Key 会替换为 `[REDACTED]`。

日志写入失败不会中断取数。

环境变量：

| 环境变量 | 作用 |
| --- | --- |
| `OPSCLI_ASIN_DATA_USAGE_LOG_DISABLED=1` | 关闭本地日志 |
| `OPSCLI_ASIN_DATA_USAGE_LOG_PATH` | 覆盖日志文件路径 |

### 7.2 中央遥测

opscli 全局遥测会异步上报命令路径、原始CLI参数、状态、耗时、用户和设备标识：

```text
{ops_url}/v1/cli/telemetry
```

遥测网络失败不会影响命令执行。

## 8. 兼容命令说明

旧 `live-data` 已从帮助页隐藏，只作为兼容入口保留。新脚本和 Skill 不应继续生成 `live-data --data-scope`，应改用：

| 旧需求 | 新命令 |
| --- | --- |
| 基础刊登和爬虫数据 | `opscli asin-data basic` |
| BI经营数据 | `opscli asin-data bi` |
| 内部类目Top数据 | `opscli asin-data category-top` |

`collect`、`stage-collect`、`merge-stages`、`daily-collect` 仍属于完整采集和流水线命令，不作为轻量取数服务的默认入口。

## 9. 命令帮助

```powershell
opscli asin-data --help
opscli asin-data basic --help
opscli asin-data bi --help
opscli asin-data category-top --help
```
