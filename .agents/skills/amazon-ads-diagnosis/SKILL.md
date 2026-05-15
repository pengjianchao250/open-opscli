---
name: amazon-ads-diagnosis
description: 面向 Aukeys Amazon 广告诊断的通用分析技能。用于用户要求分析任意项目部/部门/团队/渠道的 Amazon SC/VC 广告表现、ACOS/ROAS/CVR/CTR、预算分配、ASIN/类目/广告类型/活动结构，或要求复用广告分析方法生成 Excel 报告时；技能会通过 ops-dataset-query 取数，进行周期对比、漏斗诊断、多维聚合、逐行问题提取，并输出结构化工作簿。
---

# Amazon 广告诊断

## 用途

本技能用于生成通用的 Amazon 广告诊断报告，不绑定任何固定部门、项目或周期。它会基于用户指定的分析对象和时间范围，从 Aukeys 数据集中取数，按曝光、点击、转化、销售额、利润/投产的链路诊断广告问题，并输出多工作表 Excel。

需要配合使用：
- `ops-dataset-query`：用于数据集检索、字段校验和远端取数。
- Python 3 与 `openpyxl`：用于生成和校验 `.xlsx` 工作簿。依赖见 `scripts/requirements.txt`。

## 标准流程

1. 确认分析范围。
   - 分析对象使用通用参数表达，例如 `{目标部门}`、`{目标渠道}`、`{目标国家}`、`{目标平台}`。
   - 如果用户只说“分析某项目部情况”，默认该项目部对应 `dept_name`。
   - 如果用户没有指定周期，默认分析最近一个完整自然月，并与上一个完整自然月对比。
   - 如果用户没有指定国家和平台，默认 `country_name = 美国`，`platform_name in ["Amazon","Amazon VC"]`。

2. 确认诊断标准。
   - 默认使用 `references/thresholds.default.json`。
   - 如果用户提供了毛利目标、ACOS 目标、广告费占比目标、类目差异或新品/成熟品阶段，先复制默认配置到工作区并调整，再通过脚本参数 `--threshold-config` 传入。
   - 如果用户要求严格控亏、冲排名、新品冷启动、大促期复盘等特殊目标，必须在分析前说明将采用的判断侧重点；必要时向用户确认阈值。

3. 认证与字段校验。
   - 按 `ops-dataset-query` 的规则完成认证检查。
   - 优先走正式 `opscli query` 或 MCP 查询工具，不直接调用后端 HTTP。
   - 若 catalog 不可用，可使用 `references/data-recipes.md` 中已验证的数据集和字段，但仍需做轻量探查确认有数据。

4. 拉取数据。
   - 当前期与对比期分别拉取广告底稿、经营/利润底稿、活动层底稿。
   - 活动层数据通常不直接包含部门字段，应先从广告底稿发现该分析对象对应的渠道，再用渠道过滤活动层数据。
   - 原始 JSON 建议保存到工作区的 `data/<analysis_id>/` 下，避免覆盖历史分析。

5. 生成工作簿。
   - 标准场景使用 `scripts/amazon_ads_analysis.py`。
   - 运行时显式传入当前期/对比期的三类数据源、报告标题、周期标签、输出路径和阈值配置。
   - 工作簿会生成总览、口径校验、多维分析、规则说明和原始底稿页。

6. 诊断与校验。
   - 按 `references/analysis-method.md` 的漏斗顺序诊断，不只看 ACOS。
   - 结合曝光、点击、转化、销售额、毛利、广告费占比和环比变化判断。
   - 毛利或产品竞争力异常时，直接指出 Listing/价格/评价/优惠/配送/成本等非广告因素。
   - 最终交付前检查页签、关键数、口径差异和 Excel 错误值。

## 标准工作表

标准报告包含：

- `00_总览`
- `01_口径校验`
- `02_大组分析`
- `03_小组分析`
- `04_渠道分析`
- `05_广告类型分析`
- `06_类目分析`
- `07_ASIN分析`
- `08_活动分析`
- `09_规则说明`
- `10_广告底稿_当前期`
- `11_经营底稿_当前期`
- `12_广告底稿_对比期`
- `13_经营底稿_对比期`

## 脚本调用示例

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

## 最终回复

默认用中文回复。保持简洁：

- 给出 Excel 文件链接。
- 概括分析周期、对比周期、范围和核心结论。
- 摘要关键指标变化。
- 说明校验状态和重要口径差异。
- 不在聊天中粘贴大量表格，详细内容放在 Excel 中。

## 资源

- `scripts/amazon_ads_analysis.py`：通用 Excel 生成脚本，仅依赖 Python 标准库与 `openpyxl`。
- `scripts/requirements.txt`：脚本依赖清单。
- `references/data-recipes.md`：数据集、字段和通用取数模板。
- `references/analysis-method.md`：诊断方法、问题归因和动作建议规则。
- `references/thresholds.default.json`：默认判断阈值，可复制后按业务目标调整。
- `references/threshold-config.md`：阈值配置说明与调整策略。
