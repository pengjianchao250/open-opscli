# 源码提交与交付规范

`opscli app` 负责创建应用、初始化 Git 和推送源码；线上构建、发布、健康检查和回滚由 AppHub 处理。本文件只维护交付检查，具体构建方式、依赖版本和存储配置以项目 `docs/apphub-contract.md` 及实际发布文件为准。

## 提交前配置检查

- 使用 Keepa 或 SellerSprite 时，后端只读取 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`；生产环境显式注入 `https://ops.mcp.xenkee.com`，预发布环境显式注入 `https://ops.api.qa.aukeyit.com`。
- `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL` 必须是纯 origin，不含 `/api`、接口路径、查询参数或末尾 `/`；不得设置代码默认值、按鉴权模式推断环境或拆分 provider 专属变量。
- 第三方数据鉴权来自每个请求已校验的 `QueryCredentials`，部署配置不得注入共享 API Key、JWT、Session、Cookie 或 viewer ticket。
- 独立仓库根存在 `app.yaml`，保持 `apiVersion: apps.aukeys/v1`；名称、标题、数据集和可见范围按真实应用维护。应用清单字段以当前模板和平台 schema 为准，不补回旧版运行时声明。
- 根目录存在本地 binding `.opscli/app.json`，其中 `app_id` 和 `slug` 有效，且 `.opscli/app.json.slug == app.yaml.name`。`app_id`、仓库、Owner 和 Git 信息只保留在本地 binding。
- `.gitignore` 必须忽略 `.opscli/`，`.opscli/app.json` 不得被 Git 跟踪或暂存；`app.yaml` 留在源码中。
- 使用 SQLite 时保留 `database.kind: sqlite`、`database.path: /data/app.db`。应用只使用 `SQLITE_PATH`；模板库、本地运行库、容器运行库依次为 `data/app.db`、`.data/app.db`、`/data/app.db`。
- 已初始化的空白 `data/app.db` 是必要模板资产，可以进入 Git 和镜像；本地运行库、真实业务数据、SQLite 伴生文件、`.env`、密钥和本地 binding 不得进入 Git 或构建上下文。不得把写入业务数据后的库当空白模板提交。
- 保留模板入口 `backend/app.py`、依赖清单、唯一前端锁文件、`Dockerfile`、`nixpacks.toml`、忽略规则和项目实际使用的 `compose.apphub.yaml`；缺少必需资产时报告模板问题，不从 Skill 复制旧配置或生成替代文件。

## 构建与运行边界

- AppHub 生产入口保持单应用进程合同：`uvicorn backend.app:app --host 0.0.0.0 --port 8000`，同一应用托管前端构建产物、API 和 `/__apphub_healthz`。健康检查须快速返回 200，不依赖业务取数。
- 前端资源与 API 沿用模板相对地址、hash 路由和 Vite base，不硬编码 AppHub 公开前缀、appId、slug 或部署域名。
- 不重新引入已废弃的 `opscli.app.migrate`、Nginx 双服务或项目侧公开路径拼接。
- 普通业务开发不改平台端口、路由、网络、身份、存储挂载或保留变量。使用 `compose.apphub.yaml` 的项目保留平台校验结构与 `SQLITE_PATH` 注入；本地 `compose.yaml` 不替代平台配置。
- Node 版本读取 `frontend/package.json` 的 `engines`，包管理器读取 `packageManager`；安装使用已有锁文件。不得通过忽略 engine 错误、删除锁文件或更换包管理器完成构建。
- 依赖安装分工沿用实际模板。当前模板由 `requirements-app.txt` 声明业务依赖，`requirements.txt` 供本地与 Nixpacks 使用；Docker 的 SDK 由基础镜像提供。不要为满足旧文档再生成一套依赖清单或钉死 SDK 版本。
- Dockerfile 和 Nixpacks 保持相同应用入口、前端产物、端口与健康路径；使用当前项目合同指定的构建入口，不假定所有项目都仅用 Nixpacks。保留精确 COPY 和构建缓存，必要构建资产不能被忽略。

## 交付验证

1. 从 `README.md`、`frontend/package.json` 和项目合同读取实际检查命令，执行前端测试、生产构建及项目要求的后端测试、健康检查；不虚构 lint/typecheck，也不通过删测试或关闭规则绕过失败。
2. 前端主流程验证加载、空数据、失败、提交与结果刷新；路由或资源路径改动还要检查页面刷新和资源加载。涉及 WebSocket 才检查 WebSocket，不为普通页面新增它。
3. 部署或持久化配置变化时补充相应构建、启动、重启持久化验证，遵守已有授权和宿主权限；日常文案改动不反复启动容器。未验证项与无关既有失败必须列明，不能宣称检查全部通过。
4. 使用真实数据的应用再执行 `data-access-standard.md` 的发布检查，确认前端没有直连取数服务或持有凭证；不在本文件重复维护第三方接口清单。
5. 检查 Git 已跟踪、已暂存及未跟踪文件，而不只看普通 diff；确认源码中没有本地运行数据、密钥、依赖目录和构建产物。

## 当前 opscli 流程

新项目按主 Skill 从统一模板仓库的 `master` 分支安全 clone、清理模板 Git，随后连续执行 `opscli app create`、`opscli app init`。已有正确绑定的项目不重复初始化。空远端首次初始化允许尚无 `master` 或本地 HEAD。

`opscli app push "<project-directory>" --message "<summary>"` 会整体暂存、提交并普通推送 `HEAD:master`，不执行强制推送。`--message` 必填，用于存在修改时创建 commit。

推送前展示：

- 本次完整文件范围，包括既有暂存内容；说明该命令会整体暂存当前项目改动。
- 准确 origin、binding 对应的业务仓库与目标分支 `master`。
- 已执行检查、未验证项和仍然存在的失败。

用户已明确授权本次源码提交且范围一致时继续执行，不重复询问；范围含未授权的其他改动时停止，不通过删除或隐藏他人改动来凑出可推送状态。

不得把业务代码推回统一模板仓库；origin 与 binding 不一致时停止核对。clone、Git 清理或 create/init 失败时，停止后续开发。

## 职责结束边界

- push 成功只表示源码到达远端 `master`，不创建 release、不查询版本、不消费发布事件。
- `opscli app` 不提供 release 命令；Skill 不绕过 push 另行创建 AppHub release。
- 没有线上平台状态或运行证据时，不得报告“已发布”或“部署成功”；本地构建、镜像或 Compose 验证不能代替平台验收。
- `opscli` CLI 或相关 MCP 工具失败后，立即按 `ops-feedback` 规范提交结构化反馈并返回 `feedback_uuid`；认证未授权、用户取消和五分钟内已反馈的同一错误除外。
