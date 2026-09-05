# 源码提交与交付规范

本规范描述当前 opscli 与 AppHub 的源码交付边界。`opscli app` 只负责创建应用、初始化 Git 和推送源码；源码到达远端后，其职责结束。线上构建、发布、健康检查和回滚由 AppHub 或其他发布平台负责。

## 提交前配置检查

- 仓库根目录存在 `app.yaml`，并按业务填写名称、标题、描述、数据集和可见范围。
- 根目录存在本地 binding `.opscli/app.json`，其中 `app_id` 和 `slug` 有效，且 `.opscli/app.json.slug == app.yaml.name`。
- `.gitignore` 必须忽略 `.opscli/`；`.opscli/app.json` 不得被 Git 跟踪或暂存。
- `app.yaml` 保持 `apiVersion: apps.aukeys/v1`、`runtime: fastapi`、`python: "3.12"`、`entrypoint: backend/app.py`；使用 SQLite 时保持 `services.sqlite: true`。
- 模板要求的入口、`nixpacks.toml`、`Dockerfile` 和依赖清单仍存在，未被旧项目文件覆盖。
- 前端资源与 API 使用相对地址，不硬编码 AppHub 公开前缀、appId、slug 或部署域名。
- AppHub 生产入口保持单应用进程合同：`uvicorn backend.app:app --host 0.0.0.0 --port 8000`。Compose 或其他本地工具不能替代平台运行配置。
- 不重新引入已废弃的 `opscli.app.migrate`、Nginx 双服务或项目侧公开路径拼接。
- 已跟踪文件中没有 `.opscli/app.json`、`.env`、密钥、本地数据库、真实业务数据或构建产物。

具体配置值以当前模板和当前 Skill 的限制为准。发现项目使用旧模板配置时，列出差异并在提交前修正，不复制 Skill 内的静态配置文件。

## 当前 opscli 流程

- 新项目源码已经通过统一模板仓库 clone，不再通过 `opscli app init` 获取模板。
- 模板 clone 成功后、开始业务开发前，立即执行 `opscli app create "<app-name>" --path "<project-directory>" --json` 创建 AppHub 应用并写入本地 binding。
- `create` 成功后立即执行 `opscli app init "<project-directory>" --json`，将已克隆项目绑定到应用源码仓库并同步 remote，不覆盖已有业务源码；模板 clone 遗留的 `origin` 会在目标仓库预检后替换。
- `opscli app init`：目标仓库为空时保留本地源码，不要求远端预先存在 `main`。
- `create/init` 任一步失败都停止后续开发，并按 `ops-feedback` 规范处理失败。
- `opscli app push`：整体暂存、提交并普通推送 `HEAD:main`，不执行强制推送。
- `opscli app push --message` 必填，用于存在工作区修改时创建普通 Git commit。
- `push` 成功只表示源码到达远端 `main`，不创建 release、不查询版本、不消费发布事件。

执行会修改 Git 或远端状态的命令前：

1. 展示工作区状态和本次包含的文件。
2. 展示准确 remote、目标仓库和目标分支。
3. 说明 `opscli app push` 会整体暂存当前项目改动。
4. 取得用户明确确认后执行 `opscli app push`。

不得把业务代码推回统一模板仓库。remote 与本地应用绑定不一致时停止，先完成核对或重新初始化绑定。

## 职责结束边界

- push 成功只表示源码到达远端。
- `opscli app` 不提供 release 命令，不调用 AppHub release、版本查询或 SSE 事件接口。
- 构建排队、镜像生成、发布成功、健康状态和回滚属于线上平台状态，不由源码 push 推断。
- 没有线上平台状态或运行证据时，不得报告“已发布”或“部署成功”。
- Skill 不通过本地 Compose、Docker 启动或临时服务器替代 AppHub 线上验收。

`opscli` CLI 或相关 MCP 工具失败后，立即按 `ops-feedback` 规范提交结构化反馈；认证未授权、用户取消和五分钟内已反馈的同一错误除外。
