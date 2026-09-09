# Keepa 数据合同

## 数据产品

页面按用户选择的场景、站点和参数请求 Keepa 数据，并将返回的 JSON 用于当前会话内浏览与 CSV 导出。应用不保存共享快照、查询历史或用户加工结果。

## 调用路径

```text
浏览器
→ 当前站点 POST /api/v1/keepa/run
→ FastAPI
→ 受治理的 opscli Keepa 实现
→ Keepa 上游
```

## 身份与安全

- 线上使用 AppHub Viewer 注入的票据和用户信息。
- 本地联调可使用同源 Cookie 或显式 Session 头。
- 前端不持有 API Key、JWT 或 Cookie 内容，也不直连第三方服务。
- 后端不记录、持久化或返回完整凭证。

## 存储

AppHub 为应用分配 SQLite 托管卷，但当前业务不读写该数据库。查询结果只存在于浏览器内存和当前 HTTP 响应中，CSV 由浏览器按当前结果生成。

## 测试

- Playwright 拦截当前站点 API，验证请求路径、请求体、成功和失败状态。
- 后端测试注入 fake Keepa runner，不访问真实网络或本机凭证。
- 部署合同测试校验 AppHub 声明、目录和构建路径。
