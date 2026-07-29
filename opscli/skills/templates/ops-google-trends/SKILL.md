---
name: ops-google-trends
description: 用于通过正式 `opscli google-trends` 命令查询 Google Trends 深度趋势、主题自动补全和当前热点，并导出查询结果。
---

# ops-google-trends

将用户的 Google Trends 需求映射为正式 `opscli google-trends ...` 命令。正式 CLI 通过本机 OPS 登录态调用远端 MCP；普通用户不需要接触第三方账号或凭证。

## 快速规则

1. 正式命令面只使用 `opscli google-trends ...`，不要暴露本地调试命令、内部任务目录或第三方凭证。
2. 当前只支持三个场景：`trends`、`autocomplete`、`trending-now`。
3. 已知分析对象时用 `trends`；需要实体消歧时先用 `autocomplete`；不知道查什么、需要发现热点时用 `trending-now`。
4. `--params` 必须是 JSON 对象字符串。
5. 正式 CLI 依赖本机 OPS 授权；未登录或登录过期时先执行 `opscli auth login`。
6. 若当前宿主直接调用远端 MCP，继续读取 [SKILL_MCP.md](SKILL_MCP.md)。

## 命令

### 查看场景

```powershell
opscli google-trends scenarios
```

### 执行场景

```powershell
opscli google-trends run <scenario> --geo US --params '<JSON对象>'
```

参数：

- `scenario`：`trends`、`autocomplete` 或 `trending-now`
- `--geo`：地区代码，默认 `US`
- `--params`：场景参数 JSON 对象
- `--job-id`：可选任务 ID
- `--export-format`：`xls`、`xlsx` 或 `json`
- `--hl`：可选语言区域
- `--tz`：可选时区分钟偏移，仅趋势分析使用

### 查询任务

```powershell
opscli google-trends job-status <job_id>
```

### 获取导出文件

```powershell
opscli google-trends export <job_id>
```

## 场景

### `trends`

用于时间趋势、地域热度、相关主题和相关查询。

主要参数：

- `q`：关键词、Topic ID，或最多 5 个元素的数组
- `data_type`：`TIMESERIES`、`GEO_MAP`、`GEO_MAP_0`、`RELATED_TOPICS`、`RELATED_QUERIES`
- `date`：如 `today 12-m`、`today 5-y`、`all`
- `geo`：地区代码
- `cat`：Google Trends 分类 ID
- `gprop`：`images`、`news`、`froogle`、`youtube`
- `region`：地域粒度，仅地域类型可用
- `include_low_search_volume`：是否包含低搜索量地区
- `no_cache`：是否跳过第三方缓存

示例：

```powershell
opscli google-trends run trends --geo US --params '{"q":"flashlight","data_type":"TIMESERIES","date":"today 12-m"}'
```

```powershell
opscli google-trends run trends --geo US --params '{"q":"flashlight","data_type":"RELATED_QUERIES"}'
```

### `autocomplete`

用于关键词自动补全、Google Topic ID 获取和同名实体消歧。

主要参数：`q`、`hl`、`no_cache`。

```powershell
opscli google-trends run autocomplete --params '{"q":"Apple","hl":"en"}'
```

### `trending-now`

用于发现指定地区当前热门搜索。

主要参数：

- `geo`：地区代码
- `hours`：`4`、`24`、`48`、`168`
- `category_id`：Trending Now 分类 ID
- `only_active`：只返回仍活跃的趋势
- `hl`、`no_cache`

```powershell
opscli google-trends run trending-now --geo US --params '{"hours":24,"only_active":true}'
```

## 典型工作流

### 已知关键词分析

1. 用 `trends + TIMESERIES` 判断长期变化和季节性。
2. 用 `trends + GEO_MAP_0` 判断高热度地区。
3. 用 `trends + RELATED_QUERIES` 扩展相关搜索词。

### 实体消歧

1. 用 `autocomplete` 获取候选 Topic。
2. 选择标题和类型匹配的 Topic ID。
3. 将 Topic ID 作为 `trends.q` 查询。

### 热点发现

1. 用 `trending-now` 获取当前热点。
2. 根据搜索量、增长比例和活跃状态筛选。
3. 将热点 query 传给 `trends` 查询时间趋势，区分短期事件与持续需求。

## 回复规则

- 成功时给出：场景、地区、查询对象、`job_id`、`row_count` 和导出链接。
- `row_count=0` 时明确说明无数据，并提醒检查地区、时间范围、关键词或 Topic。
- 不展示 API Key、Key 状态、套餐额度、第三方账号、服务器本地路径或原始请求文件。
- Trends 返回的是 Google Trends 相对热度，不应描述为绝对搜索量；Trending Now 响应中的 `search_volume` 除外。
