# ops-amazon (MCP 参考文档)

使用 MCP Tool `amazon_*` 抓取 Amazon 商品页快照、搜索结果页样本和预留给 ops API 的标准 payload。

**无状态模式**：服务器不保存用户凭证，所有认证信息（`session_id` / `jwt`）由调用方在 Tool 参数中传入。

---

## 认证门禁（MCP 无状态模式）

> **【强制】每次调用 `amazon_*` 前，必须先确认已提供有效 `session_id`；禁止跳过认证检查直接开始抓取。**

- 进入本 Skill 后，第一步先调用 `auth_is_authenticated(session_id)` 检测 session 有效性
- 若返回 `false` 或报错，说明 `session_id` 缺失或已过期
- **若 `session_id` 缺失**：
  1. 调用 `auth_login_start()` 获取 `verification_url` + `user_code`
  2. 提示用户在浏览器中打开 URL 并输入验证码
  3. 按 `interval` 轮询 `auth_login_poll(device_code)` 直到 `status=authorized`
  4. 获取返回的 `session_id`，保存到当前对话上下文
- **若 `session_id` 过期**：
  1. 调用 `auth_login_start()` 重新发起 Device Flow
  2. 重复上述授权流程
- 只有认证状态确认正常后，才允许继续执行 `amazon_scrape`、`amazon_payload`、`amazon_search`、`amazon_schema`、`amazon_history`

**标准前置流程（MCP Tool 调用）**：

```python
# 1. 先检查 session 是否有效
auth_is_authenticated(session_id="xxx")

# 2. 如 session_id 缺失或过期，重新授权
auth_login_start()                     # 获取 device_code / user_code
auth_login_poll(device_code="xxx")     # 轮询直到 authorized，获取新 session_id

# 3. 登录后再次确认
auth_is_authenticated(session_id="新session_id")
```

---

## 使用原则

- 本 Skill 只负责指导 AI 使用 MCP Tool 完成抓取、取样和字段确认
- 抓取动作统一通过 MCP Tool 执行，禁止在 Skill 内直接调用 Amazon HTTP 接口
- 当前阶段以"先抓数据、API 预留"为主，不要求直接提交到 ops API
- 若目标是后端设计，优先使用 `scrape`、`payload`、`search`、`schema` 四个 Tool 取样
- 搜索结果页的 `review_count_value` 应视为近似值；商品页 `scrape` 的评论数更适合作为精确快照值
- 所有 Amazon 工作流在执行前都必须先完成一次 `session_id` 检测与授权

---

## 前置要求

首次使用前请确认本地已安装 Amazon 抓取依赖：

```bash
pip install "aukeys-opscli[amazon]"
playwright install chromium
```

如果是源码开发环境：

```bash
pip install -e ".[amazon]"
playwright install chromium
```

---

## 何时使用

以下场景建议使用 `ops-amazon`：

- 需要抓取某个 Amazon 商品的价格、评分、评论数、配送位置
- 需要抓取关键词搜索结果做竞品样本分析
- 需要输出未来提交给 ops API 的标准 payload
- 需要拿真实样本给后端做字段设计、表结构设计、接口设计
- 需要查看某个商品的本地历史抓取记录

---

## MCP Tool 调用参考

### `amazon_scrape`

抓取单个商品页。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asin` | string | 是 | Amazon ASIN 码 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |
| `zip_code` | string | 否 | 美国邮编（影响配送位置） |
| `include_raw` | boolean | 否 | 包含原始 HTML 片段 |
| `no_save_history` | boolean | 否 | 不写入本地历史 |

**调用示例**：
```python
amazon_scrape(
    asin="B09LCJPZ1P",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

适用场景：

- 获取商品页精确快照
- 对比价格、评分、评论数变化
- 给后端确认商品快照字段结构

---

### `amazon_payload`

抓取商品页，并输出预留给 ops API 的标准请求体。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asin` | string | 是 | Amazon ASIN 码 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动换取 |
| `zip_code` | string | 否 | 美国邮编 |

**调用示例**：
```python
amazon_payload(
    asin="B09LCJPZ1P",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

适用场景：

- 设计商品快照提交接口
- 给后端确认最终 payload 契约

---

### `amazon_search`

抓取关键词搜索结果页。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 是 | 搜索关键词 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动换取 |
| `zip_code` | string | 否 | 美国邮编 |
| `limit` | integer | 否 | 最大抓取条数，默认 48 |

**调用示例**：
```python
amazon_search(
    keyword="usb c cable",
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

适用场景：

- 采集竞品结果集
- 设计搜索批次表和搜索结果表
- 验证关键词结果样本

---

### `amazon_schema`

输出当前字段契约。

**调用示例**：
```python
amazon_schema()
```

> 此 Tool 不需要认证。

适用场景：

- 对照字段类型
- 做 API 请求体验收
- 做数据库字段映射

---

### `amazon_history`

读取某个商品的本地历史抓取记录。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asin` | string | 是 | Amazon ASIN 码 |

**调用示例**：
```python
amazon_history(asin="B09LCJPZ1P")
```

> 此 Tool 只读取本地文件，不需要认证。

默认历史路径：

```text
~/.config/opscli/amazon/history/<ASIN>.jsonl
```

---

## MCP 认证工具速查

### 检查 session 有效性
```python
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: true}
```

### 获取 JWT（用于手动构造请求）
```python
auth_get_token(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: "eyJhbG..."}
```

### 检查 JWT 有效期
```python
auth_check_token(jwt="eyJhbG...")
# → {success: true, data: {valid: true, expires_in: 86399}}
```

### 刷新 JWT
```python
auth_token_refresh(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

## 推荐工作流

### 场景一：做商品快照字段设计

```python
# 0. 先检查 session；如无效则重新 Device Flow 授权
auth_is_authenticated(session_id="xxx")

# 1. 抓取商品页
amazon_scrape(
    asin="B09LCJPZ1P",
    session_id="860b0636485b5188a2b9b4ed5210e736",
    include_raw=True
)

# 2. 输出标准 payload
amazon_payload(
    asin="B09LCJPZ1P",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 3. 查看字段契约
amazon_schema()
```

### 场景二：做搜索结果表设计

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 抓取搜索结果
amazon_search(
    keyword="usb c cable",
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 2. 查看字段契约
amazon_schema()
```

### 场景三：查看历史变化

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 抓取当前快照
amazon_scrape(
    asin="B09LCJPZ1P",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 2. 读取历史记录
amazon_history(asin="B09LCJPZ1P")
```

---

## 字段口径提醒

- 商品页 `review_count_value`：优先视为精确值
- 搜索页 `review_count_value`：通常是页面展示缩写解析值，适合做近似分析
- `location`：当前已做零宽字符清洗
- `raw`：建议在字段调试和后端设计阶段保留输出

---

## 当前边界

本 Skill 一期不负责：

- 直接提交到 ops API
- 本地定时调度
- 多商品批量任务编排

这些能力后续应继续收口到 `opscli amazon` 模块本身，而不是在 Skill 侧分叉实现。

---

## 认证异常处理

| 场景 | 处理方式 |
|------|---------|
| session_id 缺失 | 调用 `auth_login_start()` → 浏览器授权 → `auth_login_poll()` 获取新 session_id |
| session_id 过期 | `auth_is_authenticated()` 返回 `false`，重新执行 Device Flow 授权 |
| JWT 过期 | `auth_token_refresh(session_id)` 自动刷新；如 session 也过期则重新授权 |
| 状态不确定 | 调用 `auth_doctor(session_id)` 诊断 session 有效性与系统连通性 |

---

## 本地配置文件

```text
~/.config/opscli/
├── config.ini         # 可选，覆盖服务地址（ops_url 等）
├── systems.json       # 用户自定义 + ops_sync 系统列表
└── amazon/history/    # 商品历史抓取记录
    └── <ASIN>.jsonl
```

**覆盖服务地址示例**（开发调试用）：

```ini
# ~/.config/opscli/config.ini
[systems]
ops_url = http://localhost/api
ops_system_url = http://ops.cm
ops_token_endpoint = /api/v1/auth/cli-token
polaris_system_url = http://po2.cm
polaris_token_endpoint = /api/auth/cli-token
```
