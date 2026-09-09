# 本地开发

## 安装前端依赖

```powershell
npm --prefix frontend install
```

## 启动

前端开发服务器：

```powershell
npm --prefix frontend run dev
```

FastAPI 本地服务需要运行在 `127.0.0.1:8765`，Vite 会把 `/api` 代理到该地址。本地请求必须具备有效同源 Cookie、`X-Session-Id` 或 Viewer 测试头；不得把真实凭证写入源码或 `VITE_*` 环境变量。

## 验证

```powershell
npm --prefix frontend run test:unit
npm --prefix frontend run test:e2e
npm --prefix frontend run build
npm --prefix frontend run test:deployment
```
