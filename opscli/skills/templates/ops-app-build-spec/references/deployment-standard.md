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

根目录还必须有 `.dockerignore`。Docker 构建上下文固定为仓库根目录，Compose 中使用 `context: ..`；不得使用依赖宿主机绝对路径的上下文。

进入生产部署阶段的项目必须同时提供实际前端和后端；空项目初始化或后端尚未交付时只完成前端，不得用空容器满足文件检查。后端交付完成后才生成可发布的双服务 Compose。

`Dockerfile` 使用多阶段 target 同时描述前端和后端镜像，至少提供 `frontend-runtime`、`backend-runtime`。Compose 的两个服务分别选择对应 target，避免维护两份入口文件。

项目主 Dockerfile 固定为 `deployment/Dockerfile`。Linux 服务器使用标准 Compose 路径和相对构建上下文；不得额外生成根目录兼容 Dockerfile，也不得为本地宿主机 provider 缺陷改变生产文件结构。

### 分层与缓存

禁止无边界的 `COPY . .`，不是禁止复制文件。Dockerfile 必须按依赖和源码拆分复制：

```text
frontend-deps -> frontend-build -> frontend-runtime
backend-deps  -> backend-build  -> backend-runtime
```

- 前端先复制实际使用的 `package.json` 和唯一锁文件，再执行冻结安装，之后才复制 `frontend/` 源码、共享配置和 Nginx 模板。
- 后端先复制 `pyproject.toml`、`uv.lock`，执行 `uv sync --locked --no-install-project`，之后才复制 `backend/` 源码并完成项目安装。
- 前端 stage 不得复制 `backend/`；后端 stage 不得复制 `frontend/`。
- `ops-app.config` 在依赖安装后复制，使应用 ID 或应用名变化只触发构建层，不重装依赖。
- 使用 BuildKit cache mount；前端缓存使用包管理器原生缓存目录，后端缓存 `/root/.cache/uv`。缓存 ID 不得把密钥写入缓存内容。
- CI 可通过 Compose `build.cache_from`、`build.cache_to` 使用 registry 或本地外部缓存；本地基线不依赖外部缓存。

Docker 的缓存命中取决于指令和被复制文件的内容。精确 `COPY`、锁文件优先和小构建上下文是必须项。[Docker 构建缓存规范](https://docs.docker.com/build/cache/optimize/)

### `.dockerignore` 最低规则

必须排除 `.git`、编辑器目录、`node_modules`、前端构建产物、Python 虚拟环境和缓存、SQLite 本地数据库、日志、`.env`、私钥及包管理器认证文件；必须保留源码、锁文件、`ops-app.config`、`deployment/` 和测试所需文件。`.dockerignore` 不得通过通配规则误排除 `package.json`、`pyproject.toml`、`uv.lock` 或 `nginx.conf.template`。

## 前端镜像

- 使用多阶段构建：Node 阶段安装锁定依赖并执行 `vite build`，Nginx 阶段只复制构建产物和配置。
- 使用与锁文件一致的包管理器及冻结安装模式。
- 构建前读取 `ops-app.config`；`appId` 为空时失败。
- 将 Skill 的 `assets/nginx.conf.template` 原样复制为项目的 `deployment/nginx.conf.template`。项目内 Nginx 必须使用该模板；只允许替换模板变量，不得删除或放宽路径、SPA 回退和缓存规则。
- 将 Skill 的 `ops-app-config.mjs`、`ops-app-config.d.mts`、`render-nginx-config.mjs` 原样复制到项目 `deployment/`。
- Node 构建阶段复制根目录 `ops-app.config`，执行 `node deployment/render-nginx-config.mjs ops-app.config deployment/nginx.conf.template /tmp/default.conf`。脚本只替换 OPS 模板变量，保留 `$uri`、`$host` 等 Nginx 变量。
- Nginx 运行阶段从 Node 构建阶段复制 `/tmp/default.conf` 到 `/etc/nginx/conf.d/default.conf`，镜像构建阶段必须执行 `nginx -t`。
- 构建阶段执行 `nginx -t` 时，Compose 服务名尚不存在；允许只在检查副本中把 `backend:8000` 临时替换为 `127.0.0.1:8000`，检查完成后必须恢复原始上游地址，运行时仍通过 Compose DNS 访问 `backend:8000`。
- Nginx runtime 必须创建并赋予非 root 用户权限给 `/tmp`、`/var/cache/nginx`、`/var/run`；主配置中的 pid 必须改为 `/tmp/nginx.pid`，启动参数不得再次声明 pid，避免重复 directive，也不得依赖 `/var/run/nginx.pid` 的 root 写权限。访问日志和错误日志写入 stdout/stderr。
- Compose 和 Dockerfile 不得声明 `OPS_APP_ID`、`OPS_APP_NAME` 或另一套部署路径 build args；这些值只来自 `ops-app.config`。
- 不使用 `vite preview` 作为生产服务器。

## Vite 产物路径合同

- Vite 构建 `base` 固定为 `/ops-app/{appId}/{appName}/`，因此生成的 HTML 会从该前缀请求 JS、CSS、图片和其他资源。
- 前端镜像把 `dist` 目录中的内容直接复制到 `/usr/share/nginx/html/`，不额外创建 `/ops-app/{appId}/{appName}/` 文件夹。
- Nginx 模板将 `/ops-app/${OPS_APP_ID}/${OPS_APP_NAME}/...` 重写为根目录下的 `/...`，再执行 `try_files`；例如浏览器请求 `/ops-app/123/demo/assets/app.js` 时读取 `/usr/share/nginx/html/assets/app.js`。
- 应用 ID、应用名、Vite `base`、Docker 构建参数和 Nginx 模板变量必须来自同一份 `ops-app.config`。任一值不一致时发布检查失败。
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
- 依赖层与源码层分开复制：先复制 `pyproject.toml`、`uv.lock` 执行 `uv sync --locked --no-install-project --no-dev`，再复制源码完成安装；启动命令使用 exec 形式。
- 监听 `0.0.0.0`，提供 `/health`（存活，不查依赖）与 `/ready`（就绪，检查数据库）。Compose `healthcheck` 与 `depends_on.condition: service_healthy` 以 `/ready` 为准。
- SQLite 默认路径为 `/data/app.db`，镜像内不包含数据库文件。
- 后端代码结构、配置、迁移与测试按 `backend-standard.md` 与 `sqlite-standard.md` 执行。

## Compose

`deployment/compose.yaml` 使用最新 Compose Specification，不写旧版 `version` 字段。至少声明：

- `frontend`：构建前端镜像、暴露 Web 端口、依赖后端健康状态。
- `backend`：构建后端镜像、声明健康检查、挂载 SQLite 数据卷。
- 一个命名数据卷，用于 `/data`。
- 前后端服务都必须声明 `image`。镜像仓库名按服务区分：`<appId>-<appName>-frontend` 和 `<appId>-<appName>-backend`；每个仓库同时发布 `:sha-<git-sha>` 与 `:latest` 两个 tag。示例：`1234-orders-web-frontend:sha-3f8a2c1`、`1234-orders-web-frontend:latest`。

服务间使用 Compose 服务名通信。只有浏览器需要访问的端口才映射到宿主机；后端只使用 `expose: 8000`，由 Nginx 通过 Docker Compose 内置 resolver 动态解析的 `http://backend:8000` 访问。Nginx 必须配置 `resolver 127.0.0.11 valid=30s ipv6=off;`，并通过变量形式 `proxy_pass`，避免后端容器重启换 IP 后继续访问旧地址。

Compose 基线：

- 两个服务的 `build.context` 为 `..`，`dockerfile` 为 `deployment/Dockerfile`，分别选择 `frontend-runtime`、`backend-runtime`。
- `image` 字段由 Skill 调用共享配置模块的 `getOpsAppImageName(config, service, tag)` 渲染，不允许人工维护另一份 ID 或应用名。仓库名部分统一转为小写；校验时必须验证前后端镜像名中的 ID、应用名、服务后缀与配置一致。
- `frontend` 映射 `0.0.0.0:${OPS_APP_PORT:-8080}:8080`，保证局域网可访问；外层 Nginx 在容器网络内时改为 external network，不发布宿主端口。
- `frontend` 使用 `depends_on.backend.condition: service_healthy`；后端 `/health` 必须配置 `healthcheck`。仅写短格式 `depends_on` 不代表服务已经就绪。
- Linux 服务器和 CI 按标准 Compose provider 执行构建；不把本地宿主机 provider 的并行或路径参数写入生产 Compose。
- 线上 Compose 的 `image` 固定引用 `:latest`，并设置 `pull_policy: always`；CI 构建必须同时推送 `:sha-<git-sha>` 和 `:latest`。hash tag 不得复用，digest 必须写入发布记录。
- 生产 Compose 禁止源码 bind mount、`container_name`、`privileged` 和 `network_mode: host`。
- `read_only: true` 为默认运行策略；前端至少把 `/tmp`、`/var/cache/nginx`、`/var/run` 声明为 `tmpfs`，并显式设置非 root Nginx 用户可写的 mode，后端把 `/tmp` 声明为 `tmpfs`。镜像中的静态文件和 Python 代码不可写。
- 服务设置 `restart: unless-stopped`、`init: true`、停止宽限期和日志轮转；日志写 stdout/stderr。
- Dockerfile 不声明 `VOLUME`。持久化只由 Compose 顶层 named volume 声明，后端挂载 `/data`，前端不挂持久卷。
- SQLite 服务固定单副本，禁止通过 Compose 横向扩展写入实例；发布前必须定义卷备份和恢复步骤。
- 不在 Compose、Dockerfile `ARG/ENV` 或镜像层写入密钥。非敏感运行配置可用环境变量；敏感值使用 Compose secrets 或部署平台 secret。
- 镜像使用明确版本的官方基础镜像；业务镜像按约定使用可变标签 `latest` 和不可复用的 `sha-<git-sha>`。每次发布必须在发布记录中保存实际镜像 digest，回滚使用 hash tag 或 digest，不依赖 `latest` 的历史状态。

Compose 官方生产建议包括移除源码卷绑定、设置重启策略并为生产单独覆盖配置；服务健康依赖、只读文件系统、日志和命名卷均由 Compose Specification 提供。[Compose 生产规范](https://docs.docker.com/compose/how-tos/production/)、[服务规范](https://docs.docker.com/reference/compose-file/services/)、[卷规范](https://docs.docker.com/reference/compose-file/volumes/)

## 路径合同

```text
开发静态根路径: /
部署静态根路径: /ops-app/{appId}/{appName}/
后端 API 路径: /api
健康检查路径: /health
```

`appName` 与 `appId` 必须来自根目录 `ops-app.config`。Vite、Nginx 渲染和 Compose 镜像名必须复用同一配置；禁止在 `.env`、Compose、Dockerfile 或其他文件维护互相独立的硬编码 ID。Compose 中允许出现由 Skill 渲染得到的镜像名，但它必须视为派生产物，每次配置变更都重新生成并校验。

## 发布检查

按顺序检查：

1. 读取并校验 `ops-app.config`；首次发布通过已提供工具取得应用 ID 并写回。
2. 确认 Dockerfile、两个运行 target、Compose、Nginx 模板、共享配置模块和渲染脚本存在且被前端镜像引用。
3. 检查 `.dockerignore` 没有排除构建必需文件，Dockerfile 没有无边界 `COPY . .`、`VOLUME` 或明文 secrets；Compose 前后端镜像名符合服务后缀和双 tag 约定。
4. 执行前后端测试和生产构建。
5. 执行 `docker compose -f deployment/compose.yaml config`，再执行 `docker compose -f deployment/compose.yaml build --check`（环境支持时）。
6. 获得许可后再构建并启动容器。
7. 从外层公开地址检查健康状态、部署前缀、嵌套路由刷新、API、缓存响应头和数据持久化。

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
