---
name: ops-google-trends
description: Use when the user asks to query or export Google Trends data through the public `opscli google-trends` CLI or the remote Google Trends MCP flow, especially interest over time, interest by region, related queries, or keyword suggestions.
---

# ops-google-trends

用于把 Google Trends 自然语言需求映射成正式 `opscli google-trends ...` 命令，并沿着“本地 CLI -> 远端 MCP 配置 -> 远端 `google_trends_*` tool”这条公开链路完成查询和导出。

当前对用户公开的正式 CLI 入口是 `opscli google-trends ...`。
正式 CLI 依赖本机已完成 OPS 授权；若本机未登录或登录态过期，先完成 `opscli auth login` 再继续。

## 快速规则

1. 正式命令面默认只讲 `opscli google-trends ...`，不要向用户暴露内部调试命令或本地直连调试链路。
2. 默认 `geo=US`；如果用户要全球趋势，显式传空字符串 `--geo ""`。
3. `interest-over-time`、`interest-by-region`、`related-queries` 单次最多 5 个关键词。
4. 默认导出 `xls`，实际生成 `.xlsx`；如果用户明确要原始 JSON，可以用 `--export-format json`。
5. `related-topics`、`trending-searches`、`realtime-trending` 当前属于已知不可用场景，不要继续推荐成默认方案。
6. 不向用户暴露 `params.json`、`raw.json`、pytrends 内部错误栈、服务器本地导出路径。
7. 如果当前宿主是远端 MCP 直连而不是 CLI 代理，继续看 [SKILL_MCP.md](SKILL_MCP.md)。

## 正式链路

- 本地 CLI 代理链路：`opscli google-trends ...`
- 远端 MCP tools：`google_trends_scenarios`、`google_trends_run`、`google_trends_job_status`、`google_trends_export`
- 常见前置：确认本机 `opscli auth login` 已完成且登录态仍有效

## 命令面

1. 查看场景

```powershell
opscli google-trends scenarios
```

2. 执行场景

```powershell
opscli google-trends run interest-over-time --geo US --params '{"keyword":"flashlight","timeframe":"today 12-m"}'
```

可用参数：

- `scenario`：场景 ID，如 `interest-over-time`
- `--geo`：地区代码，默认 `US`；传空字符串表示全球
- `--params`：JSON 对象字符串
- `--job-id`：自定义任务 ID
- `--export-format`：`xls` / `xlsx` / `json`
- `--hl`：语言区域，如 `en-US`
- `--tz`：时区分钟偏移，如 `360`

3. 查任务结果

```powershell
opscli google-trends job-status <job_id>
```

4. 查导出文件

```powershell
opscli google-trends export <job_id>
```

## 最小工作流

1. 判断是趋势时间序列、地区热度、相关搜索词还是建议词
2. 缺参数时只补关键词、时间范围、地区这类当前必需项
3. 组织 `scenario + geo + params`，执行 `opscli google-trends run ...`
4. 用户只要结果文件或续查任务时，再走 `job-status` / `export`

## 场景速查

| 用户意图 | scenario | 必填参数 | 常用可选参数 |
| --- | --- | --- | --- |
| 关键词趋势时间序列 | `interest-over-time` | `keyword/keywords/kw_list` | `timeframe`, `geo`, `cat`, `gprop` |
| 关键词地区热度 | `interest-by-region` | `keyword` | `resolution`, `inc_low_vol`, `inc_geo_code`, `geo` |
| 相关搜索词 | `related-queries` | `keyword` | `timeframe`, `geo`, `cat`, `gprop` |
| 关键词建议 | `suggestions` | `keyword` | 无 |
| 相关主题 | `related-topics` | `keyword` | 当前已知不可用 |
| 每日热搜 | `trending-searches` | 无 | 当前已知不可用 |
| 实时热搜 | `realtime-trending` | 无 | 当前已知不可用 |

## 参数提示

- `gprop` 支持：`""`、`images`、`news`、`youtube`、`froogle`
- 用户说 `shopping` 时，映射为 `froogle`
- `interest-by-region` 常见 `resolution`：`COUNTRY`、`REGION`、`CITY`

## 常用示例

趋势时间序列：

```powershell
opscli google-trends run interest-over-time --geo US --params '{"keyword":"flashlight","timeframe":"today 12-m"}'
```

多关键词对比：

```powershell
opscli google-trends run interest-over-time --geo US --params '{"keywords":["flashlight","headlamp"],"timeframe":"today 3-m"}'
```

地区热度：

```powershell
opscli google-trends run interest-by-region --geo US --params '{"keyword":"flashlight","resolution":"REGION"}'
```

相关搜索词：

```powershell
opscli google-trends run related-queries --geo US --params '{"keyword":"flashlight","timeframe":"today 12-m"}'
```

关键词建议：

```powershell
opscli google-trends run suggestions --params '{"keyword":"flashlight"}'
```

## 回复规则

- 成功时只保留：场景、地区、关键词、时间范围或拆分口径、`job_id`、`row_count`、导出文件
- 如果用户问今日热搜/实时热搜，直接说明 Google Trends 热搜端点当前不可用，并建议改查关键词趋势、地区热度或相关搜索词
- `row_count=0` 时提醒用户扩大时间范围、换更宽泛关键词或调整地区
- 不要主动解释 pytrends 内部实现、服务端调试路径或原始响应结构
