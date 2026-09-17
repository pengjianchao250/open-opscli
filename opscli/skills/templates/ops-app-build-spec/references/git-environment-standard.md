# Git 本地环境规范

Git 是 `ops-app-build-spec` 的本地基础依赖。本规范只管理本机 Git 的检测、安装、权限和验证；仓库身份、远端、提交与推送继续由[源码交付规范](deployment-standard.md)管理。

## 入口门禁

每次调用本 Skill，先执行：

```bash
opscli app ensure-git --check --json
```

- `ready=true` 时静默继续，并在后续 Git 命令中使用返回的绝对路径。
- 纯规范咨询、方案讨论或不访问本地项目的任务只记录检测结果，不安装软件。
- 新建、迁移重构、模板克隆、仓库初始化、Git 状态或历史读取、提交和推送任务在 `ready=false` 时执行：

  ```bash
  opscli app ensure-git --install --json
  ```

- Git 门禁必须先于目标目录创建、AppHub 应用创建、binding 写入和业务代码修改。
- `elevation_required` 时使用当前宿主的权限审批能力重新执行安装；`user_confirmation_required` 时等待用户完成系统安装界面后重新检测。

## 检测合同

- 检查 Git 是否存在、是否可执行、版本是否达到 `2.30.0`。
- 在 PATH 之外检查 Windows 和 macOS 常见官方安装路径。
- 存在多个 Git 时优先选择满足最低版本的最高版本，并返回绝对路径。
- Windows 识别原生 x64、ARM64 和 WOW64；macOS 识别 Intel、Apple Silicon 和 Rosetta。
- 不能只使用 Python 进程架构判断安装包。
- 平台或架构无法可靠识别时停止，不猜测安装包。

## Windows

1. 优先请求 `https://git-scm.com/install/windows`。
2. x64 选择 `Git-*-64-bit.exe`，ARM64 选择 `Git-*-arm64.exe`；禁止选择 PortableGit 代替安装包。
3. 只允许 HTTPS，且下载链只能经过 `git-scm.com`、GitHub 和 GitHub Release 官方下载域名。
4. 下载完成后使用 Windows Authenticode 验证签名有效，并记录签名发布者。
5. 使用 Git for Windows 官方无人值守参数安装，不拼接用户输入，不使用 `shell=True`。
6. 官网页面解析、网络或下载失败时，才允许降级到官网列出的 `winget install --id Git.Git -e --source winget`。
7. 来源越界、签名无效或架构不支持时安全停止，不切换到第三方软件下载站。
8. 安装器需要系统权限时由宿主申请授权；代码不得绕过 UAC。

## macOS

1. 已有原生 Homebrew 时使用 Homebrew 安装或升级 Git。
2. 已有 MacPorts 时，仅在当前进程具有所需权限时执行；否则返回 `elevation_required`。
3. 没有合适包管理器时执行 `xcode-select --install`，返回 `user_confirmation_required` 并等待 Apple 系统安装界面完成。
4. Apple Silicon 优先使用 `/opt/homebrew/bin/brew`，Intel 优先使用 `/usr/local/bin/brew`；Rosetta 下不得把 Intel Homebrew静默视为原生最佳方案。
5. 不自动安装 Homebrew，不执行远程 shell 安装脚本，不使用停止维护的 macOS 独立安装器。

## 安装后验证

- 重新扫描 Git 可执行文件并执行 `git --version`。
- 版本必须达到 `2.30.0`，否则保持阻塞。
- 后续 clone、init、状态检查、提交和 push 使用返回的绝对路径，不依赖当前终端刷新 PATH。
- Windows 安装包只保存在临时目录，安装流程结束后清理。
- `ready=false` 时禁止继续任何需要 Git 的业务步骤。

## 其他平台

Linux、CI、服务器和未知平台只检测，不自动执行 `sudo`、`apt`、`yum`、`dnf` 或其他系统包管理器。返回明确的 `platform_unsupported` 状态，由环境所有者准备 Git。

## 本地与线上边界

- 本规范只影响本地开发环境。
- 不向业务项目写入安装脚本、检测代码、安装包或状态缓存。
- 不修改站点构建依赖、容器镜像和运行时。
- 不要求 AppHub 构建服务器或线上站点安装 Git。
- Git 环境失败发生在业务副作用之前；不得留下半成品目录、应用或 binding。

## 错误与反馈

- 缺失、版本不足、待权限审批和待系统确认属于环境状态，由 `ensure-git` 结构化返回。
- 官网下载失败、签名无效、安装器失败或安装后仍不可用属于硬失败。
- `opscli` CLI 或相关 MCP 工具硬失败时，立即按 `ops-feedback` 规范提交结构化反馈；反馈完成后仍应保持本地任务阻塞，不能绕过 Git 门禁。

