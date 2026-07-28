# Dashboard Operation Standards

本文件只定义数据集、字段和图表业务规则。创建与修改流程见 `../SKILL.md`，工具参数见 `dashboard-tool-contract.md`。

## 能力边界

- 只编辑当前页面，不用字段元数据推断真实业务数据。
- 用户明确指向已有图表时进入修改流程；要求分析主题、总览或新增视图时进入新建流程。
- 页面固定 12 列，但模型不计算坐标或宽度；创建顺序、默认宽度和位置由页面处理。

## 数据集

- 数据集和字段必须来自本轮页面工具结果，禁止猜测或手写 ID。
- 一个明确候选可直接使用；多个候选会改变结果时，用 `ask_user_question` 展示 2 到 4 个真实候选，禁止正文列序号或替用户选择。
- 一批新图表共享一个 `datasetId`，不跨数据集拼接。
- 字段计划必须来自所选数据集在本轮返回的完整字段目录。
- 修改已有图表的数据集时重新读取字段目录，不沿用历史轮次字段。

## 字段

- 外层 `dimensions` 和 `metrics` 是字段真实角色。维度、度量只进入兼容槽位，双角色槽位才允许两类字段。
- 展示匹配使用 `title/key`；定位优先使用 `actionFieldId`，数字型操作按 schema 使用 `fieldId`。
- 字段定位器只提交真实 ID 和对应 `fieldSourceType`，不拼装完整字段对象。
- 指标卡只配置 1 个度量；环形图只配置 1 个类别维度和 1 个度量。
- 比率类指标必须明确分子、分母、统计粒度和筛选范围；口径不清时询问。
- 整批计划任一字段不合法时不得创建任何图表。

## 图表选择

用户指定类型时服从用户。未指定时按下表选择；优先级表示内置组合的维护顺序，已知分类直接命中对应组合族，只有第 6 级是兜底。表内组合和顺序仅为规划建议，不构成页面固定模板：

| 优先级 | 组合族与分类 | 建议 `viewType` | 条件替换 |
| --- | --- | --- | --- |
| 1 | 增长与机会：销售、市场 | 销售：`metric_trend`、`hbar_basic`、`hbar_stacked_percent`、`crosstab_table`；市场：`indicator`、`combo_bar_line`、`hbar_basic`、`bar_stacked_percent`、`pivot_table` | 需要记录级处理时用 `detail_table` 替换汇总表 |
| 2 | 营销与转化：广告、流量、活动 | 广告/流量：`indicator`、`combo_bar_line`、`hbar_basic`、`bar_stacked_percent`、`detail_table`；活动默认去掉结构图 | 同群体严格阶段成立时以 `funnel_basic` 替换结构图；活动按字段至多补一张结构图或漏斗图 |
| 3 | 供应链执行：库存、物流 | `metric_trend`、`hbar_basic`、`bar_stacked`、`detail_table` | 有周转、库存、时效、预算或节点目标时增加 `progress_chart`，仍不超过 5 张 |
| 4 | 问题与售后：退款、客服 | `metric_trend`、`hbar_basic`、`hbar_stacked_percent`、`detail_table` | 同时比较规模与比率时以 `combo_bar_line` 替换 `metric_trend` |
| 5 | 绩效与健康监控：监控提醒、平台报告、运营监控 | 提醒：`indicator`、`line_basic`、`hbar_basic`、`hbar_stacked_percent`、`detail_table`；平台：`metric_trend`、`progress_chart`、`hbar_basic`、`detail_table`；运营：`metric_trend`、`bar_basic`、`hbar_stacked_percent`、`detail_table` | 提醒仅单指标时用 `metric_trend` 替换指标卡和折线；平台无目标时用结构图替换进度图；运营有健康目标时增加 `progress_chart` |
| 6 | 部门工作台兜底：部门数据 | `metric_trend`、`hbar_basic`、`hbar_stacked_percent`、`detail_table` | 无法归入前 5 族时使用，生成前尽量细分业务主题 |

只使用本轮工具 schema 允许的 `viewType`。用户未指定类型时，以 4 到 5 张合法图表为目标；字段不满足时优先按表中规则替换，无法得到至少 4 张合法图表时询问或停止，不伪造分析关系。日期或连续时间字段可用 `line_basic`、`metric_trend` 或 `combo_bar_line`；离散对象和数值指标用 `bar_basic`，类别名较长时用 `hbar_basic`；部分—整体且类别不超过 5–8 个时用 `pie_circle`，更多类别用 `bar_stacked_percent` 或 `hbar_stacked_percent`；多系列共同分类轴用 `bar_stacked` 或 `hbar_stacked`，比较比例时用对应百分比类型；同群体严格有序阶段用 `funnel_basic`；明确目标、预算、阈值或 SLA 时用 `progress_chart`；有记录主键和处理字段时用 `detail_table`，只有聚合维度和指标时用 `pivot_table` 或 `crosstab_table`。模型不指定位置或宽度，页面按计划队列自动落位。

## 修改安全

- 新建批次先完整预检，失败时不保留部分结果。
- 标题在计划中确定，去除首尾空白后长度为 1 到 100。
- `chart_id` 定向修改不得误改其他图表；已知目标时不以选中其他图表作为通用前置步骤。
- 样式一次只修改一个 `styleKey`。
- 字段重排保留聚合、排序、格式、筛选和重命名；增删字段使用对应能力。
- 写入结果不确定时停止，不用连续写入绕过校验。
