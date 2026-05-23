# 安装后评分引导

## 触发条件

仅在以下场景触发：

- 执行 `opscli skills install username@skill_name` 且命令返回**安装成功**
- 强制重装（`--force`）同样触发
- 内置模板安装（无 `@`）**不触发**
- 安装失败时**不触发**

---

## 引导流程（两步 AskUserQuestion）

> `AskUserQuestion` 每题最多 4 个选项（+ 自动追加"其他"），评分 6 项需拆成两步。

### 第一步：询问是否愿意评分

```
AskUserQuestion({
  questions: [
    {
      question: "安装成功！你愿意为「<skill_title>（<identifier>）」打个分吗？",
      header: "技能评分",
      multiSelect: false,
      options: [
        { label: "是，我要评分", description: "为这个技能提交 1-5 分评价" },
        { label: "暂不评分",     description: "跳过，稍后用命令手动评分" }
      ]
    }
  ]
})
```

- 选**"暂不评分"** → 告知用户可稍后手动评分：`opscli skills marketplace rate <identifier> <1-5>`，流程结束
- 选**"是，我要评分"** → 进入第二步

---

### 第二步：选择具体分数

```
AskUserQuestion({
  questions: [
    {
      question: "请为「<skill_title>」选择评分：",
      header: "选择分数",
      multiSelect: false,
      options: [
        { label: "5分", description: "非常棒，强烈推荐！" },
        { label: "4分", description: "挺好用，值得推荐" },
        { label: "3分", description: "一般，凑合能用" },
        { label: "2分", description: "较差，有明显问题" }
      ]
    }
  ]
})
```

> "其他"选项由 AskUserQuestion 自动追加，用户可输入 `1` 提交 1 分评价。

> `<skill_title>` 取安装元数据中的 `title` 字段；若无则用 `<identifier>` 代替。

---

## 根据选择执行评分

| 用户选择 | 分数 | 后续动作 |
|---------|------|---------|
| 5分 | 5 | 执行评分命令 |
| 4分 | 4 | 执行评分命令 |
| 3分 | 3 | 执行评分命令 |
| 2分 | 2 | 执行评分命令 |
| 其他输入 `1` | 1 | 执行评分命令 |
| 其他输入非法值 | — | 告知格式要求后跳过 |
| 第一步选"暂不评分" | — | 流程在第一步结束 |

**评分命令（用户选择后自动执行，无需二次确认）：**

```bash
opscli skills marketplace rate <identifier> <score>
```

**执行后回报：**

```
已为 pengjianchao@ops-auth 提交 5/5 评分，感谢！
```

---

## 完整场景示例

```
[安装完成后]
AI 输出：pengjianchao@ops-auth 安装成功（v1.2.0）

[第一步 AskUserQuestion]
❓ 安装成功！你愿意为「Ops 认证授权（pengjianchao@ops-auth）」打个分吗？
   是，我要评分  /  暂不评分

[用户选"是" → 第二步 AskUserQuestion]
❓ 请为「Ops 认证授权」选择评分：
   5分  /  4分  /  3分  /  2分  /  其他

[用户选 5分]
→ 自动执行：opscli skills marketplace rate pengjianchao@ops-auth 5
→ 回报：已为 pengjianchao@ops-auth 提交 5/5 评分，感谢！

[用户在第一步选"暂不评分"]
→ AI 提示：好的，可稍后通过以下命令手动评分：
            opscli skills marketplace rate pengjianchao@ops-auth <1-5>
```
