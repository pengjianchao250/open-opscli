# 站点数据层合同

用于把页面需求转换为可实现、可测试的数据产品合同。只记录已经由项目证据或对应数据 Skill 验证的内容；未验证项必须明确标记。

## 1. 数据产品结构

每个数据产品至少包含以下字段：

```json
{
  "product_key": "inventory_risk",
  "business_purpose": "识别需要优先处理的库存风险商品",
  "consumers": ["inventory-risk-page"],
  "source": "ops",
  "contract_status": "verified",
  "execution_mode": "viewer-live",
  "grain": ["site", "asin"],
  "natural_key": ["site", "asin", "snapshot_date"],
  "dimensions": ["site", "asin"],
  "metrics": ["available_inventory", "turnover_days"],
  "filters": ["site", "snapshot_date"],
  "freshness": "request-time",
  "runtime_gateway": "QueryGateway",
  "app_yaml_datasets": ["verified_dataset_alias"],
  "site_api": "GET /api/inventory/risks",
  "storage": null,
  "limitations": []
}
```

示例中的业务字段是合同形状示意，不代表真实 OPS 字段。实际数据集、字段和口径必须由对应数据 Skill 验证后写入项目 data-spec。

## 2. 合同状态

| 状态 | 含义 |
| --- | --- |
| `draft` | 业务目标已识别，尚未验证真实来源 |
| `verified` | 来源、字段或场景、参数和少量样本已验证 |
| `blocked` | 运行时适配器、权限或正式端点缺失 |
| `mock-only` | 只允许前端联调和测试，不代表线上可取数 |

不得用一个总状态覆盖所有数据产品。多来源产品要分别记录每个来源的状态。

## 3. 必须确认的合同项

### 3.1 业务语义

- 业务用途和页面消费者。
- 对象范围、站点、币种、时区和时间范围。
- 粒度、维度、指标、筛选和排序。
- 指标口径、聚合方式、空值和重复值语义。

### 3.2 查询与响应

- 真实数据集或第三方场景。
- 标准模板 `QueryGateway` 方法：`list_datasets`、`get_dataset_metadata`、`build_simple` 或 `build_simple_and_run`。
- `app.yaml.opscli.datasets` 中与真实数据集一致的白名单项。
- 请求参数、返回字段和嵌套结构。
- 分页、截断、总量、超时和额度限制。
- 自然键、幂等键和重复执行行为。
- 空结果、部分结果和上游错误的稳定映射。

### 3.3 新鲜度与存储

- `request-time`、固定有效期或业务刷新周期。
- 是否允许共享、是否依赖当前 viewer 权限。
- SQLite 表、唯一约束、索引、更新时间和过期清理策略。
- 物化失败时保留旧快照、返回降级结果或明确失败的策略。

## 4. 站点 API 合同

站点 API 统一位于 `/api`，前端不得感知上游系统地址、密钥或认证方式。

每个 API 至少定义：

- 方法、路径和用途。
- query/path/body 参数及校验。
- Pydantic 请求、响应和错误 schema。
- 数据新鲜度、分页和截断元数据。
- viewer 身份要求和缓存策略。
- 上游失败、无权限、空数据和超时的 HTTP 状态与业务 code。

路由只做协议转换。来源调用进入 client，业务组合进入 service，SQLite 进入 repository。

OPS 路由必须通过 FastAPI `Depends(get_query_gateway)` 获取 `QueryGateway`。业务 service 通过参数接收 Gateway，不得自行解析 `X-Ops-Token`、`X-Session-Id`，也不得直接创建 `AuthClient`、`QueryManager` 或另一套 Viewer Client。

## 5. 二次加工合同

跨字段或跨来源加工必须写明：

- 输入数据产品和前置状态。
- join key、时间对齐、站点和币种对齐。
- 去重、缺失、异常值和单位转换。
- 公式、舍入、排序和阈值。
- 部分来源失败时是否允许返回部分结果。

加工规则只实现已确认的业务语义，不从样本数据反推永久规则。

## 6. SQLite 合同

允许保存共享第三方数据、用户录入、配置、标签、备注、公共加工结果、新鲜度和同步记录。

默认禁止保存未隔离的 OPS viewer 结果、凭证、大文件、大型 BLOB 和高频队列数据。

写入要求：

- Compose 只有一个写入实例。
- 网络请求在数据库事务外完成。
- 使用短事务、参数化查询或 ORM、批量写入和唯一约束。
- 结构变化使用可审查迁移，不删除数据库重建。
- 缓存类表记录来源时间、抓取时间、过期时间和清理策略。

## 7. 测试合同

至少覆盖：

- client 请求合同和统一错误映射。
- FastAPI dependency override 注入 FakeGateway，证明测试不访问真实 SDK、网络、本机登录态或用户数据库。
- `app.yaml.opscli.datasets` 覆盖已验证 OPS 数据集。
- service 加工、join、空值和部分失败。
- repository 唯一约束、更新语义和迁移。
- API 参数校验、权限、空数据、分页和截断。
- Pydantic Schema 与前端类型的一致性。
- Mock 与真实合同字段保持一致，但不包含真实业务数据。

测试不得访问真实网络、真实账号、真实凭证或用户本地数据库。

## 8. `data-spec.md` 建议结构

```text
1. 页面与数据产品
2. 数据源和验证证据
3. 字段、粒度与业务口径
4. 执行模式与身份边界
5. QueryGateway 与 app.yaml 数据集白名单
6. 站点 API 与错误合同
7. 二次加工规则
8. SQLite 模型、迁移与清理
9. 新鲜度、分页、额度与超时
10. 环境变量与 Secret
11. Mock 与测试
12. 阻塞项和待接入能力
```

第一阶段只生成 Markdown 规范，不新增运行时 YAML。
