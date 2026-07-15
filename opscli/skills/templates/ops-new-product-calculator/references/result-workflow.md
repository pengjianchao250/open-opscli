# 结果与任务复用工作流

仅在用户要查询、定位、复制或复用已有任务时读取本文件。

## 查询最终试算结果

只执行一次普通 `detail`：

```bash
opscli calculator detail --task-code <TASK_CODE> --sudo "<SUDO>"
```

- `--task-code` 与 `--sudo` 之间必须有空格。
- `sudo` 很长时必须加引号。
- 默认忽略成本输入、利润和毛利，不得基于响应中的相关字段补充分析。
- 不得自动追加 `--json`、重复执行 `detail` 或为了格式化表格再次读取原始响应。
- 只有用户明确要求查看原始字段或诊断底层数据时才加 `--json`：

```bash
opscli calculator detail --task-code <TASK_CODE> --sudo "<SUDO>" --json
```

普通 `detail` 按页面“方案切换”下的表格展示 `allPlans` 全部费用方案，但不提供单选、切换或保存功能。

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

仅当用户明确要求页面入口时展示 Web 详情页。不要在回复中泄露完整 JWT/Cookie，也不得复述其它内部认证信息。

## 最终回复格式

查询 `detail` 后，原样转述 CLI 输出，不得手工重建 Markdown 表格、二次解析费用或改写列顺序。CLI 已负责保留 `allPlans` 的全部方案和 `schemes` 线路。

回复顺序：

1. 任务状态和基本信息。
2. 完整费用方案表格。

默认到此结束，不追加成本费用、利润、毛利、Web 详情页或原始 JSON 查询提示。

表格必须包含：

- 分区推荐。
- 首单数量；全部为空或 `0` 时隐藏整列。
- 分区线路。
- `每PCS头程费用(CNY)`、`每PCS目的仓费用(CNY)`、`每PCS尾程费用(CNY)`、`每PCS全程费用(CNY)` 和 `每PCS全程平均费用(CNY)`。
- 各项费用的区间。

所有费用使用 CNY，保留 4 位小数。表格前说明费用不含头程清关税金。

## 常见错误

| 现象 | 处理 |
|---|---|
| `unexpected extra argument` | 检查 `--task-code` 和 `--sudo` 之间是否缺少空格 |
| `detail` 超时 | 先使用 `list --task-code <TASK_CODE> --json` 查看状态，稍后重试 |
| 用户要完整原始字段 | 使用 `detail ... --json`，只展示必要片段 |
| `allPlans` 为空 | 输出“暂无方案数据”，不制造空费用 |
| 单项费用缺失 | 显示“未填写”，不自行推算 |
