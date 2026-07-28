# Dashboard Tool Contract

本文件定义 `dashboard-tools.v2` 的参数、结果和错误动作。业务规则见 `dashboard-operation-standards.md`，流程见 `../SKILL.md`。具体参数始终服从本轮工具 schema。

## 工具入口

| 目的 | 工具 |
| --- | --- |
| 页面上下文 | `dashboard_session_get_context` |
| 数据集候选 | `dashboard_session_search_datasets` |
| 完整字段目录 | `dashboard_session_get_dataset_fields` |
| 新建图表批次 | `dashboard_editor_batch_create_charts` |
| 选中已有图表 | `dashboard_editor_select_chart` |

`availableTools` 是可执行清单；`pendingTools` 只能等待或重读上下文。所有 `chart_id` 必须来自上下文或页面工具结果。

## 批量创建合同

根级只提交唯一 `datasetId` 和有序 `charts`。完整请求示例：

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

`height` 可省略。创建请求不提交布局对象、坐标或宽度。结果中的最终布局仅用于核验，不回填为下一次创建参数。

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
- 新建批次按输入顺序核验每张图表的 `chartId/title/viewType/layout/fieldLists`，并核验 `changed/refreshed`。
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

- 可信模板：`dashboard_editor_add_chart_from_template`。
- 用户明确要求的非图表组件：`dashboard_editor_add_component`。
- 普通数据图表包含显式单图，统一使用批量创建工具。
