# Amazon Rufus 问题参数与拒答重试 Proposal

## 背景

`opscli amazon-rufus get <asin> <country>` 当前默认只走本地题库。用户需要两种获取 Rufus 答案的方式：未给明确问题时继续使用题库；给出明确问题时由 CLI 参数传入该问题。用户还要求分析 Rufus 答案是否拒答，如果拒答，则在保持原语义的情况下改写问题，改写问题限制在 180 字以内，改写后的重试问题必须使用中文，并最多重试 3 次。

## 范围

- 新增 `--question` 单题模式的 CLI/Skill 使用契约。
- 保留未传 `--question` 时的题库模式。
- 设计并实现拒答检测、180 字内问题改写、最多 3 次改写重试。
- 约束拒答后的改写重试问题必须使用中文。
- 更新项目级 `.agents/skills/ops-amazon-rufus/SKILL.md`，让 Agent 按用户意图选择单题模式或题库模式。

## 非目标

- 不新增新的 Rufus 子命令。
- 不把临时问题写回题库文件。
- 不引入外部 LLM 或远端改写 API。
- 不输出 seed request、headers、cookie 或完整内部 JSON。

## 设计摘要

1. `--question` 为空白时仍作为输入错误处理。
2. 有效 `--question` 跳过题库读取，直接执行单题。
3. 题库模式继续读取 `.agents/skills/ops-amazon-rufus/data/question_templates.json`。
4. 每题答案解析后执行拒答检测。
5. 命中拒答时，生成不超过 180 字的中文保语义问题并重试，最多重试 3 次。
6. 最终报告展示最终答案；发生改写时展示简短改写说明和改写后问题。

