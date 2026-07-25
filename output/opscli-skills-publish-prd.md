# opscli Skills 发布能力 PRD

## 目标

让项目内 Skill 能以两种方式被用户获取：

1. 随 `aukeys-opscli` 发行包进入内置模板清单，用户本地安装。
2. 上传到技能广场，按个人、部门、公司范围共享给其他用户远程安装。

## 用户角色

- Skill 作者：在仓库或本地目录维护 `SKILL.md`、脚本、数据和版本号。
- CLI 使用者：通过 `opscli skills install/list/status/upgrade` 管理本机 Skill。
- 发版维护者：控制哪些仓库模板进入 PyPI wheel/sdist 或二进制包。
- 广场使用者：浏览、搜索、安装、评分他人发布的 Skill。

## 核心场景

### 场景一：内置模板随包发版

Skill 作者把模板放入 `opscli/skills/templates/ops-xxx/`，发版维护者在 `manifest.json` 中声明准入。构建时按 profile 裁剪模板，用户安装新版 `aukeys-opscli` 后即可执行：

```bash
opscli skills install ops-xxx
```

### 场景二：本地 Skill 发布到技能广场

Skill 作者在任意本地 Skill 目录执行：

```bash
opscli skills publish --share-type company --changelog "初始版本"
```

CLI 自动校验目录结构、解析元数据、打包 zip、上传到后端。首次发布创建技能，后续同名发布创建新版本并同步元数据。

### 场景三：从技能广场安装

用户拿到 `username@skill_name` 标识符后执行：

```bash
opscli skills install username@skill_name
```

CLI 下载远端 zip，解压到中央存储，再链接到已检测到的 AI 工具目录。

### 场景四：同步市场安装记录

换机或多设备场景下，用户执行：

```bash
opscli skills install --sync-market --dry-run
opscli skills install --sync-market
```

CLI 拉取服务端安装队列，补装缺失技能并升级旧版。

## 功能边界

已支持：

- 包内模板安装。
- 多 AI 工具安装目标检测。
- 中央存储加链接模式。
- 广场发布、编辑、下架。
- 广场浏览、搜索、详情、版本、评分。
- 远程安装和分享码安装。
- 市场安装记录同步和同步排除名单。
- `ops-dataset-query`、`ops-amazon-rufus` 的远端数据升级。

不属于当前发布能力：

- 自动把所有 `templates/` 目录无条件公开发版。
- 对任意 Skill 自动生成远端升级接口。
- 无版本号目录的广场发布。
- 未登录情况下发布或安装权限受限的广场技能。

## 验收标准

内置模板发版：

- 新模板目录必须在 `manifest.json` 声明。
- 准入模板必须有 `SKILL.md` 和 `data/VERSION.json`。
- `python-release` profile 下 wheel/sdist 只包含 manifest 允许的模板。
- `scripts/check_skill_release_manifest.py --dist` 能检测产物缺失或混入。

技能广场发布：

- 缺少 `SKILL.md` 或 `data/VERSION.json` 时发布失败并输出结构化错误。
- `VERSION.json` 缺少 `name` 时发布失败。
- `SKILL.md` frontmatter 版本与 `VERSION.json` 不一致时发布失败。
- 首次发布调用创建接口，返回 identifier。
- 已存在技能再次发布调用完整更新接口并创建新版本。
- 临时 zip 不残留。

远程安装：

- `username@skill_name` 格式校验明确。
- zip 格式完整解压，旧 md 格式兼容为 `SKILL.md`。
- 始终补写 `data/VERSION.json`。
- 安装成功后写中央存储并链接到目标工具目录。

## 约束

- 所有内置 Skill 命名必须使用 `ops-` 前缀。
- Skill 文档应描述 `opscli` 命令入口，不应要求用户直接执行内部脚本。
- 涉及远端查询或认证时，Skill 脚本不应直连后端 API，应通过 `opscli` 正式命令入口。
- 包发版准入由 `opscli/skills/templates/manifest.json` 控制，不在 `MANIFEST.in` 或 `setup.py` 重复维护白名单。

