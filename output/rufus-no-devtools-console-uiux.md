# Rufus 打开 Amazon 页面不打开控制台 - UIUX

## 体验目标

Rufus 登录采集是 CLI 驱动的浏览器体验，不涉及前端页面设计。本轮 UIUX 关注点是用户在浏览器中的操作感受：

1. 打开 Amazon 页面后，窗口应聚焦在 Amazon 页面。
2. 不自动弹出 DevTools/Console。
3. 用户只需要完成 Amazon 登录，不需要理解 Chrome 调试面板。
4. 采集完成后沿用现有 `--close-browser` 行为。

## 用户路径

```text
用户触发 Rufus 登录采集
  -> opscli 自动启动或连接 Chrome
  -> 打开 Amazon 国家站点页面
  -> 用户完成登录
  -> opscli 自动打开商品页并捕获 Rufus streaming
  -> 返回脱敏保存摘要
```

期望浏览器可见状态：

```text
Amazon 登录页 / 商品页
```

不期望可见状态：

```text
DevTools Console
Network 面板
空白调试面板
```

## 文案与交互

本轮不新增用户文案、不新增参数、不新增确认门。原因：

1. “不打开控制台”应是默认体验，而不是让用户选择。
2. 增加参数会扩大 CLI 心智负担。
3. 现有 `OPS_RUFUS_DEBUG_PAGES=1` 页面生命周期诊断仍可保留，不等同于打开 DevTools。

## 可访问性与可理解性

1. 用户无需处理控制台窗口，降低误关页面或误操作风险。
2. 避免控制台占用屏幕空间，尤其是小屏设备。
3. 登录流程更贴近普通浏览器使用习惯。

## 验证建议

自动化层：

1. 单元测试覆盖启动参数和 profile 偏好清理。
2. 不在 CI 中打开真实 Chrome 或访问 Amazon。

人工 smoke 层：

1. 清理 Rufus profile 后运行一次 `watch-login`，确认只打开 Amazon 页面。
2. 构造带 DevTools 偏好的旧 profile 后运行一次 `watch-login`，确认新打开页面不自动弹控制台。
3. 验证 `--close-browser` 仍只关闭本次由 opscli 启动的调试浏览器。

## 非目标

1. 不设计 GUI。
2. 不增加网页组件。
3. 不引入图标库、字体系统或 design token。
4. 不修改报告 Markdown 样式。

