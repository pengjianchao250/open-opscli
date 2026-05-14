# ops-methods-card Proposal

## 背景

`ops-methods-card` 原本只做认证门禁。现在需要扩展为可执行的方法卡分析 Skill：先用登录态获取方法卡列表，根据用户输入与方法卡标题/描述选择卡片，再获取卡片详情，读取本地 Excel 数据，并按方法卡规范输出本地 HTML 报告。

## 目标

1. 新增 `opscli methods-card list/detail` 正式命令，封装方法卡列表和详情接口。
2. Skill 触发后仍先完成 Aukeys 登录授权检查。
3. Skill 通过 `opscli methods-card` 获取列表和详情，不在 Skill 脚本里直连后端。
4. Skill 能读取默认 Excel：`opscli/skills/templates/ops-methods-card/交叉表-1778233062511.xlsx`。
5. Skill 按方法卡详情、用户输入和 Excel 数据生成本地 HTML 报告。
6. Skill 可按 Amazon Rufus 同样方式安装到项目 `.agents/skills/ops-methods-card`。

## 非目标

1. 不新增方法卡创建、更新、删除命令。
2. 不把分析逻辑做成后端接口。
3. 不引入 OpenAI 或其他外部 LLM SDK。
4. 不修改现有 auth、query、skills 主流程。
5. 不自动上传生成的 HTML 文件。

## 技术方案

### methods-card CLI

新增模块：

```text
opscli/methods_card/
├── __init__.py
├── cli.py
├── client.py
└── exceptions.py
```

注册命令：

```bash
opscli methods-card list --keyword "<keyword>" --page 1 --per-page 100 --pretty
opscli methods-card detail <card_id> --pretty
```

客户端通过 `AuthClient.build_request_auth("ops")` 复用现有登录态，请求：

- `GET {OPS_URL}/v1/ai/method-card`
- `GET {OPS_URL}/v1/ai/method-card/{id}`

### Skill 资源

新增/维护：

```text
opscli/skills/templates/ops-methods-card/
├── SKILL.md
├── 交叉表-1778233062511.xlsx
├── scripts/xlsx_preview.py
└── references/
    ├── 执行流程.md
    ├── 方法卡接口.md
    ├── 卡片.md
    └── 卡片输出示例.html
```

`xlsx_preview.py` 只解析本地 Excel，不访问网络，输出 JSON 摘要供分析使用。

## 验收标准

1. `opscli methods-card list` 会带认证信息请求列表接口。
2. `opscli methods-card detail` 会带认证信息请求详情接口。
3. Skill 文档明确要求先认证，再通过正式 CLI 获取列表和详情。
4. Skill 文档明确说明按用户输入、卡片标题/描述选择卡片。
5. Excel 预览脚本可读取默认 xlsx 并输出字段、预览行和数值统计。
6. HTML 报告输出路径固定到 `output/methods-card/`。
7. `opscli skills install ops-methods-card --skills-dir ".agents/skills"` 可安装到项目目录，并且安装结果不包含 Python 缓存文件。
