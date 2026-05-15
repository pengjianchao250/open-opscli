# 方法卡片参数说明

本文档说明当前 AI 方法卡详情页实际保存的 `detail.content` 参数结构，并用 Amazon 广告多维诊断配置作为完整示例。当前前端保存链路是把整个方法卡配置作为 JSON 写入后端详情内容：

```ts
SaveAiMethodsCardParams.detail: AiMethodsCardDetailContent
```

方法卡配置暂未提供独立的“数据来源 schema”“运行时入参 schema”“图表生成 schema”字段。Amazon 广告诊断的数据来源、脚本入参、Excel 工作簿结构，目前通过 `scriptAssets`、`executionContract` 和 `outputContract` 表达。

## 顶层结构

```ts
interface AiMethodsCardDetailContent {
  playbookId: string
  name: string
  description: string
  scope: BusinessScope
  inputIntent: AiMethodsCardTag[]
  analysisView: AiMethodsAnalysisView[]
  analysisPolicy: AiMethodsAnalysisPolicy[]
  thresholdConfig: AiMethodsThresholdConfigItem[]
  ruleContract: AiMethodsRuleContractItem[]
  analysisSteps: AiMethodsAnalysisStep[]
  scriptAssets: AiMethodsScriptAsset[]
  executionContract: AiMethodsExecutionContract
  outputContract: AiMethodsOutputContract
}
```

## 顶层字段说明

| 字段 | 类型 | 是否必填 | 说明 | Amazon 广告诊断 example |
| --- | --- | --- | --- | --- |
| `playbookId` | `string` | 是 | 方法卡编码，对应后端 `card_code`。建议稳定、可读、全局唯一。 | `PBK-AMAZON-ADS-DIAGNOSIS-V1` |
| `name` | `string` | 是 | 方法卡名称，对应后端 `card_name`。 | `Amazon 广告多维诊断` |
| `description` | `string` | 否 | 方法卡说明，用于描述适用业务、分析目标和输出。 | `基于 Amazon SC/VC 广告、经营利润与活动明细数据...` |
| `scope` | `BusinessScope` | 是 | 平台、站点、类目、场景、业务阶段筛选范围。 | 平台：`亚马逊`；站点：`美国/加拿大/英国` |
| `inputIntent` | `AiMethodsCardTag[]` | 否 | 用户意图触发词，帮助匹配何时使用该方法卡。 | `分析 Amazon 广告表现`、`诊断 ACOS/ROAS/CVR/CTR 异常` |
| `analysisView` | `AiMethodsAnalysisView[]` | 否 | 关联分析视图摘要。Amazon 广告诊断配置暂未绑定具体视图。 | `[]` |
| `analysisPolicy` | `AiMethodsAnalysisPolicy[]` | 否 | 分析策略，描述判断原则和业务约束。 | `漏斗诊断顺序`、`样本量保护` |
| `thresholdConfig` | `AiMethodsThresholdConfigItem[]` | 否 | 抽象阈值配置，供诊断规则引用。 | `highAcos=0.3`、`lowCvr=0.01` |
| `ruleContract` | `AiMethodsRuleContractItem[]` | 否 | 诊断规则契约，描述指标、操作符、阈值和动作建议。 | `ACOS 高风险`、`点击后转化弱` |
| `analysisSteps` | `AiMethodsAnalysisStep[]` | 否 | 分析流程步骤。 | `确认分析范围`、`拉取广告类型与 ASIN 明细` |
| `scriptAssets` | `AiMethodsScriptAsset[]` | 否 | 脚本、依赖、配置、参考资料等资源。 | `mainScript`、`dataRecipe`、`scriptCliContract` |
| `executionContract` | `AiMethodsExecutionContract` | 是 | 执行方式、输入绑定、输出绑定、执行前检查。 | `mode=script`，`executorAssetKey=mainScript` |
| `outputContract` | `AiMethodsOutputContract` | 是 | 输出结论和页面默认图表类型。 | 中文结论 + `bar_basic/line_basic/pie_basic/detail_table` |

## `scope`

`scope` 用于描述方法卡适用范围。详情表单支持以下字段：

```ts
interface BusinessScope {
  platforms: string[]
  sites: string[]
  categories: string[]
  scenarios: string[]
  businessStages: string[]
}
```

| 字段 | 类型 | 说明 | example |
| --- | --- | --- | --- |
| `platforms` | `string[]` | 适用平台。详情表单选项包含 `亚马逊`。 | `["亚马逊"]` |
| `sites` | `string[]` | 适用站点。详情表单选项包含 `美国`、`加拿大`、`英国`。 | `["美国", "加拿大", "英国"]` |
| `categories` | `string[]` | 适用品类。 | `["家具"]` |
| `scenarios` | `string[]` | 适用业务场景。 | `["广告优化", "广告异常诊断", "广告预警"]` |
| `businessStages` | `string[]` | 适用业务阶段。 | `["新品期", "成长期", "稳定期"]` |

Example：

```json
{
  "scope": {
    "platforms": ["亚马逊"],
    "sites": ["美国", "加拿大", "英国"],
    "categories": ["家具"],
    "scenarios": ["广告优化", "广告异常诊断", "广告预警"],
    "businessStages": ["新品期", "成长期", "稳定期"]
  }
}
```

## `inputIntent`

`inputIntent` 是触发方法卡的意图短语列表。每一项只有一个 `name` 字段。

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `name` | `string` | 是 | 用户可能表达的业务意图。 | `分析 Amazon 广告表现` |

Amazon 广告诊断 example：

```json
{
  "inputIntent": [
    { "name": "分析 Amazon 广告表现" },
    { "name": "诊断 ACOS/ROAS/CVR/CTR 异常" },
    { "name": "识别高花费低转化活动或 ASIN" },
    { "name": "判断预算是否应收缩或放量" },
    { "name": "输出 Amazon 广告诊断 Excel" }
  ]
}
```

## `analysisView`

`analysisView` 用于关联已有 AI 分析视图。Amazon 广告诊断配置没有绑定具体视图，因为该诊断流程通过 `ops-dataset-query` 运行时取数。

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `id` | `number` | 是 | 分析视图 ID，必须为有效正数。 | `8` |
| `name` | `string` | 是 | 分析视图名称。 | `广告转化漏斗分析` |
| `description` | `string` | 否 | 分析视图说明。 | `广告类型、ASIN、活动明细视图` |

Example：

```json
{
  "analysisView": [
    {
      "id": 8,
      "name": "广告转化漏斗分析",
      "description": "提供广告类型、ASIN、活动明细指标"
    }
  ]
}
```

## `analysisPolicy`

`analysisPolicy` 表达分析时必须遵守的判断原则。它不是规则引擎条件，而是对 AI 或执行层的策略约束。

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `name` | `string` | 是 | 策略名称。 | `漏斗诊断顺序` |
| `description` | `string` | 是 | 策略详细说明。 | `必须按曝光、点击、转化、销售与利润、结构与预算顺序诊断...` |

Amazon 广告诊断建议包含以下策略：

| 策略 | 说明 |
| --- | --- |
| `分析范围默认策略` | 缺省时按最近完整自然月、上一完整自然月、美国、Amazon/Amazon VC 处理。 |
| `优化目标判断` | 先判断利润修复、控费提投产、扩大有效流量或稳定结构，不直接套固定动作。 |
| `漏斗诊断顺序` | 按曝光、点击、转化、销售与利润、结构与预算诊断，不只看 ACOS。 |
| `阈值配置策略` | 默认使用成熟品月度复盘阈值，特殊目标时做场景覆盖。 |
| `样本量保护` | 低样本行不做激进停投或大幅提价。 |
| `问题归因框架` | 统一归因为量级、流量质量、Listing 承接、广告结构、预算分配。 |
| `动作建议边界` | 只输出建议和待办候选，不自动修改广告预算、竞价、否定词或 Listing。 |

Example：

```json
{
  "analysisPolicy": [
    {
      "name": "漏斗诊断顺序",
      "description": "必须按曝光、点击、转化、销售与利润、结构与预算顺序诊断，不得跳过前置环节直接按 ACOS 或 ROAS 下结论。"
    },
    {
      "name": "样本量保护",
      "description": "低样本行不做激进停投或大幅提价，除非已经出现明确亏损、高 ACOS 或点击后不转化。"
    }
  ]
}
```

## `thresholdConfig`

`thresholdConfig` 是扁平阈值列表。`ruleContract.thresholdKey` 通过 `key` 引用这里的阈值。

```ts
type AiMethodsThresholdValueType = 'number' | 'percent' | 'currency' | 'integer'
```

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `key` | `string` | 是 | 阈值键名，同一方法卡内唯一。 | `highAcos` |
| `name` | `string` | 是 | 阈值展示名称。 | `高风险 ACOS 阈值` |
| `valueType` | enum | 是 | 值类型：`number`、`percent`、`currency`、`integer`。 | `percent` |
| `unit` | `string` | 否 | 单位。百分比可填 `%`，货币可填 `CNY`。 | `%` |
| `value` | `string \| number \| null` | 是 | 阈值值。百分比按小数保存，`0.3` 表示 30%。 | `0.3` |
| `description` | `string` | 是 | 阈值业务含义和使用边界。 | `ACOS 高于该值时倾向立即控量...` |

Amazon 广告诊断默认阈值映射：

| 诊断阈值 | 方法卡 `thresholdConfig.key` | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| `highAcos` | `highAcos` | `percent` | `0.30` | 高风险 ACOS，超过后倾向立即控量。 |
| `warnAcos` | `warnAcos` | `percent` | `0.22` | 预警 ACOS，提示投产偏弱。 |
| `goodAcos` | `goodAcos` | `percent` | `0.12` | 优秀 ACOS，用于判断是否可放量。 |
| `lowCtr` | `lowCtr` | `percent` | `0.003` | 低点击率，高曝光低点击判断。 |
| `lowCvr` | `lowCvr` | `percent` | `0.01` | 低转化率，点击后转化弱判断。 |
| `goodCvr` | `goodCvr` | `percent` | `0.02` | 较好转化率，用于识别可放量对象。 |
| `highAdShare` | `highAdShare` | `percent` | `0.12` | 广告费占总销售偏高阈值。 |
| `weakMargin` | `weakMargin` | `percent` | `0.05` | 弱毛利率阈值。 |
| `rowSpend.asin` | `rowSpendAsin` | `currency` | `10000` | ASIN 层逐行诊断最小广告费样本。 |
| `minClicks.campaign` | `minClicksCampaign` | `integer` | `1000` | 活动层 CVR 判断点击样本。 |
| `minImpressions.campaign` | `minImpressionsCampaign` | `integer` | `300000` | 活动层 CTR 判断曝光样本。 |

Example：

```json
{
  "thresholdConfig": [
    {
      "key": "highAcos",
      "name": "高风险 ACOS 阈值",
      "valueType": "percent",
      "unit": "%",
      "value": 0.3,
      "description": "ACOS 高于该值时倾向立即控量、降价或排查高花费低转化流量。配置值按小数比例保存，0.30 表示 30%。"
    },
    {
      "key": "rowSpendAsin",
      "name": "ASIN 层最小广告费样本",
      "valueType": "currency",
      "unit": "CNY",
      "value": 10000,
      "description": "ASIN 层逐行诊断的最小广告费样本阈值，低于该值时除亏损、高 ACOS 或无转化外以观察为主。"
    }
  ]
}
```

## `ruleContract`

`ruleContract` 是可配置的诊断规则列表。每条规则通过 `metric + operator + thresholdKey` 形成判断条件，再给出问题归因、优先级和动作建议。

```ts
type AiMethodsRuleOperator = '>' | '>=' | '<' | '<=' | '='
```

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `key` | `string` | 是 | 规则键名，同一方法卡内唯一。 | `highAcos` |
| `name` | `string` | 是 | 规则展示名称。 | `ACOS 高风险` |
| `description` | `string` | 是 | 规则说明。 | `ACOS 高于高风险阈值时...` |
| `metric` | `string` | 是 | 指标字段名，由分析视图或脚本输出约定。 | `acos` |
| `operator` | enum | 是 | 比较操作符。 | `>` |
| `thresholdKey` | `string` | 是 | 引用 `thresholdConfig.key`。 | `highAcos` |
| `problemType` | `string` | 是 | 问题归因。 | `预算分配问题` |
| `priority` | `string` | 是 | 处理优先级。 | `立即执行` |
| `action` | `string` | 是 | 动作建议。 | `降低出价或预算...` |

Amazon 广告诊断常见 `metric`：

| metric | 含义 |
| --- | --- |
| `gross_margin` | 毛利率。 |
| `ad_share_total` | 广告费占总销售。 |
| `acos` | 广告费 / 广告销售额。 |
| `cvr` | 广告订单 / 点击。 |
| `ctr` | 点击 / 曝光。 |
| `ad_spend` | 广告费。 |
| `ad_spend_mom` | 广告费环比。 |
| `acos_mom` | ACOS 环比变化。 |
| `ad_sales_mom` | 广告销售额环比。 |

Example：

```json
{
  "ruleContract": [
    {
      "key": "highAcos",
      "name": "ACOS 高风险",
      "description": "ACOS 高于高风险阈值时，判断投产显著偏弱，需优先控量或拆分流量来源。",
      "metric": "acos",
      "operator": ">",
      "thresholdKey": "highAcos",
      "problemType": "预算分配问题",
      "priority": "立即执行",
      "action": "降低出价或预算，排查高花费低转化搜索词、活动、广告类型或 ASIN。"
    },
    {
      "key": "lowCvr",
      "name": "点击后转化弱",
      "description": "点击样本达到当前层级阈值且 CVR 低于低转化阈值时，判断为流量质量或 Listing 承接问题。",
      "metric": "cvr",
      "operator": "<",
      "thresholdKey": "lowCvr",
      "problemType": "流量质量或Listing承接问题",
      "priority": "立即执行",
      "action": "降低泛流量出价，暂停低转化投放；同步检查主图、价格、评价、优惠、库存和配送。"
    }
  ]
}
```

## `analysisSteps`

`analysisSteps` 描述执行流程顺序。它适合承接 Amazon 广告诊断的标准流程。

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `name` | `string` | 否 | 步骤名称。 | `拉取广告类型与 ASIN 明细` |
| `description` | `string` | 否 | 步骤说明。 | `使用 custom_type_advertising_list 数据集...` |

Amazon 广告诊断推荐步骤：

1. 确认分析范围。
2. 确认诊断标准。
3. 完成认证与字段校验。
4. 拉取广告类型与 ASIN 明细。
5. 拉取经营与利润明细。
6. 拉取广告活动明细。
7. 执行口径校验。
8. 计算派生指标。
9. 判断整体优化目标。
10. 按漏斗顺序诊断。
11. 多维聚合并逐行提取问题。
12. 生成工作簿与最终摘要。

Example：

```json
{
  "analysisSteps": [
    {
      "name": "拉取广告类型与 ASIN 明细",
      "description": "使用 custom_type_advertising_list 数据集，按周期、部门、国家、平台过滤，获取平台、渠道、大组、小组、广告类型、ASIN、产品、类目及广告费、广告销售额、订单、点击、曝光。"
    },
    {
      "name": "生成工作簿与最终摘要",
      "description": "生成总览、口径校验、多维分析、规则说明和原始底稿页；最终回复只概括范围、周期、核心结论、关键指标变化、校验状态和 Excel 文件位置。"
    }
  ]
}
```

## `scriptAssets`

`scriptAssets` 保存脚本执行所需的资源描述。当前支持选择前端脚本模板，并把完整 Python 脚本文本保存到 `content`。

```ts
type AiMethodsScriptAssetType = 'script' | 'dependency' | 'reference' | 'config'
```

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `key` | `string` | 是 | 资产键名，同一方法卡内唯一。 | `mainScript` |
| `name` | `string` | 是 | 资产展示名称。 | `Amazon 广告诊断 Excel 生成脚本` |
| `assetType` | enum | 是 | 资产类型：脚本、依赖、参考资料、配置资源。 | `script` |
| `value` | `string` | 是 | 脚本资源标识、依赖声明、参考资料或配置文本。 | `amazon_ads_analysis.py` |
| `description` | `string` | 是 | 资产用途和约束。 | `生成 Amazon 广告多维诊断 Excel 工作簿。输入广告、经营利润与活动明细 JSON，输出总览、口径校验、多维分析和原始底稿工作表。` |
| `language` | `'python'` | 脚本资产自动写入 | 仅 `assetType=script` 使用，页面固定为 `python`。 | `python` |
| `content` | `string` | 否 | 完整脚本文本。选择脚本模板后会保存完整 Python 内容。 | `#!/usr/bin/env python3\n...` |

约束：

- 不保存 `sourcePath`。脚本来源只是前端资源选择行为，最终保存的是资源标识 `value` 和脚本文本 `content`。
- `language` 不提供页面选择，固定为 `python`。
- 非脚本资产不写入 `language` 和 `content`。
- `content` 可以为空；当执行层已有脚本资源时，也可只保存资源标识或引用说明。

Amazon 广告诊断脚本资产 example：

```json
{
  "scriptAssets": [
    {
      "key": "mainScript",
      "name": "Amazon 广告诊断 Excel 生成脚本",
      "assetType": "script",
      "value": "amazon_ads_analysis.py",
      "description": "生成 Amazon 广告多维诊断 Excel 工作簿。输入广告、经营利润与活动明细 JSON，输出总览、口径校验、多维分析和原始底稿工作表。",
      "language": "python",
      "content": "<amazon_ads_analysis.py 完整脚本文本>"
    },
    {
      "key": "pythonRequirements",
      "name": "Python 依赖",
      "assetType": "dependency",
      "value": "openpyxl>=3.0.10",
      "description": "生成 Excel 工作簿所需依赖；脚本其余部分仅依赖 Python 标准库。"
    },
    {
      "key": "thresholdDefaultConfig",
      "name": "默认阈值配置",
      "assetType": "config",
      "value": "{\"thresholds\":{\"highAcos\":0.30,\"warnAcos\":0.22,\"goodAcos\":0.12}}",
      "description": "Amazon 广告诊断默认阈值配置，适用于成熟品常规月度复盘；如存在控亏、新品冷启动、大促期、高毛利或低毛利目标，可复制后进行场景化覆盖。"
    },
    {
      "key": "dataRecipe",
      "name": "取数模板与数据口径",
      "assetType": "reference",
      "value": "数据集 ds_j7mYcAr6j7YD/custom_type_advertising_list、ds_d35ac6f3910c/order_sale_trend_adv_traffic_inv_set、ds_S0CgT7ArBdBs/custom_sp_sd_sb_ads_set；过滤 date_id、dept_name、country_name、platform_name。",
      "description": "当前方法卡模型没有独立的数据来源和入参 schema 字段，因此将取数来源、字段和过滤策略沉淀为参考资产。"
    }
  ]
}
```

## `executionContract`

`executionContract` 描述方法卡如何被执行。当前前端只保存契约，不在页面执行脚本。

```ts
type AiMethodsExecutionMode = 'manual' | 'script' | 'external'
type AiMethodsExecutionBindingSource =
  | 'analysis_view'
  | 'threshold_config'
  | 'rule_contract'
  | 'script_asset'
  | 'output_contract'
```

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `mode` | enum | 是 | 执行方式。`manual` 手动，`script` 脚本，`external` 外部执行。 | `script` |
| `executorAssetKey` | `string` | 否 | 执行入口资产键名，对应 `scriptAssets.key`。 | `mainScript` |
| `inputBindings` | `AiMethodsExecutionBinding[]` | 否 | 输入绑定，描述运行时参数从哪里来、传给哪里。 | `--ad-source` |
| `outputBindings` | `AiMethodsExecutionBinding[]` | 否 | 输出绑定，描述执行结果字段如何流转。 | `output`、`sheets` |
| `precheckItems` | `AiMethodsCardTag[]` | 否 | 执行前检查项。 | `已安装 Python 3 与 openpyxl 依赖` |

### `AiMethodsExecutionBinding`

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `name` | `string` | 是 | 绑定名称。 | `广告底稿当前期` |
| `sourceType` | enum | 是 | 来源类型。 | `script_asset` |
| `sourceKey` | `string` | 是 | 来源键名。若 `sourceType=script_asset`，对应 `scriptAssets.key`。 | `dataRecipe` |
| `targetKey` | `string` | 是 | 目标字段或脚本参数名。 | `--ad-source` |
| `required` | `boolean` | 是 | 是否必填。 | `true` |
| `description` | `string` | 是 | 绑定说明。 | `由广告类型+ASIN 明细数据集导出的当前期 JSON 文件路径。` |

### Amazon 广告诊断脚本入参 example

Amazon 广告诊断脚本调用：

```bash
python scripts/amazon_ads_analysis.py \
  --title "{目标对象} Amazon 广告月度诊断" \
  --period "{当前期开始} 至 {当前期结束}" \
  --compare-period "{对比期开始} 至 {对比期结束}" \
  --ad-source data/{analysis_id}/ad_current.json \
  --profit-source data/{analysis_id}/profit_current.json \
  --campaign-source data/{analysis_id}/campaign_current.json \
  --compare-ad-source data/{analysis_id}/ad_compare.json \
  --compare-profit-source data/{analysis_id}/profit_compare.json \
  --compare-campaign-source data/{analysis_id}/campaign_compare.json \
  --threshold-config references/thresholds.default.json \
  --output outputs/{analysis_id}/{目标对象}_Amazon广告诊断.xlsx
```

对应 `inputBindings`：

| 脚本参数 | required | 来源 | 说明 | example |
| --- | --- | --- | --- | --- |
| `--title` | 是 | `script_asset:scriptCliContract` | 报告标题。 | `项目一部 Amazon 广告月度诊断` |
| `--period` | 是 | `script_asset:scriptCliContract` | 当前分析周期标签。 | `2026-04-01 至 2026-04-30` |
| `--compare-period` | 是 | `script_asset:scriptCliContract` | 对比周期标签。 | `2026-03-01 至 2026-03-31` |
| `--ad-source` | 是 | `script_asset:dataRecipe` | 当前期广告类型 + ASIN 明细 JSON。 | `data/ads-202604/ad_current.json` |
| `--profit-source` | 是 | `script_asset:dataRecipe` | 当前期经营 / 利润明细 JSON。 | `data/ads-202604/profit_current.json` |
| `--campaign-source` | 是 | `script_asset:dataRecipe` | 当前期广告活动明细 JSON。 | `data/ads-202604/campaign_current.json` |
| `--compare-ad-source` | 否 | `script_asset:dataRecipe` | 对比期广告明细 JSON。 | `data/ads-202604/ad_compare.json` |
| `--compare-profit-source` | 否 | `script_asset:dataRecipe` | 对比期经营明细 JSON。 | `data/ads-202604/profit_compare.json` |
| `--compare-campaign-source` | 否 | `script_asset:dataRecipe` | 对比期活动明细 JSON。 | `data/ads-202604/campaign_compare.json` |
| `--threshold-config` | 是 | `script_asset:thresholdDefaultConfig` | 阈值配置文件路径。 | `references/thresholds.default.json` |
| `--output` | 是 | `script_asset:scriptCliContract` | Excel 输出路径。 | `outputs/ads-202604/项目一部_Amazon广告诊断.xlsx` |

Example：

```json
{
  "executionContract": {
    "mode": "script",
    "executorAssetKey": "mainScript",
    "inputBindings": [
      {
        "name": "广告底稿当前期",
        "sourceType": "script_asset",
        "sourceKey": "dataRecipe",
        "targetKey": "--ad-source",
        "required": true,
        "description": "由广告类型+ASIN 明细数据集导出的当前期 JSON 文件路径。"
      },
      {
        "name": "阈值配置文件",
        "sourceType": "script_asset",
        "sourceKey": "thresholdDefaultConfig",
        "targetKey": "--threshold-config",
        "required": true,
        "description": "默认传入 Amazon 广告诊断阈值配置；场景化覆盖时传入复制后的配置文件路径。"
      }
    ],
    "outputBindings": [
      {
        "name": "Excel 报告路径",
        "sourceType": "script_asset",
        "sourceKey": "mainScript",
        "targetKey": "output",
        "required": true,
        "description": "脚本执行成功后打印的 output 字段，对应生成的 .xlsx 文件绝对路径。"
      }
    ],
    "precheckItems": [
      { "name": "已完成 ops-dataset-query 认证检查" },
      { "name": "已确认当前期与对比期数据文件存在且非空" },
      { "name": "已安装 Python 3 与 openpyxl 依赖" }
    ]
  }
}
```

## `outputContract`

`outputContract` 描述最终输出。当前图表类型只保存运营系统默认图表枚举。

| 字段 | 类型 | 是否必填 | 说明 | example |
| --- | --- | --- | --- | --- |
| `conclusion` | `string` | 否 | 输出结论要求。 | `输出中文结构化结论，必须包含 Excel 文件路径...` |
| `charts` | `DefaultChartType[]` | 否 | 输出图表类型。 | `["bar_basic", "line_basic", "pie_basic", "detail_table"]` |

当前可选图表值：

| 值 | 展示名 |
| --- | --- |
| `bar_basic` | 基础柱状图 |
| `line_basic` | 基础折线图 |
| `pie_basic` | 基础饼图 |
| `detail_table` | 明细表 |

Example：

```json
{
  "outputContract": {
    "conclusion": "输出中文结构化结论，必须包含：1. Excel 文件路径；2. 分析周期、对比周期和分析范围；3. 整体判断与当前优化目标；4. 广告费、广告销售额、ACOS、ROAS、CTR、CVR、总销售额、毛利、毛利率、广告费占总销售的关键变化；5. 口径校验状态和重要差异；6. 立即执行、短期观察、暂不建议调整的关键建议摘要。详细明细以 Excel 工作簿为准，不在聊天中展开大表。",
    "charts": ["bar_basic", "line_basic", "pie_basic", "detail_table"]
  }
}
```

## Amazon 广告诊断数据来源 example

当前没有独立数据来源字段，建议写入 `scriptAssets` 中的 `dataRecipe` 参考资产，并通过 `executionContract.inputBindings` 绑定到脚本参数。

### 广告类型 + ASIN 明细

| 参数 | 值 |
| --- | --- |
| 数据集 alias | `ds_j7mYcAr6j7YD` |
| 数据集 name | `custom_type_advertising_list` |
| 维度 | `platform_name:platform`、`channel_name:channel`、`large_team_name:large_team`、`team_name:team`、`ads_type:ad_type`、`asin:asin`、`product_name:product`、`amazon_cat:amazon_cat`、`category:category` |
| 指标 | `total_spend_cny:sum:ad_spend`、`sales_cny:sum:ad_sales`、`conversions:sum:ad_orders`、`clicks:sum:clicks`、`impressions:sum:impressions` |
| 常用过滤 | `date_id between 当前期`、`dept_name = 目标部门`、`country_name = 目标国家`、`platform_name in [Amazon, Amazon VC]` |

### 经营 / 利润明细

| 参数 | 值 |
| --- | --- |
| 数据集 alias | `ds_d35ac6f3910c` |
| 数据集 name | `order_sale_trend_adv_traffic_inv_set` |
| 维度 | `platform_name:platform`、`channel_name:channel`、`large_team_name:large_team`、`team_name:team`、`asin:asin`、`product_name:product`、`amazon_cat:amazon_cat`、`category:category` |
| 指标 | `price:sum:total_sales`、`order_qty:sum:total_orders`、`gross_profit:sum:gross_profit`、`advertising_fee:sum:ad_spend`、`sessions:sum:sessions`、`page_views:sum:page_views` |
| 用途 | 计算毛利、毛利率、广告费占总销售，并与广告底稿做口径校验。 |

### 广告活动明细

| 参数 | 值 |
| --- | --- |
| 数据集 alias | `ds_S0CgT7ArBdBs` |
| 数据集 name | `custom_sp_sd_sb_ads_set` |
| 维度 | `platform_name:platform`、`channel_name:channel`、`ad_type:ad_type`、`campaign_name:campaign` |
| 指标 | `cost_cny:sum:ad_spend`、`sales_cny:sum:ad_sales`、`units_sold:sum:ad_orders`、`clicks:sum:clicks`、`impressions:sum:impressions` |
| 注意 | 活动层通常无 `dept_name`，应先从广告底稿发现渠道，再按 `channel_name` 过滤活动层数据。 |

## 完整最小 example

下面是可保存到 `detail.content` 的压缩示例。完整 Amazon 配置可以参考 `output/2026-05-14-amazon-ads-diagnosis-method-card-config.json`。

```json
{
  "playbookId": "PBK-AMAZON-ADS-DIAGNOSIS-V1",
  "name": "Amazon 广告多维诊断",
  "description": "基于 Amazon SC/VC 广告、经营利润与活动明细数据，按曝光、点击、转化、销售与利润、结构与预算链路诊断广告表现，并生成多工作表 Excel 报告。",
  "scope": {
    "platforms": ["亚马逊"],
    "sites": ["美国", "加拿大", "英国"],
    "categories": ["家具"],
    "scenarios": ["广告优化", "广告异常诊断", "广告预警"],
    "businessStages": ["新品期", "成长期", "稳定期"]
  },
  "inputIntent": [
    { "name": "分析 Amazon 广告表现" },
    { "name": "输出 Amazon 广告诊断 Excel" }
  ],
  "analysisView": [],
  "analysisPolicy": [
    {
      "name": "漏斗诊断顺序",
      "description": "必须按曝光、点击、转化、销售与利润、结构与预算顺序诊断，不得跳过前置环节直接按 ACOS 或 ROAS 下结论。"
    }
  ],
  "thresholdConfig": [
    {
      "key": "highAcos",
      "name": "高风险 ACOS 阈值",
      "valueType": "percent",
      "unit": "%",
      "value": 0.3,
      "description": "ACOS 高于该值时倾向立即控量、降价或排查高花费低转化流量。"
    }
  ],
  "ruleContract": [
    {
      "key": "highAcos",
      "name": "ACOS 高风险",
      "description": "ACOS 高于高风险阈值时，判断投产显著偏弱。",
      "metric": "acos",
      "operator": ">",
      "thresholdKey": "highAcos",
      "problemType": "预算分配问题",
      "priority": "立即执行",
      "action": "降低出价或预算，排查高花费低转化搜索词、活动、广告类型或 ASIN。"
    }
  ],
  "analysisSteps": [
    {
      "name": "拉取广告类型与 ASIN 明细",
      "description": "使用 custom_type_advertising_list 数据集，按周期、部门、国家、平台过滤。"
    }
  ],
  "scriptAssets": [
    {
      "key": "mainScript",
      "name": "Amazon 广告诊断 Excel 生成脚本",
      "assetType": "script",
      "value": "amazon_ads_analysis.py",
      "description": "生成 Amazon 广告多维诊断 Excel 工作簿。输入广告、经营利润与活动明细 JSON，输出总览、口径校验、多维分析和原始底稿工作表。",
      "language": "python",
      "content": "<amazon_ads_analysis.py 完整脚本文本>"
    },
    {
      "key": "scriptCliContract",
      "name": "脚本参数契约",
      "assetType": "config",
      "value": "--title \"{目标对象} Amazon 广告月度诊断\" --period \"{当前期开始} 至 {当前期结束}\" --ad-source data/{analysis_id}/ad_current.json --output outputs/{analysis_id}/{目标对象}_Amazon广告诊断.xlsx",
      "description": "运行时由执行层或人工填充目标对象、周期、数据文件路径、阈值配置和输出路径。"
    }
  ],
  "executionContract": {
    "mode": "script",
    "executorAssetKey": "mainScript",
    "inputBindings": [
      {
        "name": "广告底稿当前期",
        "sourceType": "script_asset",
        "sourceKey": "dataRecipe",
        "targetKey": "--ad-source",
        "required": true,
        "description": "由广告类型+ASIN 明细数据集导出的当前期 JSON 文件路径。"
      }
    ],
    "outputBindings": [
      {
        "name": "Excel 报告路径",
        "sourceType": "script_asset",
        "sourceKey": "mainScript",
        "targetKey": "output",
        "required": true,
        "description": "脚本执行成功后打印的 output 字段。"
      }
    ],
    "precheckItems": [
      { "name": "已完成 ops-dataset-query 认证检查" },
      { "name": "已安装 Python 3 与 openpyxl 依赖" }
    ]
  },
  "outputContract": {
    "conclusion": "输出中文结构化结论，必须包含 Excel 文件路径、分析周期、核心结论、关键指标变化和口径差异。",
    "charts": ["bar_basic", "line_basic", "pie_basic", "detail_table"]
  }
}
```

## 当前缺口与约定

- 数据来源没有独立结构化字段，暂时用 `scriptAssets[].assetType=reference` 的 `dataRecipe` 表达。
- 运行时入参没有独立 schema，暂时用 `scriptAssets[].assetType=config` 的 `scriptCliContract` 和 `executionContract.inputBindings` 表达。
- Excel 工作簿结构没有独立字段，暂时用 `scriptAssets[].assetType=config` 的 `workbookContract` 表达。
- 生成图表目前只保存默认图表类型枚举，不保存具体图表 option。
- 脚本内容直接保存到 `scriptAssets[].content`；后续如引入脚本仓库，可再补充版本、权限、安全扫描和体积限制。
- `scriptAssets[].sourcePath` 不保存；如果页面选择内置资源，最终只落 `value`、`language`、`content`。
