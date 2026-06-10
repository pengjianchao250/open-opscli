# SIF 查排名与时光机能力扩展 UIUX

## 范围说明

本次没有新增前端页面，UIUX 重点是 CLI、MCP、Skill 的交互体验：

- 用户能用自然语言或短命令触发。
- 终端输出保持清晰、精简、可点击文件路径。
- MCP 输出保持文件名链接，点击后下载 XLSX。
- 错误提示面向业务原因，而不是只暴露接口异常。

## CLI 体验

### 命令形态

```powershell
opscli sif run 查排名 --asin B0BMW2985V
opscli sif run 运营时光机 --asin B01NBNDC1T --last-months 6 --granularity day
opscli sif run 产品时光机 --keyword "balloon pump"
```

`--site` 输入继续沿用 SIF 已有站点字段，例如 `US`、`美国`、`美国站` 等；CLI 层不展示另一套国家清单，避免和现有 SIF 模块不一致。

### 成功输出

非 JSON 模式继续使用现有表格风格：

```text
Sif 执行成功
功能        查排名
ASIN        B0BMW2985V
站点        US
每日排名    每日排名_B0BMW2985V_1780000000000.xlsx
            <file link>
```

产品时光机显示 `关键词`：

```text
Sif 执行成功
功能        产品时光机
关键词      balloon pump
站点        US
产品时光机  产品时光机_balloon_pump_1780000000000.xlsx
            <file link>
```

终端暂不展示任务目录和结构化结果路径，保持与当前 SIF 输出优化一致。

### 错误输出

继续沿用：

- 错误码
- 原因
- 建议

新增常见提示：

- 缺少 ASIN：`该功能需要 ASIN，请通过 --asin 传入。`
- 缺少关键词：`产品时光机需要关键词，请通过 --keyword 传入。`
- 无效粒度：`granularity 仅支持 day/week/month 或 week/month。`
- 无效最近月份：`last-months 仅支持 3/6/12/24。`

## MCP 体验

MCP 返回结果继续使用：

- `exports`
- `download_links`
- `download_markdown`
- `display_filename`

面向客户端回答时优先展示文件名链接：

```text
SIF 产品时光机已完成
关键词：balloon pump
站点：US
文件：[产品时光机_balloon_pump_1780000000000.xlsx](...)
```

不要展示本地绝对路径，除非用户明确要求排查本地文件。

## Skill 自然语言映射

### 查排名

用户说法：

- “帮我查 B0BMW2985V 的排名”
- “查每日排名”
- “查坑位”
- “推排名数据”

映射：

```json
{"feature":"查排名","asin":"B0BMW2985V","granularity":"week"}
```

### 运营时光机

用户说法：

- “查 B01NBNDC1T 近六个月运营时光机”
- “看这个 ASIN 的流量变化”
- “看流量词数量变化”
- “按周趋势看运营时光机”

映射：

```json
{"feature":"运营时光机","asin":"B01NBNDC1T","last_months":6,"granularity":"day"}
```

如果用户提到“流量词数量变化”：

```json
{"feature":"运营时光机","asin":"B01NBNDC1T","change_type":"all"}
```

### 产品时光机

用户说法：

- “查 balloon pump 的产品时光机”
- “按关键词 balloon pump 查产品销量”
- “查关键词 balloon pump 最近 30 天”
- “查 2026-02 月 balloon pump”

映射：

```json
{"feature":"产品时光机","keyword":"balloon pump","time_piece_type":"latelyDay","time_piece_value":"7"}
```

## 输出文件命名

新增模块本地文件名使用中文业务名，保持用户可读：

- `每日排名_<ASIN>_<timestamp>.xlsx`
- `运营时光机_<ASIN>_<timestamp>.xlsx`
- `产品时光机_<keyword>_<timestamp>.xlsx`

如果后续能从 SIF 响应 header 解析真实下载文件名，可优先使用 SIF 原始文件名。

## 验收观察点

- CLI 输出不出现 Cookie、Token、密码。
- MCP 链接 label 是完整文件名，包含 `.xlsx`。
- 产品时光机不强制用户传 ASIN。
- 新增模块站点解析与现有 SIF 模块一致。
- 自然语言中出现具体子场景时，只执行对应参数映射。
- JSON 模式保留完整结构化数据，便于自动化验收。
