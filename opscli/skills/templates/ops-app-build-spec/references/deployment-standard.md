# 部署规范

部署目标为一个 Docker Compose 项目，包含前端和后端全部运行服务。初始化只生成部署文件；是否构建、启动或发布服从当前环境授权。

## 固定产物

```text
deployment/
├── Dockerfile
├── compose.yaml
├── nginx.conf.template
├── ops-app-config.mjs
├── ops-app-config.d.mts
└── render-nginx-config.mjs
```

初始化后的项目必须同时提供实际前端和最小 FastAPI 后端；不得移除任一服务或用空容器满足文件检查。

`Dockerfile` 使用多阶段 target 同时描述前端和后端镜像，至少提供 `frontend-runtime`、`backend-runtime`。Compose 的两个服务分别选择对应 target，避免维护两份入口文件。

## 前端镜像

- 使用多阶段构建：Node 阶段安装锁定依赖并执行 `vite build`，Nginx 阶段只复制构建产物和配置。
- 使用与锁文件一致的包管理器及冻结安装模式。
- 构建前读取 `ops-app.config`；`projectId` 为空时失败。
- 将 Skill 的 `assets/nginx.conf.template` 原样复制为项目的 `deployment/nginx.conf.template`。项目内 Nginx 必须使用该模板；只允许替换模板变量，不得删除或放宽路径、SPA 回退和缓存规则。
- 将 Skill 的 `ops-app-config.mjs`、`ops-app-config.d.mts`、`render-nginx-config.mjs` 原样复制到项目 `deployment/`。
- Node 构建阶段复制根目录 `ops-app.config`，执行 `node deployment/render-nginx-config.mjs ops-app.config deployment/nginx.conf.template /tmp/default.conf`。脚本只替换 OPS 模板变量，保留 `$uri`、`$host` 等 Nginx 变量。
- Nginx 运行阶段从 Node 构建阶段复制 `/tmp/default.conf` 到 `/etc/nginx/conf.d/default.conf`，镜像构建阶段必须执行 `nginx -t`。
- Compose 和 Dockerfile 不得声明 `OPS_PROJECT_ID`、`OPS_APP_NAME` 或另一套部署路径 build args；这些值只来自 `ops-app.config`。
- 不使用 `vite preview` 作为生产服务器。

## Vite 产物路径合同

- Vite 构建 `base` 固定为 `/ops-app/{projectId}/{appName}/`，因此生成的 HTML 会从该前缀请求 JS、CSS、图片和其他资源。
- 前端镜像把 `dist` 目录中的内容直接复制到 `/usr/share/nginx/html/`，不额外创建 `/ops-app/{projectId}/{appName}/` 文件夹。
- Nginx 模板将 `/ops-app/${OPS_PROJECT_ID}/${OPS_APP_NAME}/...` 重写为根目录下的 `/...`，再执行 `try_files`；例如浏览器请求 `/ops-app/123/demo/assets/app.js` 时读取 `/usr/share/nginx/html/assets/app.js`。
- 项目 ID、应用名、Vite `base`、Docker 构建参数和 Nginx 模板变量必须来自同一份 `ops-app.config`。任一值不一致时发布检查失败。
- 禁止删除前缀重写、同时复制带前缀目录，或在 Nginx 中硬编码另一套路径；这些做法会导致资源 404 或重复路径。

## Nginx 缓存合同

模板固定以下行为：

- `/index.html` 及 SPA 路由回退：`Cache-Control: no-store, no-cache, must-revalidate, max-age=0`，关闭 ETag 和修改时间协商，确保每次返回完整新内容。
- `/index.html` 同时返回 `X-Accel-Expires: 0`，要求最外层 Nginx 不保存该上游响应。外层不得用 `proxy_ignore_headers` 忽略 `X-Accel-Expires`、`Cache-Control` 或 `Expires`。
- JS、CSS、图片和其他静态文件：`Cache-Control: public, no-cache`，启用 ETag 和精确 Last-Modified 协商；内容未变化时允许返回 `304`。
- 禁止为静态文件增加 `immutable` 或长期正数 `max-age`，避免绕过协商验证。

最外层 Nginx 是最终响应出口。发布验收必须从外层公开地址检查最终响应头，项目内配置文件存在不能单独证明缓存策略生效。

## 后端镜像

- 使用官方 Python 基础镜像和非 root 用户。
- 依赖层与源码层分开复制，启动命令使用 exec 形式。
- 监听 `0.0.0.0`，提供 `/health`。
- SQLite 默认路径为 `/data/app.db`，镜像内不包含数据库文件。

## Compose

`deployment/compose.yaml` 至少声明：

- `frontend`：构建前端镜像、暴露 Web 端口、依赖后端健康状态。
- `backend`：构建后端镜像、声明健康检查、挂载 SQLite 数据卷。
- 一个命名数据卷，用于 `/data`。

服务间使用 Compose 服务名通信。只有浏览器需要访问的端口才映射到宿主机；后端可由 Nginx 反向代理 `/api`。不得把密钥直接写入 Compose，使用环境变量或部署平台的密钥机制。

## 路径合同

```text
开发静态根路径: /
部署静态根路径: /ops-app/{projectId}/{appName}/
后端 API 路径: /api
健康检查路径: /health
```

`appName` 与 `projectId` 必须来自根目录 `ops-app.config`。Vite 和 Nginx 渲染必须复用 `ops-app-config.mjs`；禁止在 `.env`、Compose、Dockerfile 或其他文件维护互相独立的硬编码 ID。

## 发布检查

按顺序检查：

1. 读取并校验 `ops-app.config`；首次发布通过已提供工具取得项目 ID 并写回。
2. 确认 Dockerfile、两个运行 target、Compose、Nginx 模板、共享配置模块和渲染脚本存在且被前端镜像引用。
3. 执行前后端测试和生产构建。
4. 执行 `docker compose -f deployment/compose.yaml config`。
5. 获得许可后再构建并启动容器。
6. 从外层公开地址检查健康状态、部署前缀、嵌套路由刷新、API、缓存响应头和数据持久化。

发布工具未定义时停在第 4 步，不猜测项目注册或发布命令。

## 完成标准

- Compose 配置有效，且包含实际前后端服务。
- 前端 HTML、JS、CSS 和图片均从部署前缀加载。
- 带部署前缀的静态资源能映射到 Nginx 根目录中的 Vite 产物，不出现重复 `/ops-app/.../ops-app/...` 路径。
- 浏览器访问嵌套路由和刷新均成功。
- `index.html` 和 SPA 回退响应包含 `no-store`，且外层未返回缓存命中或陈旧内容。
- 其他静态文件包含 ETag 或 Last-Modified，条件请求在内容未变化时返回 `304`。
- API 请求不携带静态资源前缀。
- 后端健康检查成功，容器重启后数据仍存在。
- 回滚说明包含镜像版本和 SQLite 数据备份/恢复边界。
