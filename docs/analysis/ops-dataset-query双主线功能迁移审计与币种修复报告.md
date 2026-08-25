# ops-dataset-query 双主线功能迁移审计与币种修复报告

> 审计日期：2026-08-20
> 审计对象：Skill 版 `ops-dataset-query/scripts` 与内核版
> `opscli.query.services.planner`、CLI/MCP `query flow` 入口

## 一、结论

本次“使用欧元查询但服务端未收到币种”的根因在客户端规划层：正式
`opscli query flow` 已使用内核规划器，而单币种、多币种能力此前只提交到了 Skill
版 `scripts/query_plan.py` 和 Skill 执行脚本；内核生成的 `query_template` 因而没有
`globalCurrency`。`QueryManager.run_query_template()` 会原样转发模板字段，服务端不是
本次丢参点。

修复后，规划与执行主链已经补齐币种能力：明确币种写入完整性封存前的模板；多币种
只规划一次，按 `query_templates` 分别调用服务端，并核验实际返回币种。单币种、
多币种、逐币种执行、Schema/规则资源和双主线规划均已增加自动化守卫。

“Skill 版本所有功能是否已迁入内核”的准确答案是：**规划与正式取数主链已具备等价
能力，但整个 Skill 工具箱没有、也不应整体迁入规划器内核。** 图表分析、Excel 导出、
本地降级和脚本启动兼容层属于消费端或降级端，继续留在 Skill 侧是有意的架构边界，
不能记作规划器漏迁。

## 二、落地方案与执行状态

| 阶段 | 落地内容 | 状态 |
|---|---|---|
| 1. 复现与定界 | 对比实际 CLI 导入路径、模板转发链、提交历史和双主线实现 | 完成 |
| 2. 合同补齐 | 内核增加币种识别、`globalCurrency`、多币种模板及 Schema 字段 | 完成 |
| 3. 执行补齐 | 内核 `run_flow` 对完整性绑定的多币种模板逐项执行、独立落盘并核验返回币种 | 完成 |
| 4. 防漂移 | parity 增加币种字段与模板数量；Schema、意图规则改为逐字段对拍 | 完成 |
| 5. 文档收口 | CLI、MCP、内核入口、QUERY_SPEC 统一描述单/多币种执行语义 | 完成 |
| 6. 验收 | 相关自动化测试及真实 EUR 查询，检查请求模板与返回披露 | 完成 |

真实查询已确认模板发送 `globalCurrency=EUR`，返回 `meta.currency=EUR`，
2026-07-22 至 2026-08-20 销售额合计为 `435706.63666151 EUR`。

## 三、功能迁移矩阵

| Skill 能力模块 | 内核对应实现 | 结论 |
|---|---|---|
| `query_plan.py` 自然语言选表、字段、时间、筛选、排序、TopN | `planner/query_plan.py` | 已迁；本次补齐单/多币种 |
| `time_scope.py` | 同名内核模块 | 已迁，双主线测试覆盖 |
| `typed_schema_linking.py`、`field_semantics.py` | 同名内核模块 | 已迁 |
| `dataset_guidance.py`、`agent_query_planner.py` | 同名内核模块 | 已迁；内核另有覆盖校验加固 |
| `enum_cache.py`、组件筛选解析 | 同名模块 + `MetadataAdapter` 回调 | 能力已迁，I/O 方式不同 |
| `scoped_metadata_index.py`、`scoped_dataset_reader.py` | 索引模块 + `metadata_cache.py` / `MetadataAdapter` | 能力已替换，不做 CSV 代码照搬 |
| `plan_integrity.py`、`evidence_contract.py` | 同名内核模块 | 已迁；Skill 的 CLI `main` 不属于业务能力 |
| `query_flow.py`、`run_query.py` 正式执行 | `planner/entry.py` + `QueryManager` | 已迁；包含完整性、分页补齐、排序兜底、证据、预览/落盘与多币种 |
| `data/intent_rules.json`、`query_plan.schema.json` | 内核 package resources | 已迁且新增逐字段一致性守卫 |
| `chart_analyze*`、`chart_map*`、`chart_data_loader.py` | 无规划器内核对应物 | 有意保留：图表结果消费支线 |
| `excel_export*` | 无规划器内核对应物 | 有意保留：文件输出适配器 |
| `local_fallback.py` | 无正式主链对应物 | 有意保留：离线/失败降级，不得混入权威取数主链 |
| `core.py` | CLI/MCP 原生调用和 Python 服务层 | 有意替换：Skill 子进程、编码和脚本兼容层无需迁入 |

## 四、仍存在的差异及其性质

共同模块的纯函数并非全部逐行相同，但剩余差异可分为两类：

1. 内核专属：`_ensure_ready_adapter`、资源包读取、领域覆盖校验。这些用于后端元数据
   缓存、依赖方向和内核健壮性，属于迁移后的正向替代。
2. Skill 专属：CSV 就绪检查、升级进程标记、数据目录回退、脚本参数解析、子进程枚举
   包装等。这些服务于可独立运行的 Skill/历史离线形态；内核以缓存适配器和注入回调
   替代，不应复制进去。

因此后续审计应以“同输入下的稳定合同和执行结果等价”为准，而不是以文件数、函数名
或代码行完全相同为准。本次缺陷正是旧 parity 只比对表、维度、指标、筛选、排序和
limit，漏掉 `globalCurrency` 与 `query_templates` 所致；对应盲区现已封堵。

## 五、后续治理准则

- 新增规划合同字段时，必须同时修改 Skill/内核 Schema，并加入 parity 断言。
- 任何自然语言语义能力变更，必须同时覆盖 Skill 与内核规划用例，或明确宣布 Skill
  路径退役，禁止只改一侧。
- 正式 CLI/MCP 行为以内核入口为权威；Skill 辅助脚本不得成为主命令的隐式依赖。
- 图表、Excel、本地降级若未来要产品化，应迁入各自服务层，不应继续膨胀 planner。
