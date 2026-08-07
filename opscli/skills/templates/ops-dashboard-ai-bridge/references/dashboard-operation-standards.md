# Dashboard Operation Standards

本文件定义数据集、字段和图表规则。流程见 `../SKILL.md`，参数见 `dashboard-tool-contract.md`。

## 能力边界

- 只编辑当前页面，不用字段元数据推断真实业务数据。
- 用户明确指向已有图表或使用移动、改名、换字段等修改动词时进入修改流程；要求分析主题、总览或新增视图时进入新建流程。
- 页面固定 12 列，但模型不计算坐标或宽度；创建顺序、默认宽度和位置由页面处理。
- 场景组合模板用于分析意图的图表规划，不等同于需要 `templateUuid` 的页面图表模板。

## 数据集

- 数据集和字段必须来自本轮页面工具结果，禁止猜测或手写 ID。
- 一个明确候选可直接使用；多个候选会改变结果时，用 `ask_user_question` 展示 2 到 4 个真实候选，不替用户选择。
- 一批新图表共享一个 `datasetId`，不跨数据集拼接。
- 需要写入字段时，字段计划必须来自所选数据集在本轮返回的完整字段目录。
- 修改已有图表的数据集时重新读取字段目录，不沿用历史轮次字段。

## 字段

- 外层 `dimensions` 和 `metrics` 是字段真实角色。维度、度量只进入兼容槽位，双角色槽位才允许两类字段。
- 展示匹配用 `title/key`；定位优先用 `actionFieldId`，数字型操作按 schema 用 `fieldId`。
- 字段定位器只提交真实 ID 和对应 `fieldSourceType`，不拼装完整字段对象。
- 指标卡只配置 1 个度量；环形图只配置 1 个类别维度和 1 个度量。
- 比率类指标必须明确分子、分母、统计粒度和筛选范围；口径不清时询问。
- 字段写入前必须完成整批校验；任一字段不合法时不得提交字段配置，也不得声明配置完成。

## 图表选择

用户指定类型和数量时服从用户，不受下表数量约束。只有分析意图未指定图表时才按下表选择；优先级表示内置组合的维护顺序，已知分类直接命中对应组合族，只有第 6 级是兜底。表内组合和顺序仅为规划建议，不构成页面固定模板：

| 优先级 | 组合族与分类 | 建议 `viewType` | 条件替换 |
| --- | --- | --- | --- |
| 1 | 增长与机会：销售、市场 | 销售：`metric_trend`、`hbar_basic`、`hbar_stacked_percent`、`crosstab_table`；市场：`indicator`、`combo_bar_line`、`hbar_basic`、`bar_stacked_percent`、`pivot_table` | 需要记录级处理时用 `detail_table` 替换汇总表 |
| 2 | 营销与转化：广告、流量、活动 | 广告/流量：`indicator`、`combo_bar_line`、`hbar_basic`、`bar_stacked_percent`、`detail_table`；活动默认去掉结构图 | 同群体严格阶段成立时以 `funnel_basic` 替换结构图；活动按字段至多补一张结构图或漏斗图 |
| 3 | 供应链执行：库存、物流 | `metric_trend`、`hbar_basic`、`bar_stacked`、`detail_table` | 有周转、库存、时效、预算或节点目标时增加 `progress_chart`，仍不超过 5 张 |
| 4 | 问题与售后：退款、客服 | `metric_trend`、`hbar_basic`、`hbar_stacked_percent`、`detail_table` | 同时比较规模与比率时以 `combo_bar_line` 替换 `metric_trend` |
| 5 | 绩效与健康监控：监控提醒、平台报告、运营监控 | 提醒：`indicator`、`line_basic`、`hbar_basic`、`hbar_stacked_percent`、`detail_table`；平台：`metric_trend`、`progress_chart`、`hbar_basic`、`detail_table`；运营：`metric_trend`、`bar_basic`、`hbar_stacked_percent`、`detail_table` | 提醒仅单指标时用 `metric_trend` 替换指标卡和折线；平台无目标时用结构图替换进度图；运营有健康目标时增加 `progress_chart` |
| 6 | 部门工作台兜底：部门数据 | `metric_trend`、`hbar_basic`、`hbar_stacked_percent`、`detail_table` | 无法归入前 5 族时使用，生成前尽量细分业务主题 |

只用实时 schema 允许的 `viewType`。分析场景通常选 4 到 5 张，但最终数量由目标和字段决定；字段不足时裁剪、替换、询问或停止，不为凑数伪造关系。时间趋势用 `line_basic`、`metric_trend` 或 `combo_bar_line`；离散对象比较用 `bar_basic` 或 `hbar_basic`；部分—整体且类别不超过 5–8 个用 `pie_circle`，更多类别用百分比堆叠；多系列共同分类轴用 `bar_stacked` 或 `hbar_stacked`；严格阶段用 `funnel_basic`；明确目标、预算、阈值或 SLA 用 `progress_chart`；记录级字段用 `detail_table`，聚合字段用 `pivot_table` 或 `crosstab_table`。位置和宽度由页面按计划队列处理。

## 修改安全

- 原子新建批次先完整预检；分阶段创建时保存成功返回的图表 ID，配置失败后停止，不重复创建。
- 标题在计划中确定，去除首尾空白后长度为 1 到 100。
- `chart_id` 定向修改不得误改其他图表；已知目标时不以选中其他图表作为通用前置步骤。
- 修改请求必须保持图表 ID 集合不变，除非用户同时明确要求新增或删除。
- 样式一次只修改一个 `styleKey`。
- 字段重排保留聚合、排序、格式、筛选和重命名；增删字段使用对应能力。
- 写入结果不确定时停止，不用连续写入绕过校验。
