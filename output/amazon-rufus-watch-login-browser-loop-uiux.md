# Amazon Rufus watch-login 浏览器关闭异常 CLI 体验

## 用户体验目标

用户遇到浏览器或页面关闭时，应看到明确的业务提示，而不是 Playwright 底层错误。排障模式下，用户应能看到页签创建/关闭的脱敏摘要，用于判断是谁在反复开关页签。

## 当前体验

```json
{
  "success": false,
  "command": "amazon-rufus watch-login",
  "data": null,
  "error": {
    "code": "RUFUS_ERROR",
    "message": "Page.wait_for_timeout: Target page, context or browser has been closed"
  }
}
```

问题：

1. 错误码过于泛化。
2. message 暴露底层实现。
3. 用户无法判断是登录失败、页面关闭、还是工具主动关闭浏览器。

## 目标体验

诊断模式：

```text
[rufus-page] created source=browser page_id=... url=about:blank
[rufus-page] created source=opscli.login page_id=... url=https://www.amazon.com/
[rufus-page] created source=external page_id=... url=https://www.amazon.com/...
[rufus-page] closed page_id=... url=https://www.amazon.com/...
```

错误模式：

```json
{
  "success": false,
  "command": "amazon-rufus watch-login",
  "data": null,
  "error": {
    "code": "SEED_REQUEST_NOT_CAPTURED",
    "message": "监听 Amazon 登录或商品页时，页面、上下文或浏览器已关闭；请保持本次调试浏览器打开，并重新执行 watch-login。"
  }
}
```

## 文案原则

1. 说明发生了什么：监听页面或浏览器已关闭。
2. 说明用户动作：保持调试浏览器打开后重试。
3. 不输出敏感登录态信息。
4. 不建议重复打开多次浏览器。
5. 诊断日志只输出 URL 摘要，不输出 query、headers、payload、cookie 或 storage_state。
