# ops-methods-card Research

日期：2026-05-12

## 新需求摘要

`ops-methods-card` 需要从 auth-only Skill 扩展为方法卡分析流程：

1. 使用登录授权信息获取方法卡列表。
2. 根据用户输入、方法卡标题和描述选择最合适的卡片。
3. 获取卡片详情。
4. 读取 `opscli/skills/templates/ops-methods-card/交叉表-1778233062511.xlsx`。
5. 按方法卡规范和示例完成数据分析。
6. 输出 HTML 文件并保存到本地。

## 本地项目发现

### 前端方法卡路径

参考项目：

```text
E:/code/work/operation-frontend - 1/packages/operation-frontend-core/src/pages/aiMethodCard
```

关键文件：

- `index.vue`：列表页调用 `useAiMethodsCardListQuery(listParams)`，展示 `cardName`、`cardCode`。
- `detail.vue`：详情页调用 `useAiMethodsCardDetailQuery(cardId)`，核心编辑态是 `detail.content`。
- `src/api/modules/ai/methodCard.ts`：真实 API 前缀为 `/api/v1/ai/method-card`。
- `src/api/types/ai/methodCard.ts`：定义列表、详情和 `AiMethodsCardDetailContent`。
- `prd/AI-方法卡接口.md`：包含列表和详情接口契约。

### 接口契约

列表接口：

```text
GET /api/v1/ai/method-card
```

详情接口：

```text
GET /api/v1/ai/method-card/{id}
```

当前 `opscli.auth.OPS_URL` 默认已包含 `/api` 后缀，因此 CLI 客户端应拼接：

```text
{OPS_URL}/v1/ai/method-card
{OPS_URL}/v1/ai/method-card/{id}
```

### opscli 约束

- Skill 脚本不能直连后端 API，远端动作必须通过 opscli 正式命令封装。
- 因此新增 `opscli methods-card list/detail`，Skill 只调用该 CLI。
- Excel 解析是本地文件读取，可放在 Skill `scripts/` 中。

## Excel 数据发现

默认文件：

```text
opscli/skills/templates/ops-methods-card/交叉表-1778233062511.xlsx
```

实际结构：

- 工作表：`sheet1`
- 字段：`SPU`、`已售天数`
- 示例行：`BSB-131 / 190`、`BSB-008 / 11646`、`WC-101 / 1701`

该文件适合先转成 JSON 摘要，再由 Agent 按方法卡规则分析。

## Skill Creator 结论

- `SKILL.md` 应保持短，只放认证门禁和主流程。
- API 细节放入 `references/方法卡接口.md`。
- 选卡、读取 Excel、生成 HTML 的步骤放入 `references/执行流程.md`。
- Excel 预览脚本放入 `scripts/xlsx_preview.py`，避免每次临时写解析代码。

