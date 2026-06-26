# Google Trends MCP 使用规范

## 适用场景

使用 `google_trends_*` 工具获取 Google Trends 公开趋势数据。底层依赖非官方 `pytrends`，适合小批量取数和运营分析前置探索，不适合高频批量抓取。

## 必读规则

1. 执行前先调用 `google_trends_spec_must_read` 读取本规范。
2. 默认 `geo=US`；如果需要全球趋势，显式传 `geo=""`。
3. `interest-over-time`、`interest-by-region`、`related-queries`、`related-topics` 单次最多 5 个关键词。
4. 默认导出 `xls`，实际生成 `.xlsx`；如需原始 JSON，传 `export_format="json"`。
5. 不要向用户暴露 `params.json`、`raw.json` 等内部路径；MCP 返回已隐藏内部参数和原始响应。
6. Google Trends 可能限流或临时变更接口，遇到 429/限流提示时稍后重试。
7. `trending-searches`、`realtime-trending` 和 `related-topics` 当前已知不可用。用户询问“今日热搜/每日热搜/实时热搜”时，不要继续尝试热搜场景，也不要把实时热搜作为每日热搜的回退；应说明该热搜端点失效，或改为关键词类趋势分析。

## 场景与参数

- `interest-over-time`：关键词趋势时间序列。
  - 参数：`keyword` / `keywords` / `kw_list`、`timeframe`、`geo`、`cat`、`gprop`
  - 示例：`{"keyword":"flashlight","timeframe":"today 12-m"}`
- `interest-by-region`：关键词地区热度。
  - 参数：`keyword`、`geo`、`resolution`、`inc_low_vol`、`inc_geo_code`
  - 示例：`{"keyword":"flashlight","resolution":"REGION"}`
- `related-queries`：相关查询 top/rising。
  - 参数：`keyword`、`geo`、`timeframe`
- `related-topics`：相关主题 top/rising。
  - 状态：已知不可用；2026-06-09 自测多个关键词均在 pytrends 内部触发 `list index out of range`。
  - 参数：`keyword`、`geo`、`timeframe`，当前不要调用。
- `suggestions`：单关键词主题建议。
  - 参数：`keyword`
- `trending-searches`：每日热搜。
  - 状态：已知不可用；pytrends daily/hottrends 端点当前返回 404。
  - 参数：`pn`，历史支持 `US` 或 `united_states`，当前不要调用。
- `realtime-trending`：实时热搜。
  - 状态：已知不可用；pytrends realtime 端点当前返回 404。
  - 参数：`pn`，历史支持 `US`，当前不要调用。

## gprop

支持：`""`、`images`、`news`、`youtube`、`froogle`。用户输入 `shopping` 会自动映射为 `froogle`。

## 推荐调用

1. `google_trends_scenarios()` 查看可用场景。
2. `google_trends_run(scenario="interest-over-time", geo="US", params={"keyword":"flashlight","timeframe":"today 12-m"})`。
3. 使用返回的 `job_id` 调用 `google_trends_job_status(job_id)` 或 `google_trends_export(job_id)`。

## 用户回答规范

回答要站在业务用户视角，不解释 pytrends、内部端点、认证、内部请求参数、原始 JSON 结构。

成功时固定包含：查询已完成、场景、地区、查询对象、时间范围或拆分口径、返回行数、导出文件。导出文件优先 `export.url`，没有再用 `export.path`。

成功时不要包含：`params.json`、`raw.json`、`result.json`、内部 task directory、原始响应结构、完整内部参数。只有用户明确要求后端排障或原始 JSON 时，才说明可用原始结果文件做比对。

成功通用模板：

```text
已完成 Google Trends <场景> 查询并导出结果。

地区：<geo 或 全球>
查询对象：<keyword / keywords>
时间范围/口径：<timeframe / resolution / suggestions>
返回行数：<row_count>
导出文件：<export.url 或 export.path>
```

各场景回答模板：

| 场景 | 用户回复 |
| --- | --- |
| `interest-over-time` | `已完成 Google Trends 关键词趋势查询。\n\n地区：<geo 或 全球>\n关键词：<keyword / keywords>\n时间范围：<timeframe>\n返回行数：<row_count>\n导出文件：<export.url 或 export.path>` |
| `interest-by-region` | `已完成 Google Trends 地区热度查询。\n\n地区：<geo 或 全球>\n关键词：<keyword>\n拆分口径：<resolution>\n返回行数：<row_count>\n导出文件：<export.url 或 export.path>` |
| `related-queries` | `已完成 Google Trends 相关搜索词查询。\n\n地区：<geo 或 全球>\n关键词：<keyword>\n时间范围：<timeframe>\n返回行数：<row_count>\n导出文件：<export.url 或 export.path>` |
| `suggestions` | `已完成 Google Trends 关键词建议查询。\n\n关键词：<keyword>\n返回行数：<row_count>\n导出文件：<export.url 或 export.path>` |

异常和空结果模板：

| 场景 | 用户回复 |
| --- | --- |
| 返回行数为 0 | `已完成查询，但没有返回匹配结果。\n\n地区：<geo 或 全球>\n查询对象：<keyword / keywords>\n建议：可以换一个更宽泛的关键词，或扩大时间范围和地区。` |
| 用户询问今日热搜/每日热搜/实时热搜 | `Google Trends 热搜端点当前不可用，暂时无法查询今日/实时热搜。\n\n可以改查某个关键词的趋势、地区热度或相关搜索词。` |
| 调用已知不可用场景 | `该 Google Trends 场景当前不可用：<scenario>。\n\n可用场景：关键词趋势、地区热度、相关搜索词、关键词建议。` |
| Google Trends 限流/429 | `Google Trends 当前触发限流，请稍后重试。` |
| Google Trends 400/404/服务异常 | `Google Trends 服务或接口暂时不可用，请稍后重试；如果持续失败，请联系技术人员处理。` |
| 导出上传失败但本地文件存在 | `查询已完成，云端上传失败，已保留本地导出文件。\n\n导出文件：<export.path>` |
| `job_id` 不存在 | `未找到该 Google Trends 任务，请确认 job_id 是否正确，或重新发起查询。` |
