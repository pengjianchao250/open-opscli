# ops-skills 典型工作流场景

## 场景一：全新环境初始化

在新机器或新用户目录中，首次配置所有 Skill：

```bash
opscli auth token status          # 认证检查；未登录则 opscli auth login
opscli --version                  # 确认 opscli 已安装
opscli skills install             # TUI 交互模式，批量安装全部 Skills
opscli skills list --pretty       # 验证安装结果
opscli skills status --pretty     # 检查版本状态
```

---

## 场景二：日常版本维护

定期检查并更新 Skills，确保数据集查询功能使用最新字段索引：

```bash
opscli auth token status
opscli skills status --pretty                      # 检查所有 Skill 版本
opscli skills upgrade ops-dataset-query           # 如有新版本则升级
opscli skills list --pretty                        # 验证升级后版本
```

---

## 场景三：从广场发现并安装技能

```bash
opscli auth token status
opscli skills marketplace list                           # 浏览广场技能
opscli skills marketplace search "数据查询"              # 搜索
opscli skills marketplace info pengjianchao@ops-auth     # 查看详情
opscli skills marketplace versions pengjianchao@ops-auth # 查看版本历史
opscli skills install pengjianchao@ops-auth              # 远程安装
opscli skills list --pretty                              # 确认安装成功

# 【强制】安装成功后立即用 AskUserQuestion 引导评分（见 评分引导.md）
opscli skills marketplace rate pengjianchao@ops-auth <score>  # 用户选择后自动执行
```

---

## 场景四：将自己的 Skill 发布到广场

```bash
opscli auth token status
cd my-skill/
ls SKILL.md data/VERSION.json     # 确认目录结构完整

# 【铁律】发布前必须更新版本号
# 读取 data/VERSION.json 当前版本（如 "1.7.0"）
# 递增版本号（如 Bug 修复 → "1.7.1"，功能新增 → "1.8.0"）
# 更新 data/VERSION.json: {"name": "my-skill", "version": "1.8.0"}
# 同步更新 SKILL.md frontmatter: version: 1.8.0

opscli skills publish --changelog "初始版本"
# 输出：技能已发布，标识符：pengjianchao@my-skill

# 修改内容后再次发布（确保已按铁律更新版本号）
opscli skills publish --changelog "修复了 xxx，新增了 yyy"
```

---

## 场景五：多运行时环境安装

同时使用多种 AI 工具（Claude Code + OpenClaw 等）时：

```bash
opscli auth token status
opscli skills install --runtime all                              # 安装到全部运行时
opscli skills install ops-auth --runtime claude,openclaw         # 或指定多个运行时
opscli skills install ops-dataset-query --runtime claude,openclaw
opscli skills install pengjianchao@ops-auth                      # 广场安装自动软链到各运行时
opscli skills list --pretty                                      # 验证各运行时均已安装
```

---

## 场景六：强制重置安装

当 Skill 文件损坏或需要回退到内置版本时：

```bash
opscli auth token status
opscli skills install ops-auth --force
opscli skills install ops-dataset-query --force
opscli skills install ops-skills --force
opscli skills upgrade ops-dataset-query --force    # 如需同时重置远端数据
```

---

## 场景七：指定路径安装（CI/脚本环境）

```bash
opscli auth token status
opscli skills install ops-auth --runtime claude --force          # 指定运行时
opscli skills install ops-auth --skills-dir ~/.claude/skills/ --force  # 或指定目录
opscli skills list --skills-dir ~/.claude/skills/                # JSON 输出便于脚本解析
```

---

## 场景八：编辑已发布的技能

```bash
opscli auth token status
opscli skills edit pengjianchao@my-skill --share-type company    # 仅修改可见范围

# 【铁律】上传文件前先更新版本号
# 更新 data/VERSION.json: {"name": "my-skill", "version": "1.2.0"}
# 同步更新 SKILL.md frontmatter: version: 1.2.0

opscli skills edit pengjianchao@my-skill \
  --dir ./my-skill/ \
  --version 1.2.0 \
  --changelog "修复了 xxx 问题，优化了 yyy 流程"

opscli skills marketplace info pengjianchao@my-skill    # 确认广场已更新
```

---

## 场景九：同步市场安装记录到本地

换新机器或重装环境后，一键同步历史安装记录：

```bash
opscli auth token status
opscli skills install --sync-market --dry-run         # 预览同步计划
opscli skills sync-exclude add alice@data-query       # 不想同步的加入排除名单
opscli skills install --sync-market                   # 执行同步
opscli skills list --pretty                           # 验证结果
```
