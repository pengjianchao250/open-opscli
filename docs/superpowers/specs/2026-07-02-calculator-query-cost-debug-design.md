# 新品计算器 queryCost 调试可见性设计

## 背景

Web 端新品计算器在第一步完成并点击“确定”后，会调用 `/calculator/newProduct/queryCost` 获取后续表单默认参数。当前 CLI 的 `opscli calculator draft` 已经包含这一步：先根据站点、平台、海关类目等第一阶段参数构造请求，再调用 `queryCost`，最后把返回的 `data` 生成本地草稿包。

当前不足是 CLI 没有明确展示这次请求的接口路径和 payload，不方便用户一边打开 Web 端 Network 面板，一边调试本地 CLI 场景并对比差异。

## 目标

增强现有 `draft` 命令的调试可见性，不新增独立命令，不改变默认业务流程。

用户可以继续使用现有命令生成草稿包：

```bash
opscli calculator draft \
  --country US \
  --platform 1 \
  --platform 7 \
  --hs-code-id 337 \
  --out calculator-draft-337
```

需要对齐 Web 请求时，增加调试开关：

```bash
opscli calculator draft \
  --country US \
  --platform 1 \
  --platform 7 \
  --hs-code-id 337 \
  --debug-request \
  --out calculator-draft-337
```

需要复刻 Web 请求中的 `_t` 字段时，显式传入：

```bash
opscli calculator draft \
  --country US \
  --platform 1 \
  --platform 7 \
  --hs-code-id 337 \
  --request-t 1782983898 \
  --debug-request \
  --out calculator-draft-337
```

## 非目标

- 不新增 `query-cost` 独立命令。
- 不改变 `draft` 默认输出结构。
- 不默认添加 `_t`，避免改变现有请求语义。
- 不在终端默认打印完整后端响应，避免输出过长；完整默认表单数据仍写入 `draft.json`。

## 设计

### CLI 参数

在 `opscli calculator draft` 增加两个可选参数：

- `--debug-request`：打印第一阶段接口路径和请求参数。
- `--request-t <int>`：把 Web 请求中的 `_t` 字段加入 `queryCost` payload。

默认不传这两个参数时，当前行为保持不变。

### 请求 payload

`build_query_payload` 继续负责构造第一阶段参数。新增行为：

1. 从 CLI 参数构造 payload 时：
   - `--request-t` 有值时加入 `"_t": <value>`。
   - `--request-t` 无值时不加入 `_t`。
2. 从 `--payload` JSON 文件构造 payload 时：
   - 文件中存在 `_t` 时原样保留。
   - 文件中不存在 `_t` 时不自动生成。

示例调试 payload：

```json
{
  "country_code": "US",
  "platforms": [1, 7],
  "hs_code_id": 337,
  "department": null,
  "reference": "NONE",
  "reference_value": null,
  "_t": 1782983898
}
```

### 调试输出

开启 `--debug-request` 后，CLI 在调用接口前输出：

```text
第一步：调用 /calculator/newProduct/queryCost 获取表单默认参数
请求参数：
{
  "country_code": "US",
  "platforms": [
    1,
    7
  ],
  "hs_code_id": 337,
  "department": null,
  "reference": "NONE",
  "reference_value": null,
  "_t": 1782983898
}
```

接口成功并生成草稿包后，保留现有成功输出，并可补充说明：

```text
queryCost 调用成功，已根据后端默认参数生成草稿。
```

### 错误处理

错误处理沿用现有逻辑：

- HTTP 层异常由 `CalculatorClient._request` 转成 `RuntimeError`。
- 后端 `code != 200` 时，`draft` 命令输出 `生成草稿失败：<message>` 并退出。
- `--debug-request` 只增加请求前可见性，不吞掉异常，不改变退出码。

### 测试

新增或调整以下测试：

1. `draft --debug-request` 打印 `/calculator/newProduct/queryCost` 和请求参数。
2. `draft --request-t 1782983898` 会把 `_t` 传入 fake client。
3. `--payload` JSON 文件包含 `_t` 时，payload 构造保留该字段。
4. 不传 `--request-t` 时，现有 `draft` 行为不变。
5. 现有草稿包生成、校验、提交测试继续通过。

## 用户体验

完成后，用户可以用 `draft --debug-request` 明确看到 CLI 正在执行与 Web 端“确定”按钮对应的第一阶段请求，并用 `--request-t` 临时复刻浏览器 Network 中的 `_t` 参数。默认流程仍保持简洁，适合日常生成草稿包。 
