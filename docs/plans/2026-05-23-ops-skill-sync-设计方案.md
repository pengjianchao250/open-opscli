# ops-skill-sync Skill 设计方案

> 创建日期：2026-05-23  
> 状态：待实现

---

## 一、需求背景

用户在同一台机器上安装了多个 AI 工具（Claude Code、OpenClaw、Trae Solo 等），  
已安装的 Skills 通常只存在于某一个工具的 skills 目录下，  
需要手动逐一复制才能在其他工具中使用——这个过程繁琐且易出错。

**目标**：提供一个 Skill，让 AI Agent 帮助用户：
1. 扫描各 AI 工具下已安装的 Skills
2. 将指定（或全部）Skills 同步到其他工具的 skills 目录

---

## 二、Skill 基本信息

| 属性 | 值 |
|------|-----|
| 名称 | `ops-skill-sync` |
| 类型 | 纯本地 Skill（无远端升级） |
| 安装命令 | `opscli skills install ops-skill-sync` |
| 主脚本 | `scripts/sync.py` |

---

## 三、目录结构

```
ops-skill-sync/
├── SKILL.md                  # AI Agent 使用指南
├── data/
│   └── VERSION.json          # 版本标识（SkillDetector 识别标志）
└── scripts/
    └── sync.py               # 核心脚本（scan + sync 两个子命令）
```

---

## 四、支持的 AI 工具路径

脚本使用 `Path.home()` 构建，自动跨平台，不硬编码路径分隔符。

| 工具标识 | macOS / Linux | Windows |
|----------|--------------|---------|
| `claude` | `~/.claude/skills/` | `%USERPROFILE%\.claude\skills\` |
| `openclaw` | `~/.openclaw/skills/` | `%USERPROFILE%\.openclaw\skills\` |
| `codex` | `~/.codex/skills/` | `%USERPROFILE%\.codex\skills\` |
| `opencode` | `~/.config/opencode/skills/` | `%USERPROFILE%\.config\opencode\skills\` |
| `workbuddy` | `~/.workbuddy/skills/` | `%USERPROFILE%\.workbuddy\skills\` |
| `trae-cn` | `~/.trae-cn/skills/` | `%USERPROFILE%\.trae-cn\skills\` |

**检测条件**：配置根目录存在 **或** 对应命令在 PATH 中可用（`shutil.which`）

---

## 五、脚本接口

### 5.1 scan 子命令

扫描所有（或指定）AI 工具下已安装的 Skills。

```bash
python scripts/sync.py scan [--tool claude|openclaw|trae-cn|...]
```

| 参数 | 说明 |
|------|------|
| `--tool` | 只扫描指定工具（不填则扫描全部） |

**输出 JSON**：

```json
{
  "success": true,
  "command": "skill-sync scan",
  "data": {
    "tools": [
      {
        "tool": "claude",
        "skills_dir": "/Users/mask/.claude/skills",
        "detected": true,
        "skills": [
          { "name": "ops-auth", "version": "v1.2.0" },
          { "name": "ops-dataset-query", "version": "v2.1.0" }
        ]
      },
      {
        "tool": "trae-cn",
        "skills_dir": "/Users/mask/.trae-cn/skills",
        "detected": false,
        "skills": []
      }
    ]
  },
  "error": null
}
```

- `detected: false` 表示该工具未安装或目录不存在
- Skill 识别条件：子目录内存在 `data/VERSION.json`（与 SkillDetector 保持一致）

---

### 5.2 sync 子命令

将 Skills 从来源工具/目录同步到目标工具/目录。

```bash
python scripts/sync.py sync \
  [--from claude]                          # 来源工具（不填则自动找有 Skills 的第一个工具）
  [--from-dir /path/to/source/skills]      # 来源路径（与 --from 二选一）
  [--to openclaw,trae-cn]                  # 目标工具（不填则同步到所有检测到的工具）
  [--to-dir /path/to/target/skills]        # 目标路径（与 --to 二选一）
  [--skills ops-auth,ops-dataset-query]    # 指定 Skill 名（不填则同步全部）
```

| 参数 | 说明 |
|------|------|
| `--from` | 来源工具标识（如 `claude`） |
| `--from-dir` | 来源 skills 目录完整路径 |
| `--to` | 目标工具标识，逗号分隔多个（如 `openclaw,trae-cn`） |
| `--to-dir` | 目标 skills 目录完整路径 |
| `--skills` | 只同步指定 Skill 名，逗号分隔（不填则全部） |

**参数约束**：
- `--from` 与 `--from-dir` 互斥，只能传其一
- `--to` 与 `--to-dir` 互斥，只能传其一
- 两者均不填时，`--to` 默认为所有检测到的工具（排除来源工具自身）

**输出 JSON**：

```json
{
  "success": true,
  "command": "skill-sync sync",
  "data": {
    "from": {
      "tool": "claude",
      "skills_dir": "/Users/mask/.claude/skills"
    },
    "results": [
      {
        "skill": "ops-auth",
        "target_tool": "trae-cn",
        "target_path": "/Users/mask/.trae-cn/skills/ops-auth",
        "method": "symlink",
        "replaced": true,
        "success": true,
        "error": null
      },
      {
        "skill": "ops-dataset-query",
        "target_tool": "trae-cn",
        "target_path": "/Users/mask/.trae-cn/skills/ops-dataset-query",
        "method": "symlink",
        "replaced": false,
        "success": true,
        "error": null
      }
    ],
    "summary": {
      "total": 2,
      "success": 2,
      "failed": 0
    }
  },
  "error": null
}
```

---

## 六、文件操作策略

参考 `SkillsLinker` 的跨平台链接策略：

| 平台 | 策略 |
|------|------|
| macOS / Linux | `os.symlink(source, target)`（符号链接） |
| Windows | `os.symlink(source, target, target_is_directory=True)`（Directory Junction，无需管理员权限） |
| Windows 降级 | Junction 创建失败时，`shutil.copytree` 完整复制 |

**目标已存在时**：直接覆盖（先 `_safe_remove` 删除，再建链接），无需 `--force` 确认。

**`_safe_remove` 策略**：
- Unix symlink：`path.unlink()`（只删链接本身，不影响源）
- Windows Junction / 空目录：`os.rmdir()`
- 普通目录：`shutil.rmtree()`

---

## 七、核心执行流程

### scan 流程

```
1. 遍历所有工具路径表
2. 每个工具：检测是否存在（目录 or which）
3. 已存在工具：扫描 skills_dir 下子目录，读取 data/VERSION.json
4. 输出 JSON
```

### sync 流程

```
1. 解析来源：
   --from-dir → 直接使用
   --from     → 映射工具路径表
   均未填     → 扫描所有工具，取第一个有 Skills 的工具

2. 解析目标：
   --to-dir   → 直接使用（单目标）
   --to       → 映射工具路径表（支持多个）
   均未填     → 检测所有已安装工具，排除来源工具自身

3. 确定 Skill 列表：
   --skills   → 只同步指定名称
   未填       → 来源目录下全部有效 Skill

4. 对每个 (skill, target) 组合执行：
   a. 创建目标父目录（mkdir -p）
   b. 删除已有内容（_safe_remove）
   c. 创建链接（symlink / junction / copy_fallback）
   d. 记录结果

5. 汇总输出 JSON
```

---

## 八、SKILL.md 核心内容（供 AI Agent 使用）

SKILL.md 需要描述：

1. **使用场景**：跨工具 Skill 同步
2. **scan 命令**：如何扫描、参数说明、输出解读
3. **sync 命令**：如何同步、参数优先级、输出解读
4. **典型工作流**：
   - 场景 1：新安装 Trae，把 Claude 的所有 Skills 同步过去
   - 场景 2：只同步某几个 Skills 到指定工具
   - 场景 3：同步到自定义目录（--to-dir）
5. **注意事项**：symlink 模式下，源删除会影响目标；copy 模式下两边独立

---

## 九、实现优先级

| 优先级 | 内容 |
|--------|------|
| P0 | `sync.py` 主脚本（scan + sync 子命令） |
| P0 | `data/VERSION.json` |
| P0 | `SKILL.md`（AI Agent 使用指南） |
| P1 | Windows Junction 降级处理 |
| P2 | `--tool` 过滤（scan 子命令） |

---

## 十、不在范围内

- 不新增 `opscli` 子命令（纯 Skill 脚本方案）
- 不支持跨机器同步（只做同机跨工具）
- 不做版本比较（目标已存在时直接覆盖）
- 不支持从市场/内置模板安装（只同步已安装 Skills）
