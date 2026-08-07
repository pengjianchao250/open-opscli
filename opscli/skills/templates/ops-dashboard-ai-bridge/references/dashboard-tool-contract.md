# Dashboard Tool Contract

本文件定义 `dashboard-tools.v2` 参数、结果和错误动作。规则见 `dashboard-operation-standards.md`，流程见 `../SKILL.md`。参数服从本轮工具 schema。

## 工具入口

| 目的 | 工具 |
| --- | --- |
| 页面上下文 | `dashboard_session_get_context` |
| 数据集候选 | `dashboard_session_search_datasets` |
| 完整字段目录 | `dashboard_session_get_dataset_fields` |
| 单张未配置图表 | `dashboard_editor_add_component` |
| 原子创建并配置 | `dashboard_editor_batch_create_charts` |
| 已知图表批量配置 | `dashboard_editor_batch_configure_charts` |
| 页面图表模板 | `dashboard_editor_add_chart_from_template` |
| 选中已有图表 | `dashboard_editor_select_chart` |

`availableTools` 可执行；`pendingTools` 只能等待或重读上下文。`chart_id` 必须来自页面结果。

按用户目标和实时 schema 选择能力，不为固定流程重复创建或写入。

## 创建与配置合同

数据集和字段计划已就绪时，可原子批量创建。根级提交唯一 `datasetId` 和有序 `charts`：

```json
{
  "datasetId": 101,
  "charts": [
    {
      "viewType": "bar_basic",
      "title": "区域销售额趋势",
      "height": 30,
      "fieldLists": [
        {
          "listType": "xAxis",
          "fields": [{"fieldId": "<actionFieldId>", "fieldSourceType": "dimensions"}]
        }
      ]
    }
  ]
}
```

`height` 可省略。创建不提交布局、坐标或宽度；结果布局只用于核验。

需要先创建再配置时，保存真实 `chartId`，再提交批量配置：

```json
{
  "datasetId": 101,
  "charts": [
    {
      "chart_id": "<createdChartId>",
      "fieldLists": [
        {
          "listType": "xAxis",
          "fields": [{"fieldId": "<actionFieldId>", "fieldSourceType": "dimensions"}]
        }
      ]
    }
  ]
}
```

批量配置要求完整且非空的 `fieldLists`。空图不强配；只指定数据集时补齐最小合法字段计划。

## 已有图表工具

- 数据集与字段：`dashboard_drag_select_dataset`、`dashboard_drag_list_configured_fields`、`dashboard_drag_replace_field_list`、`dashboard_drag_add_field_to_list`、`dashboard_drag_reorder_field_list`。
- 标题与样式：`dashboard_drag_set_chart_title`、`dashboard_drag_patch_chart_style`。
- 筛选与查询控件：先用对应只读列表或 capability 工具，再调用 schema 指定的写工具。
- 位置：仅在用户明确要求移动已有图表时使用 `dashboard_drag_move_chart`。
- 设置面板依赖：需要页面选中态时调用 `dashboard_editor_select_chart`，不得使用旧 drag 选图名。

字段配置只接受完整字段目录、数据集选择结果或已配置字段列表中的真实定位器。不得反复追加字段观察渲染结果，不得用 `toggleFieldChecked` 试错。

## Result 与核验

页面工具统一返回：

```json
{"ok": true, "code": "OK", "message": "可选说明", "data": {}}
```

- 按 `ok -> code -> data` 读取，不能只凭 `message` 判断成功。
- 新建按用户目标核验 `chartId/title/viewType/layout`；要求数据集或字段时再核验最终数据集、`fieldLists`、`changed/refreshed`。
- 定向修改核验返回 `chartId` 等于目标，且非目标图表未变化。
- 证据完整为 `PASS`；明确失败为 `FAIL`；证据不足或结果不确定为 `BLOCKED`。只有 `PASS` 可继续写入或声明完成。

## 错误动作

| code | 动作 |
| --- | --- |
| `DASHBOARD_CONTEXT_MISSING` | 提示从仪表盘编辑页 AI 助手进入后重试 |
| `DASHBOARD_RUN_CONTEXT_INVALID` | 停止，不要求用户补传内部标识 |
| `CAPABILITY_NOT_ALLOWED` | 停止，不绕过页面权限 |
| `UNSUPPORTED` | 检查目标图表和实时工具清单 |
| `VALIDATION_ERROR` | 依据 schema 和同一完整字段目录修正一次 |
| `INVALID_REQUEST` | 检查图表类型和工具适用范围 |
| `TIMEOUT`、`NETWORK_ERROR` | 写操作先重读页面状态，确认未生效后才可重试 |

新增、删除、清空、批量替换或其他结果不确定的写入不得直接重复。

## 非普通图表

- 可信页面模板：只有上下文提供真实 `templateUuid` 和类型时使用 `dashboard_editor_add_chart_from_template`。
- 未配置字段的图表或非图表组件：使用 `dashboard_editor_add_component`。
- 场景组合模板由业务规范维护，最终可用原子批量创建，也可先创建再批量配置。
