# ops-methods-card Architecture

日期：2026-05-12

## 架构决策

新增 `methods-card` CLI 模块承接远端 API，请求认证复用 `ops-auth`。Skill 只调用 CLI 和本地脚本，不直接请求后端。

## 文件结构

```text
opscli/methods_card/
├── __init__.py
├── cli.py
├── client.py
└── exceptions.py

opscli/skills/templates/ops-methods-card/
├── SKILL.md
├── data/VERSION.json
├── 交叉表-1778233062511.xlsx
├── scripts/xlsx_preview.py
└── references/
    ├── 执行流程.md
    ├── 方法卡接口.md
    ├── 卡片.md
    └── 卡片输出示例.html
```

## CLI 设计

### `opscli methods-card list`

输入：

- `--keyword`
- `--page`
- `--per-page`
- `--mine`
- `--pretty`

远端请求：

```text
GET {OPS_URL}/v1/ai/method-card
```

### `opscli methods-card detail`

输入：

- `card_id`
- `--pretty`

远端请求：

```text
GET {OPS_URL}/v1/ai/method-card/{card_id}
```

## 认证

`MethodsCardClient` 使用：

```python
AuthClient().build_request_auth("ops")
```

该路径会生成 `Authorization: Bearer <jwt>` 和必要 cookie，与 query/feedback 模块一致。

## Excel 解析

`scripts/xlsx_preview.py` 只使用 Python 标准库解析 `.xlsx` 的 zip/xml 结构，避免新增依赖。

输出包含：

- sheet 名称
- headers
- row_count
- preview_rows
- numeric_summary

## Skill 执行链

```text
用户输入
  -> auth token status
  -> methods-card list
  -> 语义选卡
  -> methods-card detail
  -> xlsx_preview.py
  -> Agent 分析
  -> 写 output/methods-card/*.html
```

