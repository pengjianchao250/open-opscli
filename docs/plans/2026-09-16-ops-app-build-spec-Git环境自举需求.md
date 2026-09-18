# ops-app-build-spec Git 环境自举需求

## 1. 背景

`ops-app-build-spec` 的模板克隆、仓库初始化、迁移盘点、源码提交和推送都依赖本机 Git。当前实现只在 Git 命令真正执行时暴露“未安装”或“版本过低”，业务用户需要自行查找、安装并重新打开终端，无法满足建站流程的一体化要求。

本需求将 Git 定义为 `ops-app-build-spec` 的本地基础依赖，在 Skill 入口提前检测，并在任务确实需要 Git 时完成可信来源安装、权限申请提示和安装后验证。

## 2. 目标

1. 每次调用 `ops-app-build-spec` 时首先执行无副作用 Git 检测。
2. Git 正常时静默继续；纯咨询任务不安装软件、不弹权限窗口。
3. 新建、迁移重构、模板克隆、仓库初始化、Git 状态读取、提交和推送任务在业务副作用前完成 Git 门禁。
4. Windows 优先从 `git-scm.com` 官方页面获取与原生架构匹配的 Git for Windows 安装包。
5. macOS 按 Git 官网推荐渠道使用已有 Homebrew、MacPorts 或 Apple Command Line Tools。
6. 安装后使用 Git 绝对路径继续执行，不要求用户重新打开终端。
7. 检测和安装只影响本地开发环境，不进入业务站点源码或线上运行环境。

## 3. 任务路由

### 3.1 只检测、不安装

以下任务只执行 `opscli app ensure-git --check --json`：

- 询问 Skill 用法或开发规范；
- 讨论架构、迁移方案或可行性；
- 不访问本地项目的纯方案评审；
- 不执行 Git 操作的咨询任务。

### 3.2 检测失败后自动安装

以下任务在 Git 未就绪时执行 `opscli app ensure-git --install --json`：

- 新建 AppHub 看板；
- 已有看板迁移重构；
- 克隆统一模板；
- 初始化或恢复业务仓库；
- 读取真实 Git 状态、分支或历史；
- 提交或推送源码；
- 依赖 Git 信息的排错或代码评审。

安装和验证必须先于模板目录创建、AppHub 应用创建、binding 写入和业务源码修改。

## 4. Windows 安装合同

1. 识别原生 Windows 架构，支持 x64 和 ARM64，不以 Python 进程架构代替原生架构。
2. 请求 `https://git-scm.com/install/windows`，从页面中选择当前架构的 Git for Windows Setup。
3. 只接受 HTTPS 且位于 Git 官网或 Git for Windows 官方 GitHub Release 下载链的地址。
4. 下载到临时目录，验证 Authenticode 状态有效并记录签名发布者。
5. 使用 Git for Windows 官方无人值守参数安装。
6. 官网直装发生网络、页面解析或下载失败时，才降级到官网推荐的 WinGet `Git.Git` 包。
7. 签名无效、来源越界或架构不受支持时安全停止，不降级到其他未知来源。
8. 安装器要求系统权限时，由宿主 Agent 发起权限审批并重新执行；Python 代码不绕过 UAC。

## 5. macOS 安装合同

1. 识别 Intel、Apple Silicon 和 Rosetta 转译环境。
2. 已有原生 Homebrew 时安装或升级 Git。
3. 已有 MacPorts 时仅在具备相应权限时执行；否则返回需要提权状态，由宿主申请权限。
4. 没有合适包管理器时调用 `xcode-select --install`。
5. Apple 系统安装窗口、许可协议和管理员密码必须由用户确认，不能绕过。
6. 不自动安装 Homebrew，不执行远程 shell 安装脚本，不使用停止维护的 macOS 独立安装包。

## 6. Git 门禁结果

检测和安装结果至少包含：

- `ready`：是否可以继续需要 Git 的任务；
- `status`：`ready`、`missing`、`version_unsupported`、`platform_unsupported`、`elevation_required` 或 `user_confirmation_required`；
- `platform`、`architecture` 和兼容层状态；
- Git 绝对路径和版本；
- `detected_via`：`path`、`standard_location` 或 `installed`，说明 Git 候选来源；
- 最低版本；
- 实际安装方式；
- 面向用户的下一步说明。

最低支持版本保持为 Git `2.30.0`。

## 7. 三层保护

1. **Skill 入口**：每次调用先检测，确认任务需要 Git 后才安装。
2. **`opscli app`**：提供 `ensure-git` 命令；`app init` 和 `app push` 在业务副作用前再次确保 Git 就绪。
3. **模板克隆命令**：正式流程使用 `opscli app clone-template <project-directory> --json`，由 opscli 自身使用统一 Git 环境服务和绝对路径执行 clone；Skill 目录下的 `clone_template.py` 不再是正式入口或合同依据。

`app create` 自身不直接执行 Git，不单独触发安装；标准新建流程必须在调用它之前完成 Git 门禁。

## 8. 安全边界

- 不从第三方软件下载站或未知镜像下载 Git。
- 不执行 `curl | sh`、服务端动态返回命令或 `shell=True` 拼接命令。
- 不绕过 Windows UAC、macOS 系统许可、`sudo` 或宿主安全审批。
- 官网来源、重定向或签名验证失败时停止。
- Linux、CI 和服务器环境不自动执行 `apt`、`yum`、`dnf` 或 `sudo`。
- 安装失败时不得创建半成品项目、AppHub 应用或 binding。
- `opscli` 命令硬失败继续遵守 `ops-feedback` 自动反馈规则。

## 9. 本地与线上边界

- Git 探测、下载、安装和缓存只存在于用户本地。
- 不向生成站点写入 Git 安装脚本、检测代码或状态文件。
- 不修改站点 `Dockerfile`、Nixpacks、前端依赖或 Python 依赖。
- 不要求 AppHub 构建服务器或站点运行容器安装 Git。
- 临时安装文件在安装流程结束后清理。
- 站点上传后的构建、发布和运行行为保持不变。

## 10. 验收标准

- Git 已满足要求时检测快速、静默且返回绝对路径。
- 纯咨询任务不会自动安装或申请权限。
- Windows x64 和 ARM64 自动选择对应官网安装包。
- Windows 官网直装校验可信来源和有效数字签名。
- macOS 根据 Intel、Apple Silicon、Rosetta 和现有包管理器选择官网推荐渠道。
- 安装完成后无需重开终端即可继续。
- 用户拒绝权限、系统策略阻止安装或安装后验证失败时不产生业务副作用。
- 新建、迁移、初始化、提交和推送流程不能绕过 Git 门禁。
- 生成项目和线上站点不包含本功能的安装代码、依赖或缓存。
