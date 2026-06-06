# amazon-rufus-cookie-headless Proposal

## 背景

当前 `opscli amazon-rufus get` 依赖用户本机 Chrome/CDP 登录态。用户要求先提供并落地 Python 端调用方法：调用方传入 Amazon `cookie`，系统参考 `E:/code/work/extension/python` 的 Playwright headless 捕获链路，用该 `cookie` 获取 Rufus 数据。

## 范围

本变更只实现 Python SDK 入口：

```python
RufusManager().get_headless(
    asin="B0TEST1234",
    country="US",
    question="这个商品适合送礼吗？",
    streaming_url="https://www.amazon.com/rufus/cl/streaming?tabId=...",
    headers=headers,
    cookie=amazon_cookie,
    payload_template=payload_template,
)
```

## 设计原则

1. 保留现有 CDP 本机流程，不修改 `RufusManager.get()` 的默认行为。
2. `cookie` 是必填登录态输入，同一份 `cookie` 同时用于 headless 页面捕获和 Rufus streaming 请求。
3. 输出结构与现有 `RufusManager.get()` 兼容，继续复用 `AnswerReportFormatter`。
4. 不在异常、日志、报告或测试输出中回显 `cookie`、完整 headers 或 payload。
5. 测试只 mock Playwright/httpx，不访问真实 Amazon。

## 非目标

1. 不实现远程授权确认、MCP 调用、storage_state 持久化。
2. 不新增 CLI `--cookie` 参数。
3. 不建立 Amazon 账号池或后台队列。

## 验收标准

1. Python 层可以调用 `RufusManager.get_headless(..., cookie=...)` 获取兼容数据结构。
2. `cookie` 为空时返回稳定错误。
3. headless 捕获阶段收到传入 `cookie`。
4. Rufus streaming 请求阶段收到同一份 `cookie`。
5. 现有 `tests/amazon_rufus/test_core.py` 继续通过。
