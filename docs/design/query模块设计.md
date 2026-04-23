# opscli query 模块设计

> **版本：** v0.1  
> **日期：** 2026-04-22  
> **适用范围：** opscli 一期 AI 取数能力底座补全

---

## 1. 设计背景

当前一期实现已经具备以下能力：

- `auto-scheduler` 已提供 `cli-query`、`query-metadata`、`skill/export`、`publish` 等服务端接口
- `opscli skills` 已支持 `dataset-fields` Skill 的安装、升级、本地字段搜索和本地缓存管理
- 本地 `search.py -> query-metadata -> cli-query` 的链路已被验证可用

但目前仍存在一个关键缺口：

- `opscli` 还没有正式的 `query` 模块
- Skill 如果要真正发起查数，只能自己直连后端接口
- 这会导致认证、参数校验、payload 组装、错误映射散落在 Skill 脚本中

因此需要新增 `opscli query` 模块，把所有查询相关能力统一收口到 CLI。

---

## 2. 核心原则

### 2.1 单一远端入口原则

所有涉及远端元数据读取、查询执行的能力，都必须通过 `opscli` 调用后端服务。

正确链路：

```text
Skill / AI
   -> opscli query ...
   -> auto-scheduler API
   -> Python 查询服务
```

禁止链路：

```text
Skill / AI
   -> 直接 httpx 调用 auto-scheduler
```

### 2.2 Skill 只做本地辅助，不做远端调用

`dataset-fields` 等 Skill 只负责：

- 本地缓存读取
- 本地字段搜索
- 辅助构造查询参数

Skill 不负责：

- 携带 JWT / session
- 调用 `query-metadata`
- 调用 `cli-query`
- 解析服务端错误码

### 2.3 opscli 负责完整转发职责

`opscli query` 必须统一负责：

- 读取本地认证信息
- 组装请求头和 cookie
- 校验命令参数
- 构造和标准化查询 payload
- 请求转发
- 统一输出 JSON
- 错误码映射与提示

---

## 3. 模块目标

一期 `opscli query` 模块目标不是做自然语言查数，而是提供一个稳定的查询入口层，满足以下需求：

1. 让 Skill 不再直连后端 API
2. 让 AI/脚本/用户都通过 `opscli` 发起查询
3. 让服务端接口变化时，仅修改 `opscli query` 即可
4. 为后续更高层的自然语言查询能力预留稳定底座

---

## 4. 一期最小命令集

### 4.1 `opscli query metadata`

**作用：** 获取指定数据集的查询元数据，供 AI/Skill 构造查询时使用。

**一期建议参数：**

```bash
opscli query metadata --dataset ds_xxx
opscli query metadata --table-id 1103
opscli query metadata --pretty
```

**行为说明：**

- 优先支持按 `dataset_alias` 查询
- 同时支持按 `table_id` 查询
- 数据来源优先使用本地 `query_metadata.json`
- 如本地不存在或用户显式指定 `--remote`，再通过 `opscli` 转发调用远端接口

**默认 JSON 输出：**

```json
{
  "success": true,
  "command": "query metadata",
  "data": {
    "dataset": {
      "table_id": 1103,
      "dataset_alias": "ds_e93be345cfa1"
    },
    "fields": []
  },
  "error": null
}
```

### 4.2 `opscli query run`

**作用：** 执行标准查询请求，由 `opscli` 统一转发到服务端 `cli-query`。

**一期建议参数：**

```bash
opscli query run --payload payload.json
opscli query run --table-id 1103 --select ds_xxx.date_id
opscli query run --table-id 1103 --payload payload.json --pretty
```

**行为说明：**

- 一期优先支持 `--payload` 方式，先保证最小可用
- `opscli` 负责把 payload 标准化为服务端期望结构
- `opscli` 自动注入认证信息后转发到 `POST /api/v1/data-metrics/cli-query`

**默认 JSON 输出：**

```json
{
  "success": true,
  "command": "query run",
  "data": {
    "result": {},
    "meta": {}
  },
  "error": null
}
```

### 4.3 暂缓项：`opscli query build`

这个命令长期有价值，但一期不必马上实现。

后续可扩展为：

```bash
opscli query build --table-id 1103 --select ds_xxx.gmv --group-by ds_xxx.country_name
```

作用是把较友好的 CLI 参数组装为标准 query payload，再交给 `query run` 执行。

---

## 5. 推荐目录结构

新增模块目录：

```text
opscli/query/
├── __init__.py
├── cli.py
├── manager.py
├── client.py
├── models.py
└── exceptions.py
```

测试目录：

```text
tests/query/
├── test_cli.py
├── test_manager.py
└── test_client.py
```

职责建议：

- `cli.py`
  - Typer 命令定义
  - 参数解析
  - `--pretty` / 默认 JSON 输出
- `manager.py`
  - 查询主流程编排
  - 本地 metadata 读取
  - payload 校验与标准化
- `client.py`
  - 统一远端 HTTP 调用
  - JWT + session 注入
  - 状态码与业务码处理
- `models.py`
  - payload/result dataclass 或 TypedDict
- `exceptions.py`
  - `QueryError` 及其子类

---

## 6. 调用关系设计

### 6.1 metadata 查询

```text
opscli query metadata
   -> QueryManager.get_metadata()
   -> 优先读取本地 query_metadata.json
   -> 必要时 QueryClient.get_query_metadata()
```

### 6.2 查询执行

```text
opscli query run
   -> QueryManager.run()
   -> 校验 payload / table_id
   -> QueryClient.cli_query()
   -> auto-scheduler /api/v1/data-metrics/cli-query
```

### 6.3 Skill 调用方式

Skill 不再直接调远端 API，而是：

```text
Skill
   -> 调用 opscli query metadata
   -> 调用 opscli query run
```

这可以通过两种方式实现：

1. Skill 通过子进程调用 `opscli`
2. Skill 内部调用 `opscli.query` 对应 Python 模块

一期推荐优先支持第 2 种，让内部复用更稳定；若面向外部 AI 工具，则统一暴露 CLI 命令。

---

## 7. 认证与请求规范

### 7.1 认证来源

统一复用：

```python
from opscli.auth import AuthClient

headers, cookies = AuthClient().build_request_auth("ops")
```

### 7.2 请求格式

请求头：

```python
headers = {"Authorization": "Bearer <jwt>"}
```

Cookie：

```python
cookies = {
    "polarisUserToken": "<session_id>",
    "opscliDeviceCode": "<device_code>",  # 本地存在时自动附带
}
```

说明：

- `query` 模块不再自行拼接 `Authorization` / `Cookie`
- 统一通过 `AuthClient.build_request_auth("ops")` 获取认证参数
- 这样后续新增认证字段时，只需要在 `auth` 模块收口调整

### 7.3 服务地址来源

统一复用 `opscli.auth` 中对 `OPS_URL` 的读取逻辑，不在 `query` 模块中单独维护另一套配置来源。

---

## 8. 输出与错误处理

### 8.1 输出原则

保持与现有 `opscli skills` 一致：

- 默认输出 JSON
- `--pretty` 输出终端友好文本

### 8.2 错误分层

建议至少区分：

- `NOT_LOGGED_IN`
- `INVALID_PAYLOAD`
- `DATASET_NOT_FOUND`
- `QUERY_FORBIDDEN`
- `REMOTE_HTTP_ERROR`
- `REMOTE_BUSINESS_ERROR`
- `BAD_REMOTE_JSON`

### 8.3 服务端错误映射

例如：

- HTTP `401/403` -> 查询鉴权失败
- HTTP `200` 且 body `code=403` -> 业务权限失败
- HTTP `200` 且 body `code=404` -> 业务资源不存在

要避免把“HTTP 成功但业务失败”误判成成功，这个问题此前在 `skills manifest` 联调中已经出现过一次，`query` 模块必须一开始就规避。

---

## 9. 与现有 Skill 的边界重构

### 9.1 `dataset-fields` 保留职责

继续保留：

- `search.py`
- 本地 `dataset_fields.csv`
- 本地 `datasets.csv`
- 本地 `query_metadata.json`
- `updater.py`

### 9.2 `dataset-fields` 不再承担远端职责

后续若模板里需要“执行查询”能力，必须改成：

- 生成 payload
- 调用 `opscli query run`

而不是：

- 在 Skill 脚本里 `httpx.post(.../cli-query)`

---

## 10. 一期实现建议顺序

### 阶段 1：补最小骨架

1. 新增 `opscli/query/`
2. 在 [opscli/cli.py](/Users/mask/python3/opscli/opscli/cli.py) 注册 `query` 子命令
3. 先实现 `opscli query run --payload`
4. 补 `tests/query/test_cli.py`

### 阶段 2：补 metadata

1. 实现 `opscli query metadata`
2. 优先读取本地 `query_metadata.json`
3. 支持 `--dataset` / `--table-id`
4. 补 manager/client 测试

### 阶段 3：Skill 接入改造

1. 检查所有 Skill 模板脚本
2. 禁止任何脚本直连后端查询接口
3. 改为调用 `opscli query`

---

## 11. 非目标

一期 `opscli query` 不负责：

- 自然语言转 SQL
- 自动字段推荐
- 自动纠错查询意图
- 多轮对话式查询规划

这些能力可以建立在 `opscli query` 之上，但不应混进一期最小实现。

---

## 12. 设计结论

当前缺的不是服务端能力，而是 `opscli` 的统一查询入口层。

因此一期后续最合理的补齐方向是：

1. 增加 `opscli query` 模块
2. 先落 `query run --payload`
3. 再补 `query metadata`
4. 最后把 Skill 查询调用全部收敛到 `opscli query`

只有这样，才能满足“所有操作都必须经过 opscli，而不是直接暴露 API 给 Skill 调用”的设计原则。
