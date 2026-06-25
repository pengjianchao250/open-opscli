# 复盘 ASIN 模块技术设计

> 版本：v0.1-draft
> 日期：2026-06-23
> 状态：待运营系统数据集对接确认

---

## 1. 背景与目标

### 1.1 业务背景

运营团队需要定期对指定 ASIN 进行"复盘"，即从运营系统仪表盘中提取多维度业务数据（销量、广告、库存、退款等），形成结构化的复盘报告。当前这一过程依赖人工登录运营系统、逐个仪表盘截图/导出数据，效率低且容易遗漏指标。

### 1.2 目标

- 提供 CLI 命令入口 `opscli asin-review`，AI Agent 可通过 MCP Tool 或 CLI 调用
- 输入 ASIN + 日期范围，自动从运营系统拉取多个仪表盘的数据集
- 输出结构化 JSON 结果（可直接被 AI 消费生成复盘报告）
- 可选 Excel 导出，供人工查阅

### 1.3 非目标

- 不负责"生成复盘报告文本"——这是 AI Agent 的职责，本模块只负责取数
- 不负责"健康度评分/诊断"——已有 `ops-asin-health-diagnoser` 承担
- 不设计具体数据集和字段的业务含义——待运营系统侧确认

---

## 2. 整体架构

### 2.1 定位

```
AI Agent
  |
  +-- MCP Tool: asin_review_fetch  (或直接 CLI 调用)
       |
       v
  opscli asin-review fetch --asin B08XXX --date-range 2025-01-01~2025-01-31
       |
       v
  opscli/asin_review/  (新模块)
       |
       +-- QueryClient  (复用 opscli.query.transport.client)
       +-- AuthClient   (复用 opscli.auth)
       +-- CredentialStore (复用 opscli.auth.storage)
       |
       v
  运营系统 API (ops)
       |
       +-- 数据集 A: 销量指标
       +-- 数据集 B: 广告指标
       +-- 数据集 C: 库存指标
       +-- ... (待运营系统确认)
```

### 2.2 与现有模块的关系

| 模块 | 关系 |
|------|------|
| `opscli.query` | **依赖**。复用 `QueryClient` 发起 HTTP 请求，复用 `QueryManager` 的 `build_simple_and_run` 执行查询 |
| `opscli.auth` | **依赖**。复用 `AuthClient` 获取 JWT 进行鉴权 |
| `opscli.mcp` | **可选暴露**。注册 MCP Tool `asin_review_fetch`，供 AI Agent 直接调用 |
| `ops-asin-health-diagnoser` | **并列**。健康诊断侧重评分和行动建议，复盘侧重原始数据拉取 |
| `ops-cli-view-data` | **参考**。数据拉取 + Excel 导出的模式可参考 |
| `ops-cli-view-runner` | **参考**。参数校验 + 视图运行的模式可参考 |

---

## 3. 模块结构

```
opscli/
├── asin_review/                    # 新模块
│   ├── __init__.py                  # 导出 AsinReviewClient
│   ├── cli.py                       # 兼容导出 → commands/cli.py
│   ├── client.py                    # 兼容导出 → transport/client.py
│   ├── models.py                    # 兼容导出 → domain/models.py
│   ├── exceptions.py                # 兼容导出 → domain/exceptions.py
│   ├── commands/
│   │   ├── __init__.py
│   │   └── cli.py                   # Typer CLI 子命令
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py                # 数据模型
│   │   └── exceptions.py           # 异常类
│   ├── services/
│   │   ├── __init__.py
│   │   └── manager.py               # 业务编排（核心）
│   ├── transport/
│   │   ├── __init__.py
│   │   └── client.py                # 运营系统 API 客户端
│   └── config.py                    # 复盘仪表盘配置（数据集映射）
```

### 3.1 遵循的现有规范

- **分层架构**：与 `query` 模块一致，`commands/` + `services/` + `transport/` + `domain/`
- **兼容导出层**：顶层 `__init__.py`、`cli.py`、`client.py`、`models.py` 做兼容导出
- **无状态支持**：构造函数接受可选 `jwt`/`session_id`，支持 MCP 远程调用
- **凭证统一**：复用 `CredentialStore`，不引入独立存储

---

## 4. CLI 命令设计

### 4.1 命令树

```
opscli asin-review
    fetch --asin <ASIN> --date-start <date> --date-end <date> [--dashboards <list>] [--output <path>] [--format json|excel]
    dashboards                       # 列出所有可用的复盘仪表盘/数据集
```

### 4.2 命令详情

#### `opscli asin-review fetch`

拉取指定 ASIN 在日期范围内的复盘数据。

| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--asin` | 是 | Amazon ASIN，支持逗号分隔多个 |
| `--date-start` | 是 | 开始日期，格式 `YYYY-MM-DD` |
| `--date-end` | 是 | 结束日期，格式 `YYYY-MM-DD` |
| `--dashboards` | 否 | 指定拉取的仪表盘列表（默认全部）。如 `--dashboards sales,ads,inventory` |
| `--output` | 否 | 输出路径（JSON 文件或 Excel 文件） |
| `--format` | 否 | 输出格式：`json`（默认）或 `excel` |
| `--pretty` | 否 | 格式化 JSON 输出 |
| `--jwt` | 否 | 外部传入 JWT（MCP 模式使用） |
| `--session-id` | 否 | 外部传入 session_id（MCP 模式使用） |

**输出示例（JSON）**：

```json
{
  "success": true,
  "request": {
    "asin": ["B08XXXXXX"],
    "date_range": {"start": "2025-01-01", "end": "2025-01-31"},
    "dashboards": ["sales", "ads", "inventory"]
  },
  "data": {
    "sales": {
      "status": "ok",
      "dataset_alias": "asin_sales_daily",
      "rows": 31,
      "columns": ["date", "orders", "revenue", "units"],
      "result": [
        {"date": "2025-01-01", "orders": 15, "revenue": 234.56, "units": 18},
        {"date": "2025-01-02", "orders": 12, "revenue": 189.30, "units": 14}
      ]
    },
    "ads": {
      "status": "ok",
      "dataset_alias": "asin_ads_daily",
      "rows": 31,
      "columns": ["date", "spend", "impressions", "clicks", "acos"],
      "result": [...]
    },
    "inventory": {
      "status": "ok",
      "dataset_alias": "asin_inventory_snapshot",
      "rows": 1,
      "columns": ["snapshot_date", "fba_stock", "fbm_stock", "days_of_supply"],
      "result": [...]
    }
  },
  "warnings": [],
  "errors": []
}
```

**错误场景**：

```json
{
  "success": false,
  "request": {...},
  "data": {
    "sales": {"status": "ok", ...},
    "ads": {"status": "error", "error": "DATASET_NOT_FOUND", "message": "数据集 ads_daily 未找到"}
  },
  "warnings": ["inventory 数据集返回空结果"],
  "errors": ["ads 数据集拉取失败"]
}
```

#### `opscli asin-review dashboards`

列出当前可用的复盘仪表盘/数据集清单，供 AI Agent 或用户确认有哪些维度可查。

| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--jwt` | 否 | 外部传入 JWT |
| `--session-id` | 否 | 外部传入 session_id |

**输出示例**：

```json
{
  "success": true,
  "dashboards": [
    {
      "key": "sales",
      "name": "销量指标",
      "description": "按日期聚合的订单数、销售额、件数",
      "dataset_alias": "asin_sales_daily",
      "required_fields": ["asin", "date"],
      "available_dimensions": ["date", "asin", "marketplace"],
      "available_metrics": ["orders", "revenue", "units", "avg_price"]
    },
    {
      "key": "ads",
      "name": "广告指标",
      "description": "按日期聚合的广告花费、曝光、点击、ACOS",
      "dataset_alias": "asin_ads_daily",
      "required_fields": ["asin", "date"],
      "available_dimensions": ["date", "asin", "campaign_type"],
      "available_metrics": ["spend", "impressions", "clicks", "acos", "cpc"]
    }
  ]
}
```

---

## 5. MCP Tool 设计

### 5.1 工具注册

在 `opscli/mcp/tools/` 下新增 `asin_review.py`，遵循现有 `_ALL_TOOLS` + `register(mcp)` 模式。

### 5.2 暴露的 Tool

#### `asin_review_fetch`

```python
async def asin_review_fetch(
    asin: str,                    # Amazon ASIN，逗号分隔支持多个
    date_start: str,              # 开始日期 YYYY-MM-DD
    date_end: str,                # 结束日期 YYYY-MM-DD
    dashboards: str | None = None, # 逗号分隔的仪表盘 key 列表，默认全部
    output_format: str = "json",  # json 或 excel
    jwt: str | None = None,       # 可选外部 JWT
    session_id: str | None = None # 可选外部 session_id
) -> dict
```

返回值与 CLI `fetch` 命令的 JSON 输出一致。

#### `asin_review_dashboards`

```python
async def asin_review_dashboards(
    jwt: str | None = None,
    session_id: str | None = None
) -> dict
```

返回值与 CLI `dashboards` 命令一致。

---

## 6. 仪表盘配置（待运营系统确认）

### 6.1 配置文件结构

复盘的核心是"ASIN + 日期范围 → 多个数据集查询"。每个仪表盘对应一个运营系统数据集（`dataset_alias` + `table_id`），以及固定的查询维度和指标。

配置存储在 `opscli/asin_review/config.py`：

```python
# 复盘仪表盘注册表
# 每个 key 对应一个仪表盘，映射到运营系统的一个数据集查询
REVIEW_DASHBOARDS: dict[str, DashboardConfig] = {
    "sales": DashboardConfig(
        key="sales",
        name="销量指标",
        description="按日期聚合的订单数、销售额、件数",
        dataset_alias="asin_sales_daily",     # 待运营系统确认
        table_id="ds_xxxxx_sales",            # 待运营系统确认
        dimensions=["date"],                  # 固定查询维度
        metrics=["orders", "revenue", "units"], # 固定查询指标
        filters=[                              # 固定过滤条件模板
            {"field": "asin", "operator": "in", "value": "{asins}"},
            {"field": "date", "operator": "between", "value": "{date_range}"},
        ],
    ),
    "ads": DashboardConfig(
        key="ads",
        name="广告指标",
        description="按日期聚合的广告花费、曝光、点击、ACOS",
        dataset_alias="asin_ads_daily",        # 待运营系统确认
        table_id="ds_xxxxx_ads",               # 待运营系统确认
        dimensions=["date"],
        metrics=["spend", "impressions", "clicks", "acos"],
        filters=[
            {"field": "asin", "operator": "in", "value": "{asins}"},
            {"field": "date", "operator": "between", "value": "{date_range}"},
        ],
    ),
    # ... 更多仪表盘待运营系统确认后补充
}
```

### 6.2 需要运营系统确认的信息

| # | 确认项 | 说明 |
|---|--------|------|
| 1 | 复盘需要哪些仪表盘维度 | 例如：销量、广告、库存、退款、星级、流量来源等 |
| 2 | 每个仪表盘对应的数据集 `dataset_alias` 和 `table_id` | 需从运营系统 BI 模块获取 |
| 3 | 每个数据集可供查询的维度（dimensions）字段 | 例如 `date`、`asin`、`marketplace` |
| 4 | 每个数据集可供查询的指标（metrics）字段 | 例如 `orders`、`revenue`、`spend` |
| 5 | 过滤条件的字段名和操作符 | ASIN 过滤用什么字段名（`asin` / `asin_code` / `parent_asin`） |
| 6 | 是否有现成的"复盘仪表盘"图表 UUID | 若有，可直接复用 `ops-cli-view-data` 的 chart 查询模式，无需自行组装 payload |
| 7 | 是否需要支持按 `parent_asin` 聚合 | 变体场景下，是否需要自动展开子 ASIN 查询 |

---

## 7. 核心类设计

### 7.1 `domain/models.py`

```python
@dataclass(frozen=True)
class DashboardConfig:
    """单个复盘仪表盘的查询配置"""
    key: str                          # 仪表盘唯一标识，如 "sales"
    name: str                        # 中文显示名，如 "销量指标"
    description: str                 # 仪表盘描述
    dataset_alias: str               # 运营系统数据集别名
    table_id: str                    # 运营系统数据集 table_id
    dimensions: list[str]            # 查询维度（固定）
    metrics: list[str]               # 查询指标（固定）
    filters: list[dict]             # 过滤条件模板（含占位符）


@dataclass
class ReviewRequest:
    """复盘查询请求"""
    asins: list[str]                 # 一个或多个 ASIN
    date_start: str                  # 开始日期
    date_end: str                    # 结束日期
    dashboard_keys: list[str] | None # 指定仪表盘，None 表示全部


@dataclass
class DashboardResult:
    """单个仪表盘的查询结果"""
    key: str                         # 仪表盘 key
    status: str                     # "ok" / "error" / "empty"
    dataset_alias: str
    rows: int
    columns: list[str]
    result: list[dict] | None
    error: str | None = None


@dataclass
class ReviewResult:
    """完整的复盘查询结果"""
    success: bool
    request: dict                    # ReviewRequest.to_dict()
    data: dict[str, DashboardResult] # key -> DashboardResult
    warnings: list[str]
    errors: list[str]
```

### 7.2 `services/manager.py`

```python
class AsinReviewManager:
    """复盘业务编排层"""

    def __init__(self, auth_client=None, jwt=None, session_id=None)

    def dashboards(self) -> dict:
        """列出所有可用的复盘仪表盘配置"""

    def fetch(self, request: ReviewRequest) -> ReviewResult:
        """
        核心方法：拉取复盘数据
        1. 参数校验（ASIN 格式、日期范围合法性）
        2. 解析请求，确定需要查询的仪表盘列表
        3. 逐个仪表盘构建查询 payload 并执行
        4. 汇总结果，处理部分失败场景
        """
```

### 7.3 `transport/client.py`

```python
class AsinReviewClient:
    """
    运营系统 HTTP 客户端
    内部复用 QueryClient，不直接发 HTTP 请求（铁律11）
    """

    def __init__(self, query_client: QueryClient)

    def query_dashboard(self, config: DashboardConfig, asins: list[str],
                        date_start: str, date_end: str) -> dict:
        """查询单个仪表盘数据，内部调用 query_client.build_simple_and_run"""
```

---

## 8. 数据流

```
用户/AI: opscli asin-review fetch --asin B08XXX --date-start 2025-01-01 --date-end 2025-01-31
    |
    v
commands/cli.py: 解析参数 → 构造 ReviewRequest
    |
    v
services/manager.py: AsinReviewManager.fetch()
    |
    +-- 1. 校验参数（ASIN 格式、日期范围）
    +-- 2. 从 config.py 加载仪表盘配置
    +-- 3. 对每个仪表盘:
    |       |
    |       v
    |   transport/client.py: AsinReviewClient.query_dashboard()
    |       |
    |       v
    |   opscli.query.transport.client.QueryClient.build_simple_and_run()
    |       |
    |       v
    |   运营系统 API → 数据集查询结果
    |       |
    |       v
    |   DashboardResult(status="ok", result=[...])
    |
    +-- 4. 汇总所有 DashboardResult → ReviewResult
    |
    v
输出 JSON / Excel
```

---

## 9. 与运营系统对接方案

### 9.1 前置条件

运营系统需提供以下信息：

1. **数据集 Catalog**：通过 `opscli query metadata --dataset <alias>` 可查到字段列表
2. **数据集查询权限**：当前登录用户的 JWT 需要有对应数据集的查询权限
3. **查询 API**：复用现有 `POST /v1/data-metrics/cli-query/simple` 端点，无需新增接口

### 9.2 对接步骤

1. **运营系统侧**：确认复盘涉及的数据集和字段（见 6.2 节确认清单）
2. **opscli 侧**：根据确认结果填写 `config.py` 中的 `REVIEW_DASHBOARDS` 配置
3. **联调**：使用 `opscli asin-review dashboards` 确认配置正确，使用 `opscli asin-review fetch` 验证数据拉取
4. **可选**：如果运营系统有现成的"复盘仪表盘"图表 UUID，可直接走 `ops-cli-view-data` 的 chart 查询路径，简化 payload 组装

### 9.3 降级策略

- 若某个数据集不存在或无权限，该仪表盘标记为 `status: "error"`，不影响其他仪表盘
- 若返回空结果，标记为 `status: "empty"`，AI Agent 可据此提示"该维度暂无数据"
- 所有错误汇总在 `errors` 列表，部分失败不影响整体 `success: true`（有至少一个仪表盘成功即视为成功）

---

## 10. Skill 集成

### 10.1 是否需要独立 Skill

当前设计倾向于**不创建独立 Skill**，原因：

- 复盘取数是一个明确的 CLI 命令，通过 `opscli asin-review fetch` 即可完成
- MCP Tool `asin_review_fetch` 已足够让 AI Agent 调用
- 如果需要更复杂的编排逻辑（如"自动选择仪表盘"、"多轮参数确认"），可在后续考虑封装为 `ops-asin-review` Skill

### 10.2 后续 Skill 化路径（可选）

如果复盘流程需要更丰富的 AI 交互（如参数引导、数据解读建议），可创建 `ops-asin-review` Skill：

```
opscli/skills/templates/ops-asin-review/
├── data/VERSION.json
├── SKILL.md
├── scripts/
│   └── fetch.py              # 封装 opscli asin-review fetch
└── references/
    ├── cli.md                # CLI 调用参考
    └── mcp.md                # MCP Tool 调用参考
```

---

## 11. 实现计划

### 阶段一：骨架搭建（不依赖运营系统数据集）

1. 创建 `opscli/asin_review/` 模块目录和分层结构
2. 实现 `domain/models.py` 数据模型
3. 实现 `domain/exceptions.py` 异常类
4. 实现 `config.py` 仪表盘配置（先用占位数据集）
5. 实现 `commands/cli.py` CLI 入口
6. 在 `opscli/cli.py` 注册新模块
7. 实现单元测试骨架

### 阶段二：核心取数逻辑

1. 实现 `transport/client.py`（复用 QueryClient）
2. 实现 `services/manager.py` 核心编排
3. 实现 MCP Tool 注册（`opscli/mcp/tools/asin_review.py`）
4. 集成测试（mock 运营系统响应）

### 阶段三：运营系统对接

1. 运营系统确认数据集和字段
2. 填写 `config.py` 真实配置
3. 联调验证
4. 可选：Excel 导出功能
5. 可选：Skill 化封装

---

## 12. 待确认事项

| # | 问题 | 确认方 |
|---|------|--------|
| 1 | 复盘具体需要哪些仪表盘维度？ | 运营系统 / 业务方 |
| 2 | 每个维度的数据集 `dataset_alias` 和 `table_id`？ | 运营系统 |
| 3 | 是否有现成的"复盘仪表盘"图表 UUID？ | 运营系统 |
| 4 | 是否需要支持 `parent_asin` 自动展开变体？ | 业务方 |
| 5 | 是否需要 Excel 导出？ | 业务方 |
| 6 | 是否需要独立 Skill 还是 MCP Tool 足够？ | 业务方 |
| 7 | 复盘数据的时间粒度（日 / 周 / 月）？ | 业务方 |

---

## 13. 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 运营系统数据集尚未确定 | 无法完成 `config.py` | 先用占位符，阶段三对接时填充 |
| 部分数据集无权限 | 复盘数据不完整 | 降级策略，标记 error 不中断 |
| 查询超时（大量 ASIN + 长时间范围） | 用户体验差 | 增加超时控制 + 分页/分批查询 |
| 数据集 schema 变更 | 查询失败 | `dashboards` 命令可实时检测可用性 |
