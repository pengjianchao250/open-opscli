# listing-rufus-trigger Proposal

## 背景

`ops-amazon-rufus` 当前 Skill 描述覆盖 Rufus、ASIN 问答、题库模式、单题模式和报告格式化，但没有覆盖用户常用的 `listing` 语义。用户表达“用 listing”“listing 分析”“listing 优化”时，Agent 可能不会加载 Rufus Skill。

仓库中同时存在 `ops-amazon-listing-analysis`，其职责是基于卖家精灵采集材料做 Listing 表达与一致性优化。因此本变更只让 `listing` 在 Rufus/ASIN 商品页问答语境下触发 `ops-amazon-rufus`，不把所有 Listing 任务都导向 Rufus。

## 目标

1. 增强 `ops-amazon-rufus` 的 frontmatter `description`，覆盖 `Amazon Listing`、`listing 商品页`、`listing 分析`、`listing 优化` 等触发词。
2. 在 Skill 正文新增触发范围说明，明确 Rufus Listing 场景和 `ops-amazon-listing-analysis` 的职责边界。
3. 同步更新内置模板与当前 `.agents` 安装副本。
4. 增加轻量测试，防止后续修改丢失 listing 触发词或边界说明。

## 非目标

1. 不改 `opscli amazon-rufus get` CLI 参数、Manager、Replay、Parser 或题库数据。
2. 不新增自然语言路由代码。
3. 不修改 `ops-amazon-listing-analysis`。
4. 不处理 `listing_uuid` 数据查询或权限字段。
5. 不变更 `VERSION.json`，除非后续发版治理单独要求。

## 方案

采用文档触发层最小变更：

1. 更新 `opscli/skills/templates/ops-amazon-rufus/SKILL.md`。
2. 更新 `.agents/skills/ops-amazon-rufus/SKILL.md`。
3. 在 `tests/skills/test_manager.py` 增加模板/安装副本文本断言，覆盖：
   - frontmatter 包含 `listing`。
   - 正文包含 `触发范围`。
   - 正文明确提到 `ops-amazon-listing-analysis`。
4. 更新 `docs/change-log-pending.md` 记录本次变更。

## 风险与控制

1. 风险：泛化 listing 触发导致误用 Rufus。
   控制：description 和正文都绑定 Rufus/ASIN 商品页问答、诊断或报告语境。
2. 风险：模板和 `.agents` 副本不一致。
   控制：测试同时读取两份文件。
3. 风险：扩大运行链路影响面。
   控制：不修改 Python 运行时代码和题库文件。

## 验收

1. `rg -n "listing|Listing|触发范围|ops-amazon-listing-analysis" ".agents/skills/ops-amazon-rufus/SKILL.md" "opscli/skills/templates/ops-amazon-rufus/SKILL.md"` 命中预期内容。
2. `pytest tests/skills/test_manager.py tests/skills/test_cli.py -v` 通过。
3. `git diff --check` 无空白错误。
