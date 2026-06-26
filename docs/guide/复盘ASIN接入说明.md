# 复盘 ASIN CLI 接入说明

> 本文档面向产品和 AI Skill 开发者，说明如何通过 `opscli asin-review fetch` 命令获取指定 ASIN 的复盘数据，并将其接入 Skill 或 AI Agent 工作流。

---

## 1. 命令概览

| 项目 | 说明 |
|------|------|
| 命令 | `opscli asin-review fetch` |
| 用途 | 从运营系统拉取指定 ASIN 在日期范围内的复盘数据（汇总指标 + 按日明细） |
| 后端接口 | `POST /v1/asin-review/query`（ops 系统） |
| 鉴权 | ops JWT（自动获取，无需手动传 token） |
| 输出格式 | JSON（终端 stdout） |

---

## 2. 命令参数

```bash
opscli asin-review fetch \
  --asin <ASIN> \
  --start-date <YYYY-MM-DD> \
  --end-date <YYYY-MM-DD> \
  [--pretty]
```

| 参数 | 必填 | 说明 | 示例 |
|------|:----:|------|------|
| `--asin` | 是 | Amazon ASIN（支持纯数字和标准 10 位字母数字） | `10043986503` |
| `--start-date` | 是 | 开始日期 | `2026-01-01` |
| `--end-date` | 是 | 结束日期 | `2026-01-31` |
| `--pretty` | 否 | 格式化 JSON 输出（便于人工阅读，Skill 调用无需加） | — |

---

## 3. 请求体（后端实际接收）

命令内部构造如下请求体发往运营系统，**Skill 无需关心此细节，仅供调试参考**：

```json
{
  "asin": "10043986503",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31"
}
```

---

## 4. 返回数据结构

### 4.1 整体结构

```json
{
  "success": true,
  "request": {
    "asins": ["10043986503"],
    "date_range": {"start": "2026-01-01", "end": "2026-01-31"}
  },
  "data": {
    "summary": { ... },
    "daily_data": [ ... ],
    "daily_rows": 11,
    "columns": [ ... ]
  },
  "warnings": [],
  "errors": []
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 是否成功取到数据 |
| `request` | object | 请求参数回显（ASIN + 日期范围） |
| `data.summary` | object | 周期汇总指标（见 4.2） |
| `data.daily_data` | array | 按日明细数据列表（见 4.3） |
| `data.daily_rows` | int | 按日明细行数 |
| `data.columns` | array | 按日明细的列名列表 |
| `warnings` | array | 警告信息（如缺少 summary 或 daily_data） |
| `errors` | array | 错误信息 |

### 4.2 summary 汇总指标

整个日期范围内的聚合数据：

```json
{
  "sessions": 0,
  "page_views": 0,
  "sessions_mobile_app": 0,
  "sessions_browser": 0,
  "page_views_mobile_app": 0,
  "page_views_browser": 0,
  "order_qty": 11,
  "orders": 11,
  "price": 7598.57,
  "advertising_fee": 0,
  "ads_conversions": 0,
  "ads_sales_cny": 0,
  "transfer_available_qty": 737,
  "platform_qty": 0,
  "star": 0,
  "reviews_qty": 0,
  "convert_percent": 0,
  "avg_price_cny": 690.78
}
```

| 字段 | 含义 | 单位 |
|------|------|------|
| `sessions` | 访问会话数 | 次 |
| `page_views` | 页面浏览量 | 次 |
| `sessions_mobile_app` | 移动端 APP 会话数 | 次 |
| `sessions_browser` | 浏览器会话数 | 次 |
| `page_views_mobile_app` | 移动端 APP 浏览量 | 次 |
| `page_views_browser` | 浏览器浏览量 | 次 |
| `order_qty` | 订单商品件数 | 件 |
| `orders` | 订单数 | 笔 |
| `price` | 销售额 | CNY |
| `advertising_fee` | 广告花费 | CNY |
| `ads_conversions` | 广告转化次数 | 次 |
| `ads_sales_cny` | 广告销售额 | CNY |
| `transfer_available_qty` | 可调拨库存 | 件 |
| `platform_qty` | 平台库存 | 件 |
| `star` | 商品星级 | 星 |
| `reviews_qty` | 评论数 | 条 |
| `convert_percent` | 转化率 | % |
| `avg_price_cny` | 平均客单价 | CNY |

### 4.3 daily_data 按日明细

每天一条记录，字段与 summary 一致，额外包含 `date_id` 和 `asin`：

```json
{
  "date_id": "2026-01-05",
  "asin": "10043986503",
  "sessions": 0,
  "page_views": 0,
  "order_qty": 3,
  "orders": 3,
  "price": 2164.03,
  "advertising_fee": 0,
  ...
}
```

> `daily_data` 仅包含有数据产生的日期，非连续日期（如周末无数据则不出现）。

---

## 5. 错误场景

### 5.1 参数错误

```json
{
  "success": false,
  "command": "asin-review fetch",
  "data": null,
  "error": {
    "code": "INVALID_PARAMS",
    "message": "ASIN 格式不合法：'xxx'（应为字母数字）"
  }
}
```

### 5.2 未登录 / 鉴权失败

```json
{
  "success": false,
  "command": "asin-review fetch",
  "data": null,
  "error": {
    "code": "REVIEW_HTTP_ERROR",
    "message": "远端请求失败，HTTP 401",
    "status_code": 401
  }
}
```

### 5.3 后端接口异常

```json
{
  "success": false,
  "command": "asin-review fetch",
  "data": null,
  "error": {
    "code": "REVIEW_BUSINESS_ERROR",
    "message": "ASIN 不存在",
    "business_code": 4001
  }
}
```

---

## 6. Skill 接入方式

### 6.1 CLI 模式（推荐）

Skill 脚本通过 `subprocess` 调用命令，解析 stdout JSON：

```python
import subprocess
import json

result = subprocess.run(
    [
        "opscli", "asin-review", "fetch",
        "--asin", "10043986503",
        "--start-date", "2026-01-01",
        "--end-date", "2026-01-31",
    ],
    capture_output=True,
    text=True,
)
data = json.loads(result.stdout)

if data["success"]:
    summary = data["data"]["summary"]
    daily = data["data"]["daily_data"]
    # 用数据生成复盘报告...
else:
    error = data["error"]
    # 处理错误...
```

**注意事项**：
- 调用前需确保用户已执行 `opscli auth login` 登录
- ASIN 和日期从用户输入中提取，缺失时追问
- 日期范围可默认取最近 30 天

### 6.2 MCP Tool 模式

MCP Tool `asin_review_fetch` 已注册，AI Agent 可直接调用：

```
工具名：asin_review_fetch
参数：
  asin (str, 必填)          — Amazon ASIN
  start_date (str, 必填)     — 开始日期 YYYY-MM-DD
  end_date (str, 必填)       — 结束日期 YYYY-MM-DD
  jwt (str, 可选)            — 外部 JWT（通常不需要传）
  session_id (str, 可选)      — 外部 session_id（通常不需要传）
```

返回结构与 CLI 一致（包裹在 `{"success": true, "data": {...}}` 中）。

### 6.3 典型 Skill 触发条件建议

在 Skill 的 `description` 中声明以下触发词，AI 即可在用户对话时自动触发：

```
当用户说"复盘ASIN"、"ASIN复盘"、"分析ASIN表现"、"查一下ASIN数据"时触发
```

Skill 文档中应引导 AI 的执行流程：

1. 从用户输入提取 ASIN 和日期范围（缺失日期时默认最近 30 天）
2. 调用 `opscli asin-review fetch` 获取数据
3. 基于 `data.summary` 和 `data.daily_data` 生成复盘报告

---

## 7. 完整调用示例

```bash
# 基本调用
opscli asin-review fetch --asin 10043986503 --start-date 2026-01-01 --end-date 2026-01-31

# 格式化输出（人工查看用）
opscli asin-review fetch --asin 10043986503 --start-date 2026-01-01 --end-date 2026-01-31 --pretty
```
