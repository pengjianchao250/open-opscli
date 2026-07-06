# 结果与任务复用工作流

仅在用户要查询、定位、复制或复用已有任务时读取本文件。

## 查询最终试算结果

优先使用：

```bash
opscli calculator detail --task-code <TASK_CODE> --sudo "<SUDO>"
```

- `--task-code` 与 `--sudo` 之间必须有空格。
- `sudo` 很长时必须加引号。
- 需要排查原始字段时才加 `--json`：

```bash
opscli calculator detail --task-code <TASK_CODE> --sudo "<SUDO>" --json
```

普通 `detail` 按页面 `trial-result-teble` 展示任务摘要、成本摘要和试算结果。
方案列使用 `自发货(币种)`、`FBA(币种)`、`WFS(币种)` 等业务表头；缺失方案不显示。

## 从列表定位任务

如果任务编号或 `sudo` 信息不足，先查列表：

```bash
opscli calculator list --task-code <TASK_CODE> --json
```

拿到 `task_code` 和 `sudo` 后再执行 `detail`，不要直接调用 Polaris 后端 API。

## 复制已有任务

用户要复用既有试算参数时：

```bash
opscli calculator copy --task-code <TASK_CODE> --sudo "<SUDO>" --out <NEW_DRAFT_DIR>
```

`--out` 必须指向新的空目录，不得覆盖已有 `draft.json`。复制完成后按 `references/draft-workflow.md` 的“继续已有草稿”处理。

## Web 路由与 Web详情页

列表页：

```text
https://bi.xenkee.com/#/calculatorResultList
```

结果详情页：

```text
https://bi.xenkee.com/#/calculatorDatail?task_code=<TASK_CODE>&sudo=<SUDO>
```

回复可以展示 Web 详情页，但不要在回复中泄露完整 JWT/Cookie，也不得复述其它内部认证信息。

## 最终回复格式

查询 `detail` 后，不要只摘要毛利/毛利率；必须保留完整“试算结果”表格的主要费用行，列必须包含 CLI 返回的所有方案，如自发货、FBA、WFS，并标出推荐方案。

回复顺序：

1. 任务状态、推荐方案和 Web 详情页。
2. 完整试算结果表格。
3. 1–2 句说明亏损或推荐原因。

至少保留 CLI 实际返回的这些行：

- 售价、毛利、毛利率。
- 非税采购价、头程费用、仓库费用、尾程费用。
- 站内广告、站外促销、平台佣金、退款费、固定成本。
- 备注。

如果某行 CLI 未返回可以省略；不能把完整表格压缩成“方案/毛利/毛利率”三列。

示例：

```text
结果已出，状态：试算成功。推荐方案：WFS。

| 费用 | 自发货(USD) | FBA(USD) | WFS(USD) 推荐 |
|---|---:|---:|---:|
| 售价 | 1.00 | 1.00 | 1.00 |
| 毛利 | -10.81 | -5.42 | -5.00 |
| 毛利率 | -1080.88% | -541.67% | -499.67% |
| 非税采购价 | 0.13 | 0.13 | 0.13 |
| 头程费用 | 0.33 | 0.37 | 0.37 |
| 仓库费用 | 0.27 | 0.00 | 0.00 |
| 尾程费用 | 11.02 | 5.87 | 5.45 |
| 站内广告 | 0.01 | 0.01 | 0.01 |
| 站外促销 | 0.01 | 0.01 | 0.01 |
| 平台佣金 | ... | ... | ... |
| 退款费 | ... | ... | ... |
| 固定成本 | ... | ... | ... |
| 备注 | ... | ... | ... |

售价只有 1.00，三个方案均亏损；主要亏损来自尾程费用。
```

## 常见错误

| 现象 | 处理 |
|---|---|
| `unexpected extra argument` | 检查 `--task-code` 和 `--sudo` 之间是否缺少空格 |
| `detail` 超时 | 先使用 `list --task-code <TASK_CODE> --json` 查看状态，稍后重试 |
| 用户要完整原始字段 | 使用 `detail ... --json`，只展示必要片段 |
| FBA/WFS/MFN 缺失 | 隐藏缺失方案列，不制造空数据 |
| CLI 标记推荐方案 | 在表头保留“推荐”标识 |
