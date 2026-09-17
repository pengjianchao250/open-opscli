# opscli App 模板克隆与本地开发预览优化需求

## 1. 背景

T107 看板创建与本地启动过程中暴露出两类环境耦合问题：模板克隆通过 Skill 目录下的裸 Python 脚本执行，可能加载到不完整或错误的 Python 环境；本地前端启动依赖 Corepack 的隐式版本解析和错误的 Vite 参数转发，导致在 Git 由 opscli 运行时提供、Corepack 缺失或版本声明不一致时失败。

本需求同步修改 `open-opscli` 正式源码和统一模板。`bind-apphub-git.py` 仅作为历史参考文件，不参与本需求的实现、合同或质量门禁，也不修改其实现。

## 2. 目标

- 提供 `opscli app clone-template <project-directory> --json` 正式模板克隆入口。
- 由 opscli 自身检测并使用绝对 Git 路径，克隆成功后安全删除模板根 `.git`，失败不留下半成品目标目录。
- `app dev` 和模板启动脚本按 `frontend/package.json` 的 `packageManager` 执行 pnpm。
- 优先使用 Corepack；Corepack 不存在时，仅允许使用版本完全匹配的现有 pnpm。
- 在前端目录执行 pnpm，避免 `--dir frontend` 改变 Corepack 解析上下文。
- 传递 Vite 参数时不产生多余的 `--`，固定监听 `127.0.0.1`。
- 提前检查 Node、uv、包管理器和端口，改善失败阶段、命令和退出码诊断。
- 让 Git 检测结果说明候选来源，便于区分 PATH、标准安装位置和运行时安装路径。

## 3. 非目标

- 不修改 `bind-apphub-git.py`，不迁移其逻辑，不以其测试合同阻断模板交付。
- 不改变 AppHub 后端 API、数据库结构、生产端口、发布流程或 Git push 授权边界。
- 不全局安装 Node、pnpm、Git 或 Python 依赖。
- 不主动提交、推送、发布或部署任何项目。

## 4. 功能合同

### 4.1 模板克隆

`opscli app clone-template` 接受不存在或为空的目标目录，可选 `--repo-url` 与 `--branch`，默认使用统一模板仓库和 `master` 分支。命令输出统一 `{success, command, data, error}` 信封；成功数据至少包含目标路径、仓库地址、分支和 Git 路径。目标非空、父目录不存在、Git 未就绪、clone 失败或 `.git` 清理验证失败时返回稳定错误码并停止后续流程。

### 4.2 包管理器

模板前端必须声明形如 `pnpm@11.0.0` 的 `packageManager`。Corepack 存在时使用 Corepack 解析该声明；Corepack 不存在时检测现有 pnpm，只有 `pnpm --version` 与声明版本完全相同才允许继续，否则明确提示安装或启用 Corepack。所有 pnpm 命令以 `frontend` 为工作目录执行。

### 4.3 本地开发预览

`opscli app dev` 继续启动后端 `127.0.0.1:8035` 与前端 `127.0.0.1:5173`，但前端命令必须等价于 `pnpm dev --host 127.0.0.1 --port 5173`，不得生成 `vite -- --host ...`。前端失败或任一启动等待超时必须清理已启动的后端和前端进程。

### 4.4 模板启动脚本

`scripts/check_startup.py`、`scripts/start.ps1` 和 `scripts/start.sh` 使用同一包管理器合同；检查脚本不再无条件要求 Corepack。模板忽略规则必须排除 `.pytest-tmp/` 和 `.test-tmp/` 等测试临时目录。

## 5. 验收标准

- `opscli app clone-template <empty-dir> --json` 能使用 opscli 运行时 Git 完成 clone 和 `.git` 脱离。
- clone 失败、目标非空和 Git 不可用均不会执行 `create/init`，且不会留下新建的半成品目录。
- `app dev` 的单元测试覆盖 packageManager 解析、Corepack 路径、匹配版本 pnpm 回退、frontend 工作目录、无多余 `--`、127.0.0.1 参数和进程清理。
- 模板启动检查覆盖 Corepack 存在、Corepack 缺失但 pnpm 匹配、pnpm 不匹配、packageManager 缺失或非法以及 Windows/Unix 启动参数一致性。
- 相关后端与前端测试通过；不把 `bind-apphub-git.py` 的旧测试合同作为本次模板交付阻断条件。

## 6. 分阶段实施

1. 在 `open-opscli` 增加模板克隆服务和正式 CLI，更新 Skill 入口与 Git 来源诊断。
2. 修复 `app dev` 包管理器解析、工作目录、Vite 参数和失败清理，并补充回归测试。
3. 同步统一模板启动检查、Windows/Unix 启动脚本、忽略规则、测试入口和 README 流程说明。
4. 运行针对性测试、构建和模板启动检查，记录未验证项；后续提交和推送仍需用户明确授权。
