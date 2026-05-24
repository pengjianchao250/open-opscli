# ops-skill-sync 流程地图

> 本文件记录 Skill 的完整设计背景、技术细节和操作说明。日常执行无需加载，仅在排查问题或理解设计时参考。

---

## 使用场景

**触发话术（示例）**：
- 「把我 Claude 的 Skills 同步到 Trae」
- 「新装了 OpenClaw，帮我把技能复制过去」
- 「扫描一下哪些工具装了哪些 Skill」
- 「只把 ops-auth 和 ops-dataset-query 同步到 opencode」

**目标用户**：在同一台机器上使用多个 AI 工具的用户。

**核心价值**：避免在多个工具的 skills 目录中手动维护多份 Skill 副本。

---

## 支持的 AI 工具路径

| 工具标识 | 配置根目录 | Skills 目录 | 检测命令 |
|----------|------------|-------------|----------|
| `claude` | `~/.claude/` | `~/.claude/skills/` | `claude` |
| `openclaw` | `~/.openclaw/` | `~/.openclaw/skills/` | `openclaw` |
| `codex` | `~/.codex/` | `~/.codex/skills/` | `codex` |
| `opencode` | `~/.config/opencode/` | `~/.config/opencode/skills/` | `opencode` |
| `workbuddy` | `~/.workbuddy/` | `~/.workbuddy/skills/` | `workbuddy` |
| `trae-cn` | `~/.trae-cn/` | `~/.trae-cn/skills/` | `trae` |

**Windows 路径**：所有 `~/` 对应 `%USERPROFILE%\`，`~/.config/opencode/` 对应 `%USERPROFILE%\.config\opencode\`。脚本统一使用 `Path.home()` 构建路径，自动处理跨平台差异。

**检测逻辑（满足任一即视为已安装）**：
1. 配置根目录存在（`config_dir.exists()`）
2. 对应命令在 PATH 中可用（`shutil.which(cmd) is not None`）

---

## Skill 识别规则

与 opscli `SkillDetector` 保持一致：
- 候选目录：skills 目录下的每个子目录
- 识别条件：子目录内存在 `data/VERSION.json` 文件
- 版本读取：解析 `VERSION.json` 中的 `version` 字段
- 解析失败时静默跳过，不中断整体扫描

---

## 文件操作策略

### macOS / Linux
使用标准符号链接（`os.symlink(source, link)`），`method` 返回 `"symlink"`。

### Windows
1. 优先创建 **Directory Junction**（`os.symlink(source, link, target_is_directory=True)`）
   - 等价于 `mklink /J`，普通用户权限即可创建
   - `method` 返回 `"junction"`
2. 失败时降级为 **完整复制**（`shutil.copytree`）
   - 适用于极少数受限环境
   - `method` 返回 `"copy_fallback"`
   - 注意：copy 模式下两边独立，源更新不会自动同步到目标

### 安全删除（`_safe_remove`）
覆盖目标时需先删除已有内容，策略如下：
- Unix symlink：`path.unlink()`（只删链接本身，不影响源目录）
- Windows Junction 或空目录：`os.rmdir()`（不递归删目标内容）
- 普通目录：`shutil.rmtree()`

---

## sync 参数优先级

### 来源解析（`--from` 与 `--from-dir` 互斥）
1. `--from-dir PATH` → 直接使用指定路径
2. `--from TOOL` → 从工具注册表获取 skills 路径
3. 均未填 → 遍历已检测到的工具，取第一个有有效 Skill 的工具

### 目标解析（`--to` 与 `--to-dir` 互斥）
1. `--to-dir PATH` → 单目标，直接使用指定路径
2. `--to TOOL[,TOOL]` → 映射工具注册表（支持逗号分隔多个）
3. 均未填 → 自动检测所有已安装工具，排除来源工具自身

### Skill 列表
1. `--skills NAME[,NAME]` → 只同步指定名称
2. 未填 → 扫描来源目录，同步全部有效 Skill

---

## 来源与目标相同时的处理

当目标 skills 目录与来源 skills 目录 resolve 后路径相同时，自动跳过该条目，不报错、不创建自我引用链接。

---

## 典型工作流

### 场景 1：新装 Trae，把 Claude 的所有 Skills 同步过去
```bash
# 先扫描确认当前状态
python scripts/sync.py scan

# 同步全部
python scripts/sync.py sync --from claude --to trae-cn
```

### 场景 2：只同步指定几个 Skills 到 OpenClaw 和 Trae
```bash
python scripts/sync.py sync \
  --from claude \
  --to openclaw,trae-cn \
  --skills ops-auth,ops-dataset-query,ops-skills
```

### 场景 3：从自定义目录同步到自定义目标
```bash
python scripts/sync.py sync \
  --from-dir /Volumes/backup/skills \
  --to-dir ~/.openclaw/skills
```

### 场景 4：同步到所有检测到的工具（不指定目标）
```bash
python scripts/sync.py sync --from claude
# 自动检测并排除 claude 自身
```

---

## 与 opscli skills install 的区别

| 维度 | ops-skill-sync | opscli skills install |
|------|---------------|----------------------|
| 来源 | 已安装在某个工具 skills 目录的 Skill | 内置模板 或 技能广场远程包 |
| 目标 | 其他工具的 skills 目录 | AI 工具的 skills 目录 |
| 中央存储 | 不使用 | 使用（~/.opscli/skills/） |
| 注册表 | 不写入 | 写入 installed_skills.json |
| 适用场景 | 跨工具同步已有 Skill | 首次安装 Skill |
