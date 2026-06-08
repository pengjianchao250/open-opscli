# amazon-rufus-headless-page-retry Proposal

## 背景

`amazon_rufus_get` 和 `amazon_rufus_get_remote` 的默认 headless 链路会打开 Amazon 商品页并捕获 `/rufus/cl/streaming` seed request。当前 `HeadlessRufusCaptureService.capture_seed_request()` 只打开一次页面；若 Amazon 商品页首轮没有触发 Rufus 请求或导航临时失败，会直接返回 `RUFUS_HEADLESS_CAPTURE_ERROR`。

用户要求在该错误场景增加重试机制：重新打开 Amazon 页面，最多重试 3 次。

## 目标

1. 在 headless capture 服务内部对页面捕获失败增加有限重试。
2. 首次失败后最多重新打开 Amazon 商品页 3 次，总页面尝试最多 4 次。
3. 重试成功后继续沿用现有 seed request、Rufus streaming、报告写入链路。
4. 最终失败时保持 `RUFUS_HEADLESS_CAPTURE_ERROR` 错误码。
5. 不新增 MCP/CLI 参数，不回退 CDP，不泄露敏感字段。

## 非目标

1. 不重启 Chromium browser；本轮只重开 page。
2. 不调整 Playwright Chromium 自动安装逻辑。
3. 不修改 Rufus 请求 payload、SSE 解析、题库和报告格式。
4. 不为重试次数新增可配置项。

## 实现边界

主要修改：

- `opscli/amazon_rufus/services/headless_capture.py`
- `tests/amazon_rufus/test_core.py`
- `docs/change-log-pending.md`

## 验收标准

1. 测试覆盖 transient miss 后重开页面并最终捕获成功。
2. 测试覆盖最多只重试 3 次，失败后抛 `HeadlessRufusCaptureError`。
3. 测试覆盖重试复用同一个 context，不重复启动 browser。
4. 现有 headless Chromium 自动安装测试继续通过。
5. MCP Rufus 工具测试继续通过。
