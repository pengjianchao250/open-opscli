# ops-methods-card PRD

日期：2026-05-12

## 目标

将 `ops-methods-card` 扩展为可用的方法卡分析 Skill。用户给出分析诉求后，Skill 应完成认证、选卡、取详情、读 Excel、分析并输出本地 HTML 报告。

## 功能需求

### FR-1 认证门禁

进入 Skill 后先执行 `opscli auth token status`。未登录、未授权或 Token 过期时切换到 `ops-auth` 完成登录或刷新。

### FR-2 方法卡列表

提供正式 CLI：

```bash
opscli methods-card list --keyword "<keyword>" --page 1 --per-page 100 --pretty
```

返回方法卡列表，供 Agent 根据用户输入初步筛选。

### FR-3 方法卡选择

Agent 根据用户输入与以下字段选择卡片：

- `card_name`
- `card_code`
- `scenarios`
- `platforms`
- `sites`
- `categories`
- 详情中的 `detail.content.name`
- 详情中的 `detail.content.description`

无法判断时停止并要求用户补充。

### FR-4 方法卡详情

提供正式 CLI：

```bash
opscli methods-card detail <card_id> --pretty
```

详情的 `detail.content` 作为分析规范来源。

### FR-5 Excel 数据读取

默认读取：

```text
opscli/skills/templates/ops-methods-card/交叉表-1778233062511.xlsx
```

通过 `scripts/xlsx_preview.py` 输出 JSON 摘要。

### FR-6 HTML 报告

按 `references/卡片输出示例.html` 的结构生成完整 HTML，保存到：

```text
output/methods-card/<方法卡ID或名称>-YYYYMMDD-HHMMSS.html
```

## 非目标

- 不新增创建、更新、删除方法卡能力。
- 不上传 HTML。
- 不引入外部 LLM SDK。
- 不在 Skill 脚本中直连后端 API。

## 验收标准

- `opscli methods-card list/detail` 请求带认证信息。
- Skill 文档明确列表、详情、选卡、Excel、HTML 输出流程。
- 默认 Excel 可被脚本读取为 JSON 摘要。
- Skill 校验通过。

