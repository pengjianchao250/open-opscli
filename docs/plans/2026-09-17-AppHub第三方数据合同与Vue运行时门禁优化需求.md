# AppHub 第三方数据合同与 Vue 运行时门禁优化需求

> 日期：2026-09-17  
> 状态：已实施  
> 范围：`ops-app-build-spec`、`ops-app-data-builder`、共享 AppHub 数据合同校验服务及专项测试

## 1. 背景

AppHub 真实站点联调暴露出两类可重复问题：

1. 页面使用 Vue 组件对象的字符串 `template`。统一模板使用 Vue runtime-only 构建，生产构建可以成功，但浏览器运行时无法编译模板，最终只显示模块标题而不显示内容。
2. Keepa 和 SellerSprite 虽然要求在线验证场景和返回结构，但交付校验器只强制检查 OPS 的字段合同。第三方数据产品可以在没有精确记录路径和字段映射的情况下生成投影代码，导致 Keepa 正式返回 `data.data[]` 时，站点仍按旧的 `data.products` 结构解析。

这两类问题不能依赖用户逐站点提醒修复，必须进入通用 Skill 规范、机器可执行门禁和回归测试。

## 2. 目标

1. 禁止在统一 Vue runtime-only 模板中生成需要运行时编译的字符串模板组件。
2. 在测试和生产构建之外提供可执行的前端合同检查。
3. 让 Keepa、SellerSprite 与 OPS 一样固化精确技术合同和业务字段映射。
4. 只保存脱敏结构证据，不保存真实商品行、导出结果、凭证或临时下载地址。
5. 第三方响应先完成投影和必填字段校验，再保存快照并标记成功。
6. 上游结构变化时返回稳定降级状态，并保留最后一次有效快照。
7. 保持 `opscli app create/init/dev/push` 的命令行为不变。

## 3. 非目标

- 不修改 OPS、Keepa、SellerSprite 的线上接口路径和鉴权模式。
- 不修改 SQLite 表结构或 Alembic 迁移。
- 不让前端直连第三方数据服务。
- 不把具体站点的部门、ASIN、标题或商品数据写入通用规则。
- 不在 `opscli app dev` 中嵌入 Vue 或第三方业务语义。

## 4. Vue runtime-only 前端合同

- 组件视图使用 SFC 顶层 `<template>`、独立 `.vue` 组件或 render function。
- 禁止组件对象中的字符串 `template`。
- 禁止调用 `Vue.compile`，也禁止从 `vue` 导入运行时 `compile`。
- 构建通过不等于页面运行正常；浏览器验收必须检查 Vue warning 和业务模块正文。
- `ops-app-build-spec` 提供脚本扫描 `frontend/src` 的 `.vue/.js/.jsx/.ts/.tsx`。
- `.vue` 文件只扫描 `<script>` 内容，不误判 SFC 顶层 `<template>`。

## 5. 第三方数据合同 1.1

OPS-only 合同继续兼容 `schema_version=1.0`。包含已验证 Keepa 或 SellerSprite 数据产品时，必须使用 `schema_version=1.1`。

已验证第三方产品的 `technical_contract` 至少包含：

```json
{
  "scenario": "product",
  "site": "US",
  "result_format": "json",
  "response_shape": {
    "records_path": "$.data.data[*]",
    "record_type": "object"
  },
  "required_business_roles": ["title", "price", "bsr"],
  "fields": {
    "title": {
      "source_field": "title",
      "source_path": "$.data.data[*].title",
      "result_field": "title",
      "data_type": "string"
    }
  },
  "projection_policy": {
    "validate_before_snapshot": true,
    "on_schema_mismatch": "degraded_preserve_snapshot"
  }
}
```

SellerSprite 的 `response_shape` 还必须声明 `columns_path`，字段映射使用在线验证得到的正式列名。

## 6. 脱敏结构证据

第三方 `verification` 增加 `shape_evidence`：

```json
{
  "records_path": "$.data.data[*]",
  "record_type": "object",
  "observed_fields": ["title", "currentAmazonPrice", "currentSalesRank"]
}
```

结构证据只允许记录路径、容器类型和字段名。校验器必须确认技术合同与证据路径、类型一致，并确认每个页面字段的 `source_field` 出现在 `observed_fields`。

## 7. 运行时生成规则

1. HTTP 状态和响应 `success` 成功后先提取业务记录。
2. 按已验证合同投影页面字段并校验必填业务角色。
3. 校验通过后才保存新快照和标记来源 `success`。
4. 路径或字段不匹配时标记 `degraded`，并保留最后一次有效快照。
5. 在线验证处于 `degraded` 时可以生成传输、任务和缓存基础设施，但不得根据历史项目或相似字段生成正式投影器。

## 8. 分层职责

- `ops-app-build-spec`：维护 Vue runtime-only 红线、前端合同脚本和浏览器验收门禁。
- `ops-app-data-builder`：维护第三方结构证据、字段映射和运行时投影规则。
- `opscli.app.services.data_contracts`：作为共享校验事实源，支持 1.0/1.1 兼容规则，不改变 App CLI 命令行为。

## 9. 验收标准

1. 字符串组件 `template`、`Vue.compile` 和从 `vue` 导入 `compile` 均被拒绝。
2. 标准 SFC 顶层 `<template>` 可以通过。
3. OPS-only 的 1.0 合同保持兼容。
4. 已验证 Keepa/SellerSprite 合同使用 1.0 时返回升级提示。
5. Keepa 正式 `$.data.data[*]` 结构和标题、价格、BSR 映射可以通过。
6. SellerSprite `columns + rows` 结构和业务列映射可以通过。
7. 第三方合同缺少路径、结构证据、业务角色或字段映射时失败。
8. 技术合同字段未出现在脱敏结构证据时失败。
9. 两个 Skill 的版本、安装资产、默认提示和静态 eval 保持一致。
10. 不修改 `opscli app create/init/dev/push` 行为。

## 10. 回滚

前端合同脚本和第三方 1.1 合同校验可以分别回滚。OPS-only 1.0 合同、App CLI 命令、认证、查询和第三方运行接口不受影响。
