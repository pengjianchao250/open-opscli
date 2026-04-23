# ops-amazon Skill 规划方案

## 1. 目标

基于现有 `opscli amazon` 模块，新增一个可安装的内置 Skill：`ops-amazon`。

它的核心职责不是重复实现抓取逻辑，而是把 AI 使用 Amazon 抓取能力的工作方式标准化：

- 什么时候该用 `scrape`
- 什么时候该用 `payload`
- 什么时候该用 `search`
- 如何基于真实样本做 ops API 和数据表设计

## 2. 设计原则

### 2.1 轻模板优先

`ops-amazon` 应优先采用 `ops-auth` / `ops-skills` 这种轻模板结构，而不是 `ops-dataset-query` 这种重模板结构。

原因：

- Amazon 抓取的核心能力已经在 `opscli amazon` 模块里
- 当前不需要本地大索引数据文件
- 当前不需要 Skill 自带独立脚本来补充正式命令

因此，一期只保留：

- `SKILL.md`
- `data/VERSION.json`

## 3. 技能职责边界

### 3.1 Skill 应负责

- 指导 AI 识别何时使用 Amazon 抓取能力
- 指导 AI 通过 `opscli amazon` 命令进行标准化抓取
- 约束 AI 在后端设计场景下优先输出真实样本、字段契约和 payload
- 统一字段口径认知，例如商品页评论数是精确值、搜索页评论数通常是近似值

### 3.2 Skill 不应负责

- 直接访问 Amazon HTTP 接口
- 自己维护一套独立 Playwright 脚本
- 自己调用 ops API
- 在 Skill 侧实现调度、重试、批量编排

这些能力应继续沉淀在 `opscli amazon` 模块中，Skill 只做 AI 工作流指引。

## 4. 推荐目录结构

```text
opscli/skills/templates/ops-amazon/
├── SKILL.md
└── data/
    └── VERSION.json
```

后续如果需要扩展，再考虑增加：

```text
opscli/skills/templates/ops-amazon/
├── references/
│   ├── 字段说明.md
│   └── API样本.md
└── scripts/
    └── sample.sh
```

但一期不建议提前加重。

## 5. 一期功能范围

`ops-amazon` 一期建议覆盖以下场景：

### 5.1 商品页取样

通过：

```bash
opscli amazon scrape --asin <ASIN> --include-raw --pretty
opscli amazon payload --asin <ASIN> --pretty
```

用于：

- 商品快照字段确认
- API 请求体设计
- 数据表字段设计

### 5.2 搜索结果取样

通过：

```bash
opscli amazon search --keyword "<keyword>" --limit 10 --pretty
opscli amazon schema --pretty
```

用于：

- 搜索批次表设计
- 搜索结果表设计
- 竞品样本分析

### 5.3 历史追踪

通过：

```bash
opscli amazon history --asin <ASIN> --pretty
```

用于：

- 价格变化查看
- 评论数变化查看
- 商品历史补数检查

## 6. 与 `ops-dataset-query` 的关系

用户提到参考 `ops-dataset-query`，这里建议“参考的是模板接入方式”，不是“复制其数据结构”。

应复用的点：

- 作为内置 Skill 放在 `opscli/skills/templates/`
- 通过 `data/VERSION.json` 接入 `skills install`
- 在 `SKILL.md` 中明确命令用法和边界

不应照搬的点：

- `data/` 下的本地索引数据文件
- 自带的查询搜索脚本
- 远端升级能力

因为 Amazon 场景当前没有本地字段索引更新需求。

## 7. 后续演进建议

### 7.1 第二阶段

当 `opscli amazon` 增加以下能力后，`ops-amazon` 可同步扩展：

- `submit` 命令
- 批量任务抓取
- 定时调度
- 批次级幂等提交

### 7.2 第三阶段

如果 Amazon 数据字段持续增多，再考虑给 Skill 增加：

- `references/`：字段语义和示例文档
- `scripts/`：辅助生成样本或比对历史的轻脚本

## 8. 实施结果

本轮建议的落地结果应包括：

1. 创建内置模板目录 `opscli/skills/templates/ops-amazon/`
2. 新增 `SKILL.md`
3. 新增 `data/VERSION.json`
4. 同步 README / `ops-skills` 相关说明，告知 `ops-amazon` 已成为可安装内置 Skill

## 9. 推荐下一步

在模板已创建的前提下，下一步建议继续做两件事：

1. 把 `ops-amazon` 加入 README 和 `ops-skills` 文档中的内置 Skill 列表
2. 补一个 `tests/skills/test_manager.py` 安装测试，确保 `opscli skills install ops-amazon` 持续可用
