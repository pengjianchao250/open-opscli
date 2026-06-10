# amazon-rufus multi question CLI proposal

## 背景

`opscli amazon-rufus get` 当前已经支持 `--question` 单题模式，传入后会跳过默认题库。但它没有 `-q` 短参数，也不能在一次命令中传入多个临时问题。用户需要一次输入多个问题并跳过默认问题模板。

## 目标

1. `amazon-rufus get` 支持 `-q` 作为 `--question` 短别名。
2. `-q/--question` 可重复传入，并按输入顺序逐题执行。
3. 传入任意临时问题时跳过默认题库。
4. 保留现有单题调用兼容。
5. MCP Tool 同步支持多题参数。
6. Skill/README 同步说明新的问题来源规则。

## 非目标

1. 不新增子命令。
2. 不新增 JSON、分隔符或问题文件参数。
3. 不把临时问题写回默认题库。
4. 不改 Rufus replay、parser、报告格式化主链路。

## 技术方案

1. CLI 将 `question` option 改为可重复参数：`list[str] | None`，声明 `--question` 和 `-q`。
2. `RufusManager` 新增 `questions: list[str] | None` 内部参数，保留 `question: str | None`。
3. `_resolve_questions()` 统一处理单题、多题、题库三种来源，避免校验分散。
4. MCP Tool 新增 `questions: list[str] | None`，并透传给 Manager。
5. 多题中任一空白问题返回 `INVALID_RUFUS_QUESTION`。

## 风险

1. Typer 可重复 option 会改变测试中 dummy manager 接收字段，需要同步测试断言。
2. 旧调用方仍使用 `question` 单题参数，必须保持兼容。
3. MCP schema 增加 `questions` 后，Agent 可能同时传 `question` 与 `questions`，需返回稳定错误。
