# Amazon Rufus 回答质量重试机制

## 背景

当前 `ops-amazon-rufus` 在 `amazon_rufus_get` 成功后只返回本次 `report_path`。如果 Rufus 未回答、拒答，或回答内容明显偏离问题意图，例如用户询问风险/评价/适配性但回答退化为商品详情，现有 Skill 没有要求 Agent 改写问题并重试。

## 目标

在 Skill 编排规则中新增回答质量判断和问题改写重试流程：

1. 每次 Rufus 获取成功后读取本次 `report_path` 做回答质量判断。
2. 对无回答、拒答、答非所问、复杂问题退化为商品详情的问题触发改写。
3. 开启子 agent，使用固定提示词改写问题：`重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。`
4. 使用改写后的问题重新调用 Rufus。
5. 多问题获取保持在同一个 Rufus 对话中，不拆成多个独立对话。
6. 使用 `answer_rewrite_attempts_by_question` 按问题分别记录，每个问题最多 5 次。

## 非目标

1. 不在 Skill 目录新增 Python 获取脚本。
2. 不把子 agent 能力下沉到 `opscli` 后端。
3. 不改变 MCP 登录恢复、远程授权偏好、CLI fallback 白名单和敏感信息隐藏规则。
4. 不读取历史报告作为重试判断依据。

## 影响范围

- `.agents/skills/ops-amazon-rufus/`
- `opscli/skills/templates/ops-amazon-rufus/`
- `output/amazon-rufus-skill-*`
- `tests/skills/test_ops_amazon_rufus_updater.py`
