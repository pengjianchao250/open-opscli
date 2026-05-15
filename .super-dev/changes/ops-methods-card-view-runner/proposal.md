# ops-methods-card-view-runner Proposal

## 背景

`ops-methods-card` 当前主流程仍以本地固定 Excel 为数据入口，并引用部分已经不存在的参考文件。新需求要求方法卡不再直接读取用户本地 xlsx，而是根据方法卡关联的 AI 分析视图获取视图配置、判断运行参数、导出 Excel，再基于方法卡规则生成 HTML 报告。

## 目标

1. 将 `ops-methods-card` 主流程改为“方法卡 -> 分析视图 -> `ops-cli-view-runner` -> Excel -> HTML 报告”。
2. 缺少视图运行参数时，向用户提示 `field`、`type`、`description`、`values` 并等待补参后继续。
3. 参数足够时，调用 `ops-cli-view-runner` 导出 Excel 到 `output/methods-card/data/`。
4. 继续使用 `xlsx_preview.py` 预览导出的 Excel，但不再把模板固定 xlsx 作为业务入口。
5. 方法规则以 `references/method-card-parameter-guide.md` 为准，覆盖 `analysisPolicy`、`thresholdConfig`、`ruleContract`、`analysisSteps`、`outputContract`。
6. 如 runner 输出不足以支撑报告说明，向后兼容地补充视图配置摘要。

## 非目标

1. 不新增方法卡创建、保存、删除能力。
2. 不创建或修改 AI 分析视图。
3. 不绕过 `ops-cli-view-runner` 直接调用底层 chart 数据接口。
4. 不上传 HTML 报告。
5. 不做前端页面。
6. 不做 git commit、branch、push。

## 技术方案

### Skill 流程

`ops-methods-card/SKILL.md` 更新为：

```text
认证门禁
  -> opscli methods-card list/detail
  -> 解析 detail.content.analysisView 与 executionContract.inputBindings
  -> 调用 ops-cli-view-runner
      -> 缺参：提示用户补充，并保留上下文
      -> 成功：取得 Excel 路径
  -> xlsx_preview.py 预览导出的 Excel
  -> 按 method-card-parameter-guide.md 规则生成 HTML
```

### runner 输出增强

`ops-cli-view-runner/scripts/run_view.py` 成功输出中补充只读 `view_config` 摘要：

- `input_schema`
- `output_schema`
- `metric_definitions`
- `chart_contract`
- `quality_rules`

缺参输出保持当前 `needs_input=true` 结构，并继续包含 `view_id`、`view_name`、`missing[]`。

### 测试策略

1. 文档契约测试：`ops-methods-card/SKILL.md` 必须包含 view-runner 流程，不再声明默认 Excel 业务入口，也不引用不存在参考文件。
2. runner 单元测试：缺参输出仍包含 field/type/description/values。
3. runner 单元测试：成功输出包含 `view_config` 摘要。
4. 安装链路测试：`ops-methods-card` 模板仍可安装，且不包含 Python 缓存文件。

## 验收标准

1. `ops-methods-card` 文档主流程不再要求用户提供本地 Excel。
2. `ops-methods-card` 文档明确使用 `ops-cli-view-runner` 运行分析视图。
3. 缺参提示规范清晰，并说明用户补参后继续。
4. `xlsx_preview.py` 明确只预览 runner 导出的 Excel。
5. runner 成功输出包含报告可用的视图配置摘要。
6. 定向测试通过。
