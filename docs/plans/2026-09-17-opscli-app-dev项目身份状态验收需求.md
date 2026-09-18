# `opscli app dev` 项目身份状态验收需求

## 1. 背景

多个 AppHub 看板可以通过 `opscli app dev` 同时运行并自动选择不同端口。开发进程退出后，释放的默认端口允许被其他项目再次使用；浏览器旧标签页只保存 URL，不保存项目身份，因此同一个 `127.0.0.1:5173` 可能在不同时间展示不同项目。

仅检查端口可连接、前端页面可打开或后端健康检查返回 HTTP 200，无法证明响应来自当前项目。Codex 若在原启动命令已经退出后继续复用旧 URL，会把其他项目误报为当前项目。

## 2. 目标

- `opscli app dev` 在前后端真实就绪后登记当前项目、监督进程、子进程和实际端口。
- 提供稳定的 `opscli app dev-status <project-root> --json` 查询入口。
- 状态查询同时校验项目根目录、记录的进程和实际服务可用性。
- 状态缺失、失效或项目不匹配时保持安全失败，不使用 HTTP 200 猜测归属。
- 正常退出时清理状态；异常退出遗留状态时明确返回 `stale`，并识别端口可能已被复用。

## 3. 状态合同

开发状态写入项目根目录 `.opscli/dev.json`，至少包含：

- `schema_version`
- `project_root`
- `supervisor_pid`
- `backend_pid`
- `frontend_pid`
- `backend_port`
- `frontend_port`
- `started_at`

`.opscli/` 继续保持本地忽略，不进入源码、发布归档或生产镜像。

## 4. 查询合同

`opscli app dev-status <project-root> --json` 使用 `opscli app` 统一信封返回。只有同时满足以下条件时：

- `success=true`
- `running=true`
- `identity_verified=true`
- `project_root` 与请求目录解析后的绝对路径一致

调用方才能报告“当前项目正在运行”，并使用返回的 `frontend_url` 与 `backend_url`。

状态值包括：

- `running`：记录的监督进程、前后端进程和端口均正常。
- `starting`：记录的进程仍在，但服务尚未全部就绪。
- `stale`：记录的进程已退出；原端口即使可访问也不得认领。
- `not_running`：当前项目没有开发状态记录。
- `invalid` / `identity_mismatch`：状态文件不可用或不属于当前项目。

## 5. Agent 规则

- 本地启动仍统一使用 `opscli app dev <project-root>`。
- 启动器输出 URL 后必须执行 `dev-status` 验证项目身份。
- 启动命令会话退出、失败或被宿主回收后必须重新查询状态。
- 不得用旧浏览器标签页、端口可连接或单独健康检查 HTTP 200 替代项目身份校验。
- 浏览器只打开 `dev-status` 返回的 `frontend_url`。

## 6. 验收标准

1. 默认端口空闲时继续使用 `8035/5173`。
2. 多项目并发时继续自动顺延端口。
3. 前后端就绪后生成 `.opscli/dev.json`，退出后删除。
4. 当前项目运行时 `dev-status` 返回 `running=true` 和 `identity_verified=true`。
5. 记录进程退出但端口被其他项目复用时，返回 `running=false`、`status=stale` 和 `ports_reused=true`。
6. 没有状态文件时，即使默认端口正在响应，也返回 `not_running`。
7. Skill 和统一模板明确禁止仅凭 HTTP 200 报告项目正在运行。
