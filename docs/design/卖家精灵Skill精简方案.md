# 卖家精灵 Skill 精简方案

## 背景

`ops-seller-sprite` 当前的 `SKILL.md` 与 `SKILL_MCP.md` 同时承担了触发说明、执行工作流、异步任务规则、场景映射、参数词典、枚举值、类目解析、回复模板和示例库等多种职责，导致两个问题：

1. 主文档过长，Agent 进入 Skill 后需要先吞下大量低频细节。
2. `SKILL.md` 与 `SKILL_MCP.md` 大段重复，维护时容易漂移。

## 精简目标

1. 把两份主文档收敛为“入口文档”，只保留执行当前任务必须先知道的规则。
2. 把场景映射、参数词典、别名、默认值、类目规则统一收敛到单一参考文件。
3. 不改变现有能力边界，不牺牲缺参澄清、类目确认、异步跟进和结果回复成功率。

## 目标结构

### `opscli/skills/templates/ops-seller-sprite/SKILL.md`

保留：

- Skill 作用和触发范围
- 最小执行流程
- 缺参澄清原则
- 公共参数默认值
- 对外回复边界
- 进一步阅读入口

删除并下沉：

- 大段场景参数表
- 推荐模式和枚举值清单
- 官方别名映射
- 长 JSON 示例
- MCP 轮询细节

### `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`

保留：

- MCP tools 列表
- `run -> status -> export` 调用链
- 异步任务轮询与续查规则
- MCP 下禁止传入的控制参数
- 认证缓存和运行时边界
- 结果回复模板

删除并下沉：

- 与 `SKILL.md` 重复的参数词典
- 长参数表和长示例

### `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`

升级为唯一参数手册，集中保留：

- 场景映射表
- 公共参数和默认值
- 缺参澄清规则
- 各 scenario 的必填与常用可选参数
- `product-research` / `market-research` 的重点字段、推荐模式、枚举值、官方别名
- 类目解析规则

## 设计原则

1. 主文档只保留高频、先决、易错规则。
2. 参数类知识只有一个权威来源，避免双写。
3. 高风险规则保持一跳可达，不做多层跳转。
4. 不为“看起来完整”保留低价值示例。

## 预期结果

1. `SKILL.md` 和 `SKILL_MCP.md` 的长度明显下降。
2. Agent 进入 Skill 后先拿到工作流，再按需读取参数手册。
3. 后续维护参数口径时，只需更新 `SCENARIO_PARAMS_ZH.md` 一处。
