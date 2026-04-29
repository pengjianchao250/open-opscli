---
name: ops-competitive-intelligence-analyst
description: 使用 CLI 模式查询本地数据集索引并执行 竞争情报分析师 数据查询
version: v0.1.0
---

# ops-competitive-intelligence-analyst (CLI 模式)

使用 `opscli` 命令行工具查询数据，通过本地缓存索引辅助字段检索，使用脚本完成分析计算。

---

## 调用前置要求

> **【强制】每次使用本 Skill 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现"未登录 / 未授权 / Token 过期 / expired / 401"等状态，必须立即调用 `ops-auth` Skill
- 只有认证状态确认正常后，才允许继续读取本地索引、执行查询或运行分析脚本

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

> **【强制】使用本 Skill 前，必须先阅读 `references/data-query-service-dev-guide.md`**

---

## 使用原则

- 本 Skill 负责字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 `opscli query` 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `opscli skills upgrade ops-dataset-query` 再重试查询
- 分析计算通过对应脚本完成

---

## 典型工作流

### 查询 内部销售数据

```bash
opscli query build \
  --dataset 内部销售数据（销售额、ASIN 数量、毛利率等） \
  --dimension asin \
  --output /tmp/competitive-intelligence-analyst_query1.json \
  --run --pretty
```

### 查询 竞品 Listing 快照

```bash
opscli query build \
  --dataset 竞品 Listing 快照（价格、星级、评论数、排名） \
  --dimension asin \
  --output /tmp/competitive-intelligence-analyst_query2.json \
  --run --pretty
```

### 查询 搜索词表现

```bash
opscli query build \
  --dataset 搜索词表现数据 \
  --dimension asin \
  --output /tmp/competitive-intelligence-analyst_query3.json \
  --run --pretty
```

### 查询 品牌搜索表现

```bash
opscli query build \
  --dataset 品牌搜索表现数据 \
  --dimension asin \
  --output /tmp/competitive-intelligence-analyst_query4.json \
  --run --pretty
```

---

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

详细字段映射和 payload 模板见 `references/dataset_fields_mapping.md`。

---

## 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案：**

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①②均因工具限制无法使用时 | 多次 `opscli query run` + 客户端合并 |

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 检查拼写或 `opscli skills upgrade` 同步最新数据集 |
| 未登录 | 调用 `ops-auth` Skill，执行 `opscli auth login` |
| Token 过期 | 优先 `opscli auth token refresh --all`；刷新失败再 `opscli auth login` |
| opscli 未找到 | 激活虚拟环境或设置 `OPSCLI_BIN` |
| 分析结果异常 | 检查输入数据是否完整，补全缺失数据后重算 |

---

## 安装与管理

```bash
opscli skills install ops-competitive-intelligence-analyst            # 安装
opscli skills install ops-competitive-intelligence-analyst --force     # 强制重装
opscli skills status --pretty                                # 查看版本
opscli skills upgrade ops-competitive-intelligence-analyst             # 升级
```
