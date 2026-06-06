# Rufus 问题模板接口调用说明

## 适用范围

本文只描述 `ops-amazon-rufus` 使用的问题模板数据与接口调用方式，包括默认题库获取、管理端模板保存、问题列表保存和本地题库文件关系。

本文不描述 Rufus 回答获取、seed request、SSE 解析或答案报告格式化。回答获取流程见 `references/rufus-mcp-workflow.md`，报告格式化规范见 `references/rufus-report-formatting.md`。

## 认证与基础路径

管理端接口由 operation-frontend 的 `extensionInterceptors` 调用，基础路径取决于运行环境的 `VITE_EXTENSIONS_API_BASE_URL` 或同源代理。

请求认证由前端统一注入：

- `Authorization: Bearer <OPERATION_TOKEN>`
- `X-Polaris-User-Token: <OPERATION_USER_TOKEN 或 polarisUserToken cookie>`
- `withCredentials: true`

Skill 文档不得直接调用后端接口。如果后续需要通过 CLI 保存问题模板，应先新增正式 `opscli` 命令，由 `opscli` 负责认证、参数校验与错误映射。

## 数据模型

接口响应通常包在统一 `code / data / msg` 结构中。本文的响应示例只展示 `data` 部分。

前端 TypeScript 类型使用 camelCase；请求和响应经过 `extensionInterceptors` 自动转换后，wire JSON 与本地 `question_templates.json` 按 snake_case 表达。

### 模板列表项

```json
{
  "id": 12,
  "description": "默认问题模板",
  "preferred_version_index": 0,
  "questions_count": 8,
  "created_at": "2026-04-28T09:25:05",
  "updated_at": "2026-04-28T09:25:12"
}
```

### 模板详情

```json
{
  "id": 12,
  "description": "默认问题模板",
  "preferred_version_index": 0,
  "questions": [
    {
      "id": 3172,
      "text": "请分析该商品的核心卖点",
      "position": 1
    }
  ],
  "created_at": "2026-04-28T09:25:05",
  "updated_at": "2026-04-28T09:25:12"
}
```

## 获取默认题库

`opscli skills upgrade ops-amazon-rufus` 使用默认题库接口同步数据到本地 Skill。

```http
GET /opencalw/default-question-templates
```

响应 `data`：

```json
{
  "items": [
    {
      "id": 12,
      "description": "默认问题模板",
      "preferred_version_index": 0,
      "questions": [
        {
          "id": 3172,
          "text": "请分析该商品的核心卖点",
          "position": 1
        }
      ],
      "created_at": "2026-04-28T09:25:05",
      "updated_at": "2026-04-28T09:25:12"
    }
  ]
}
```

同步后本地文件路径：

```text
.agents/skills/ops-amazon-rufus/data/question_templates.json
```

`amazon-rufus get` 只读取该本地文件，不会在回答获取过程中自动拉取或保存模板。

## 管理端模板接口

这些接口用于管理问题模板本身，即模板描述、模板列表和模板详情。

### 列出模板

```http
GET /admin/opencalw/question-templates
```

响应 `data`：

```json
{
  "items": [
    {
      "id": 12,
      "description": "默认问题模板",
      "preferred_version_index": 0,
      "questions_count": 8,
      "created_at": "2026-04-28T09:25:05",
      "updated_at": "2026-04-28T09:25:12"
    }
  ]
}
```

### 获取模板详情

```http
GET /admin/opencalw/question-templates/{templateId}
```

响应 `data` 为模板详情，包含 `questions` 列表。

### 新增模板

新增模板只创建模板描述，不同时保存问题列表。问题内容需要通过 questions 接口单独保存。

```http
POST /admin/opencalw/question-templates
Content-Type: application/json
```

请求体：

```json
{
  "description": "默认问题模板"
}
```

响应 `data` 为模板详情。

### 修改模板描述

```http
PATCH /admin/opencalw/question-templates/{templateId}
Content-Type: application/json
```

请求体：

```json
{
  "description": "更新后的模板描述"
}
```

响应 `data` 为模板详情。

### 删除模板

```http
DELETE /admin/opencalw/question-templates/{templateId}
```

响应 `data`：

```json
{
  "deleted": true
}
```

## 问题列表保存接口

这些接口用于保存模板下的问题。问题顺序由服务端返回的 `position` 表示。

### 整体保存问题列表

该接口会用请求体中的 `questions` 覆盖模板当前问题列表。清空问题列表时传入空数组。

```http
PUT /admin/opencalw/question-templates/{templateId}/questions
Content-Type: application/json
```

请求体：

```json
{
  "questions": [
    "请分析该商品的核心卖点",
    "请分析该商品的主要差评风险"
  ]
}
```

响应 `data`：

```json
{
  "template_id": 12,
  "questions_count": 2,
  "updated_at": "2026-04-28T09:30:00"
}
```

### 追加问题

该接口向模板末尾追加问题。服务端会返回新增、跳过和总数，适合前端“新增问题”动作。

```http
PUT /admin/opencalw/question-templates/{templateId}/questions/append
Content-Type: application/json
```

请求体：

```json
{
  "questions": [
    "请判断该商品是否适合做广告投放"
  ]
}
```

响应 `data`：

```json
{
  "template_id": 12,
  "inserted": 1,
  "skipped": 0,
  "total": 3,
  "updated_at": "2026-04-28T09:31:00"
}
```

### 修改单个问题

```http
PUT /admin/opencalw/question-templates/{templateId}/questions/{questionId}
Content-Type: application/json
```

请求体：

```json
{
  "text": "请重新分析该商品的主要差评风险"
}
```

响应 `data`：

```json
{
  "id": 3172,
  "text": "请重新分析该商品的主要差评风险",
  "position": 1
}
```

### 删除单个问题

```http
DELETE /admin/opencalw/question-templates/{templateId}/questions/{questionId}
```

响应 `data`：

```json
{
  "deleted": true
}
```

## 保存模板工作流

### 新增模板并配置问题

1. 调用 `POST /admin/opencalw/question-templates` 创建模板，拿到 `id`。
2. 调用 `PUT /admin/opencalw/question-templates/{id}/questions/append` 追加问题。
3. 调用 `GET /admin/opencalw/question-templates/{id}` 回读详情，确认 `questions` 已保存。

### 覆盖保存整份问题列表

1. 调用 `GET /admin/opencalw/question-templates/{id}` 获取当前详情。
2. 在本地编辑完整问题文本数组。
3. 调用 `PUT /admin/opencalw/question-templates/{id}/questions` 覆盖保存。
4. 回读详情确认 `questions_count` 和 `questions[].position` 符合预期。

### 修改单题

1. 调用 `GET /admin/opencalw/question-templates/{id}` 找到目标 `questionId`。
2. 调用 `PUT /admin/opencalw/question-templates/{id}/questions/{questionId}` 保存新文本。
3. 回读详情确认文本已更新。

## 本地题库文件

默认题库同步后写入：

```text
.agents/skills/ops-amazon-rufus/data/question_templates.json
```

文件格式与默认题库接口的 `data` 部分一致：

```json
{
  "items": [
    {
      "id": 12,
      "description": "默认问题模板",
      "preferred_version_index": 0,
      "questions": [
        {
          "id": 3172,
          "text": "请分析该商品的核心卖点",
          "position": 1
        }
      ],
      "created_at": "2026-04-28T09:25:05",
      "updated_at": "2026-04-28T09:25:12"
    }
  ]
}
```

`QuestionBankService` 会按 `questions[].position` 排序后执行问题。若文件缺失或问题总数为 0，`amazon-rufus get` 会提示先安装并升级 `ops-amazon-rufus`。

## 注意事项

- 模板保存接口属于管理端能力，不在 `amazon-rufus get` 执行过程中调用。
- `POST /admin/opencalw/question-templates` 只保存描述；问题列表需要通过 questions 接口保存。
- `PUT .../questions` 是整体覆盖，传入空数组会清空问题列表。
- `PUT .../questions/append` 适合追加新问题，并会返回 `inserted` 与 `skipped`。
- 本地 `question_templates.json` 是 Skill 升级结果，不是答案报告输出。
- 文档示例不得包含真实 token、cookie 或生产请求头。
