---
name: ops-methods-card
description: "用于处理 Aukeys AI 方法卡、方法卡、method card、methods card 分析任务：先通过 ops-auth 完成登录授权，再用 opscli methods-card 获取方法卡列表和详情，解析方法卡关联的 Analysis View，通过 ops-cli-view-runner 补齐参数并导出 Excel，最后按方法卡规则生成本地 HTML 报告。"
---

# ops-methods-card

用于 Aukeys methods card 相关任务。当前版本以方法卡关联的 Analysis View 为数据入口，不再要求用户直接提供本地 Excel。

---

## 运行模式判断

优先级如下：

1. 用户明确要求 CLI 或 MCP 时，直接遵循用户指定。
2. 在 `opscli` 项目里默认走 CLI，先执行 `opscli auth token status`。
3. 若状态失败、未登录、未授权或 Token 过期，切换到 `ops-auth`。
4. 若 CLI/MCP 都不可用，提示用户先安装或配置 `aukeys-opscli`。

---

## 强制认证门禁

> **【强制】每次调用 `ops-methods-card` 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`。
- 若认证状态有效，跳过登录，不要重复打断用户。
- 若命令失败，或输出中出现“未登录 / 未授权 / Token 过期 / expired / 401”等状态，必须立即切换到 `ops-auth` Skill。
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh --all`。
- 若是未登录、未授权、401、刷新失败或状态仍异常，在 `ops-auth` 中执行 `opscli auth login`。
- 登录或刷新后必须再次执行 `opscli auth token status`。
- 只有认证检查通过后，才允许继续 methods card 后续流程。
- 若认证状态仍未通过，停止 methods card 后续动作。

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

---

## 核心流程

处理分析任务时，按顺序执行：

1. 完成认证门禁。
2. 通过 `opscli methods-card list` 获取方法卡列表。
3. 根据用户输入、方法卡标题、编码、描述、`inputIntent` 和 `scope` 选择最合适的卡片。
4. 通过 `opscli methods-card detail <card_id>` 获取详情。
5. 读取 `references/method-card-parameter-guide.md`，确认方法规则字段含义。
6. 从 `detail.content.analysisView` 和 `detail.content.executionContract.inputBindings` 解析需要运行的 Analysis View。
7. 对每个视图调用 `ops-cli-view-runner`。
8. 如果 runner 返回 `needs_input=true`，按缺参提示格式要求用户补充入参，并在用户补充后继续当前方法卡流程。
9. 如果 runner 返回成功结果，对导出的 Excel 调用 `scripts/xlsx_preview.py` 生成数据摘要。
10. 结合方法卡规则、视图配置摘要、Excel 数据摘要和用户要求完成分析。
11. 生成完整 HTML 文件，并保存到本地 `output/methods-card/`。

---

## Analysis View 运行计划

运行计划按以下规则生成：

1. 优先读取 `executionContract.inputBindings[]` 中 `sourceType=analysis_view` 的绑定，`sourceKey` 为视图 ID。
2. 如果没有分析视图输入绑定，则读取 `analysisView[]`。
3. 同一视图 ID 只运行一次。
4. 如果方法卡没有配置可运行视图，停止并提示该方法卡缺少 `analysisView` 或 `executionContract.inputBindings`。

调用 runner 示例：

```bash
python opscli/skills/templates/ops-cli-view-runner/scripts/run_view.py \
  --view-id <view_id> \
  --params '<runtime_params_json>' \
  --output "output/methods-card/data/<run_id>/<view_name>.xlsx" \
  --pretty
```

运行时参数 JSON 的 key 必须使用 runner 返回的 `missing[].field`，或 Analysis View `inputSchema.required` 中的字段 ID。

---

## 缺参提示

当 `ops-cli-view-runner` 输出 `needs_input=true` 时，必须暂停分析并提示用户补充。提示格式：

```text
当前方法卡需要补充以下分析视图参数：

视图：<view_name>（<view_id>）
- <description>：字段 <field>，类型 <type>，可选值 <values>

请按“字段=值”的形式补充。
```

约束：

- 多个视图缺参时按视图分组展示。
- 必须保留当前方法卡、视图 ID、已识别参数和缺失字段上下文。
- 用户补充后继续当前流程，不重新选卡。
- 不要为缺失参数臆造默认值。

---

## Excel 预览

`scripts/xlsx_preview.py` 只用于预览 `ops-cli-view-runner` 导出的 Excel。

预览信息用于分析：

- sheet 名称。
- headers。
- row_count。
- preview_rows。
- numeric_summary。

如果 Excel 为空、字段缺失或规则指标无法匹配，必须在 HTML 报告中说明，不要生成虚假结论。

---

## 方法规则

按 `references/method-card-parameter-guide.md` 读取并理解以下配置：

- `analysisPolicy`：分析判断原则。
- `thresholdConfig`：阈值配置。
- `ruleContract`：诊断规则、指标、阈值、归因和动作建议。
- `analysisSteps`：分析流程顺序。
- `executionContract`：运行绑定。
- `outputContract`：报告输出要求。

规则执行要求：

- `ruleContract.thresholdKey` 必须能引用 `thresholdConfig.key`。
- `ruleContract.metric` 必须能映射到 Excel 字段或可解释的派生指标。
- 无法执行的规则要标记为“未执行”，并说明原因。
- 样本量不足、字段缺失、口径不一致必须进入报告限制说明。

---

## HTML 报告

报告保存路径：

```text
output/methods-card/<方法卡ID或名称>-YYYYMMDD-HHMMSS.html
```

报告至少包含：

- 方法卡信息。
- 用户问题。
- 运行参数和默认参数说明。
- Analysis View 列表和 Excel 文件路径。
- 数据摘要。
- 规则执行结果。
- 分析结论。
- 风险、样本量、字段缺失或口径差异说明。

HTML 使用纯 HTML + 内联 CSS，不依赖外部 CDN，不使用 emoji 作为功能图标或占位。

---

## 使用原则

- 认证逻辑必须统一委托 `ops-auth` 或 `opscli auth`，不要在本 Skill 内直接读取凭证文件。
- 后端方法卡列表和详情必须通过 `opscli methods-card` 命令获取，不要在 Skill 脚本里直接调用方法卡后端 HTTP API。
- Analysis View 详情、缺参判断、`filterRule` 写回和 Excel 导出统一委托 `ops-cli-view-runner`。
- 数据查询与 Excel 导出失败时，保留 runner 原始错误；若失败来自 `opscli` CLI 或 MCP Tool，必须按项目规则调用 `ops-feedback` 提交结构化反馈。
- Excel 解析只读取 runner 导出的本地文件，不访问网络。
- 后续如需新增真实业务能力，必须先补充 PRD、架构和 Spec 后再实现。
