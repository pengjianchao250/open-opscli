# 新品计算器 Skill 优化调研

## 1. 调研目标

在不改变 `opscli calculator` CLI 行为、不修改 Skill 版本号的前提下，同时改善：

- 主 `SKILL.md` 的上下文占用与可扫描性。
- 新建草稿、继续草稿、查询结果三类任务的执行完整性。
- 触发描述、按需加载和测试契约的可验证性。

## 2. 当前状态

目标目录：

```text
opscli/skills/templates/ops-new-product-calculator/
├── SKILL.md
└── data/VERSION.json
```

现状数据：

- `SKILL.md` 共 318 行、15124 字节。
- `VERSION.json` 为 `v0.0.1`。
- 聚焦测试 `tests/skills/test_ops_new_product_calculator_skill.py` 共 8 项，当前全部通过。
- CLI 实际提供 `search-category`、`recommend`、`draft`、`show`、`validate`、`submit`、`dropdown-list`、`zones`、`list`、`detail`、`copy`。

## 3. 发现

### 3.1 主文件职责过多

主文件同时承载：

- 触发条件和硬性规则。
- 完整端到端工作流。
- 第二阶段字段说明。
- 30 余字段的 JSON 烟测示例。
- 查询结果表格契约。
- 常见问题和回复示例。

其中完整 JSON、字段映射和结果模板只在特定分支需要，却在 Skill 每次触发时全部进入上下文。

### 3.2 重复信息削弱规则优先级

以下内容在多个章节重复出现：

- 使用 CSV 而不是直接编辑 JSON。
- 不愿本地填写时改用 Web。
- 非认证失败提交 `ops-feedback`。
- 最终结果必须保留完整费用表。

重复并未形成更明确的结构，反而增加 Agent 从长文中提取当前步骤的成本。

### 3.3 工作流入口不清晰

现有文档主要按“从头生成草稿”顺序编排，但触发场景还包括：

- 用户已有草稿目录，需要查看、校验或提交。
- 用户已有任务编号，需要查询或复制草稿。

缺少入口分流会让 Agent 在已有任务场景仍从下拉项开始执行。

### 3.4 CLI 能力覆盖不完整

现有 Skill 没有说明：

- `opscli calculator show <草稿路径>`：查看已有草稿。
- `opscli calculator copy --task-code ...`：从既有任务复制草稿。

这与 CLI 的实际能力不一致。

### 3.5 测试偏重关键词存在

当前测试能防止关键规则被误删，但不能验证：

- 主文件是否按需引用详细资料。
- 详细参考文件是否存在。
- 完整 JSON 是否从主上下文移出且仍通过真实校验。
- 三类入口是否完整。
- `show` / `copy` 是否覆盖。
- 主文件是否重新膨胀。

## 4. 外部规范结论

Agent Skills 规范要求 `SKILL.md` 由 YAML frontmatter 和 Markdown 正文组成，并支持 `references/` 作为按需加载的参考目录。官方最佳实践建议把主文件控制在 500 行、5000 tokens 以内，并将只在特定场景需要的详细内容移到引用文件，同时明确“何时读取”。

OpenAI 的 Skills 指南将 Skill 定义为可复用工作流，建议明确输入、步骤、输出格式和最终检查；复杂工作流应优先拆成可组合、边界清晰的单元。

参考：

- Agent Skills Specification: https://agentskills.io/specification
- Agent Skills Best Practices: https://agentskills.io/skill-creation/best-practices
- Agent Skills Description Optimization: https://agentskills.io/skill-creation/optimizing-descriptions
- OpenAI Academy - Using skills: https://openai.com/academy/skills/

## 5. 仓库内对比

`ops-feedback` 和 `ops-amazon-product-data` 表明当前仓库已采用：

- frontmatter 只保留 `name`、`description`。
- 核心路径在主文档中给出明确默认值。
- 对运行路径、失败反馈和用户回复边界进行结构化约束。

本次继续沿用这些约定，不引入新的 Skill 元数据体系或执行脚本。

## 6. 结论

推荐采用渐进式拆分：

1. 主 `SKILL.md` 保留入口路由、认证、核心门禁、命令速查和失败处理。
2. `references/draft-workflow.md` 承载草稿生成、CSV、字段规则和完整 JSON。
3. `references/result-workflow.md` 承载 `list`、`detail`、`copy`、费用表输出和查询排障。
4. 用失败优先的契约测试验证引用边界、命令覆盖和真实 JSON 校验。
5. 保持 `data/VERSION.json` 为 `v0.0.1`。

