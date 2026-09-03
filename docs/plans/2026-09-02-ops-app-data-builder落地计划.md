# OPS 应用数据层构建 Skill 落地计划

> 日期：2026-09-02  
> 状态：已完成  
> 新 Skill：`ops-app-data-builder`  
> 替换 Skill：`ops-business-data-orchestrator`

## 1. 已确认决策

1. 新名称采用 `ops-app-data-builder`。
2. 删除旧 Skill，不保留兼容副本。
3. OPS viewer 数据默认实时查询，不写共享 SQLite。
4. Keepa 由站点后端通过正式 opscli REST API 调用。
5. SellerSprite 第一阶段只完成合同、Mock 和待接入边界。
6. 只生成 `docs/ops-app/data-spec.md`，暂不增加运行时 YAML。
7. 不自动生成 OPS 无人值守同步任务。
8. 删除并替换旧需求设计和旧落地计划。
9. 2026-09-03 起只支持 `opscli app create/init` 拉取的标准模板，不兼容旧数据层项目。
10. OPS 运行期统一复用模板 `QueryGateway`，不生成或引用 `opscli.app.sdk.OpsClient`。
11. 真实 OPS 数据集必须进入 `app.yaml.opscli.datasets` 白名单，测试统一使用 FakeGateway 和 dependency override。

## 2. 职责分层

```text
ops-app-build-spec
→ 识别站点结构、真实数据需求和违规调用
→ 委托 ops-app-data-builder

ops-app-data-builder
→ 验证真实数据合同
→ 选择 viewer-live / app-materialized / hybrid
→ 生成 FastAPI、前端 API、SQLite 迁移、测试和 data-spec

站点运行期
→ 只运行普通 FastAPI/Python/SQLite 代码
→ 不加载 Skill
```

## 3. 实施文件

### 3.1 新 Skill

- `opscli/skills/templates/ops-app-data-builder/SKILL.md`
- `opscli/skills/templates/ops-app-data-builder/references/data-layer-contract.md`
- `opscli/skills/templates/ops-app-data-builder/references/runtime-source-routing.md`
- `opscli/skills/templates/ops-app-data-builder/agents/openai.yaml`
- `opscli/skills/templates/ops-app-data-builder/data/VERSION.json`

### 3.2 建站规范

- 新增 `opscli/skills/templates/ops-app-build-spec/references/data-access-standard.md`
- 修改 `opscli/skills/templates/ops-app-build-spec/SKILL.md`
- 升级 `ops-app-build-spec` 版本

### 3.3 接入与验证

- 更新 `opscli/skills/templates/manifest.json`
- 新增 `opscli/skills/evals/cases/ops-app-data-builder.json`
- 新增 `tests/skills/test_ops_app_data_builder_skill.py`
- 更新 `tests/skills/test_ops_app_build_spec_skill.py`
- 删除旧 Skill、旧测试、旧 eval 和旧设计文档

## 4. 数据源落地规则

### OPS

- 开发期使用 `ops-dataset-query` 或 `ops-query-wizard` 验证合同。
- 运行期固定复用标准模板 `backend.core.auth.get_query_gateway` 和 `backend.clients.ops_query_client.QueryGateway`。
- AppHub 线上由 `ViewerQueryGateway` 使用 `X-Ops-Token`；业务 API 通过 `Depends(get_query_gateway)` 注入 Gateway。
- 缺少标准 QueryGateway 文件、类或方法时停止并提示重新执行模板初始化，不兼容旧适配器。
- 真实数据集同步加入 `app.yaml.opscli.datasets`；测试使用 FakeGateway 和 dependency override。
- 默认 `viewer-live`，不把未隔离 viewer 结果写入共享 SQLite。

### Keepa

- 开发期使用 `ops-keepa` 验证场景和样本。
- 运行期由站点后端使用 `OPSCLI_API_BASE_URL`、`OPSCLI_API_KEY` 调用正式 Keepa REST 端点。
- 当前只使用正式文档声明的 scenarios 和 run，不猜测任务轮询或下载端点。

### SellerSprite

- 开发期使用 `ops-seller-sprite` 验证合同。
- 第一阶段生成 schema、Mock、站点 API 合同、SQLite 设计和阻塞说明。
- 标准模板没有 SellerSprite Gateway，第一阶段不生成线上调用，也不复用旧项目私有适配器。

## 5. 验证顺序

1. 运行两个 Skill 的 `quick_validate.py`。
2. 运行新 Skill 与 `ops-app-build-spec` 定向 pytest。
3. 运行 manifest 和 packaging 测试。
4. 运行 `ops-app-data-builder` 静态 eval。
5. 搜索旧名称、敏感值、伪造端点和本机绝对路径。

## 6. 完成标准

- 新 Skill 可以被发现、安装和正确打包。
- `ops-app-build-spec` 可以识别真实数据需求并委托新 Skill。
- 三类数据源边界与已同步 API/SDK 规范一致。
- 前端只调用站点 `/api`，数据加工进入 FastAPI service。
- SQLite、凭证、viewer 权限和 SellerSprite 缺口均有硬边界。
- 测试、validator、manifest 和静态 eval 全部通过。
