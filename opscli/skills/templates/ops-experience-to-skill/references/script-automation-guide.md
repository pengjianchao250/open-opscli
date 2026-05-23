# 脚本固化评估

目标：分析流程方案中哪些部分应该固化为脚本自动执行，减少每次 AI 模型重新理解、重新写代码和重复消耗 token。

默认优先使用 Python。原因是跨 AI 工具兼容性好，运营数据处理、Excel/CSV/JSON/HTML 生成生态成熟，内部交付也更容易复用。

## 1. 适合脚本化的信号

优先固化这些动作：

- 每次输入结构相似，例如固定 CSV/XLSX 字段。
- 计算规则确定，例如 ACOS、ROAS、CTR、CVR、毛利率、环比。
- 过滤和分类规则稳定，例如低样本、异常阈值、否词候选、库存预警。
- 输出格式固定，例如 Excel 工作簿、CSV 动作清单、HTML 报告。
- 校验规则明确，例如必填字段、日期范围、数值范围、空值检查。
- 多个 AI 工具都要复用，不应依赖某个 AI 的临时推理。

## 2. 不适合过早脚本化的内容

先保留在 Skill 说明或 reference 中：

- 运营还没确认的阈值。
- 强依赖业务语境的主观判断。
- 每个团队差异很大的策略。
- 需要解释和说服人的诊断叙述。
- 数据来源不稳定、字段尚未确认的流程。

## 3. 脚本设计原则

脚本要做确定性工作，不要把所有业务判断塞进脚本：

- 输入参数显式化：日期、平台、国家、部门、ASIN、阈值配置、输入文件。
- 输出结构稳定：JSON/CSV/XLSX/HTML。
- 错误信息中文友好：缺字段、空数据、口径不一致要说清楚。
- 保留中间结果：方便 AI 或运营复核。
- 支持配置文件：阈值和例外尽量放 JSON/YAML，不写死。
- 生成 `--help`：让其他 AI 工具也能知道怎么调用。

## 4. 脚本契约

为了跨工具复用，生成脚本时默认遵守这份契约：

- `零依赖优先`：能用 Python 标准库完成就不要引入第三方包。必须依赖第三方包时，在 `requirements.txt` 或脚本文档里写清。
- `Python 优先`：默认生成 `.py`；只有目标环境明确更适合时，再提供 Node.js 或 Shell fallback。
- `参数清晰`：使用 `argparse`，提供 `--help`，输入文件、输出目录、日期范围、站点、币种、阈值配置都显式传参。
- `结构化输出`：脚本成功时优先向 stdout 输出 JSON 摘要，方便其他 AI 工具解析；详细报告写入文件。
- `退出码明确`：成功返回 `0`；输入缺失、字段不匹配、权限或文件错误返回非 0，并给中文错误信息。
- `配置外置`：阈值、字段映射、例外清单优先放 `references/*.json` 或 `config/*.json`，不要硬编码在脚本里。
- `不绑定平台`：不要依赖当前 AI 工具的私有路径、MCP 对象、会话状态或文件链接。

推荐 JSON 摘要结构：

```json
{
  "success": true,
  "output_files": ["outputs/report.html"],
  "metrics": {"rows": 120, "warnings": 2},
  "warnings": [],
  "next_steps": []
}
```

## 5. 推荐脚本类型

| 脚本 | 作用 |
| --- | --- |
| `normalize_input.py` | 统一字段名、日期、币种、空值 |
| `calculate_metrics.py` | 计算确定性指标和派生字段 |
| `classify_rules.py` | 按配置阈值标记异常/动作 |
| `validate_output.py` | 校验输出结构、必填字段和数值范围 |
| `render_report.py` | 生成 Markdown/HTML/Excel 报告 |
| `compare_outputs.py` | 对比当前工具参照和通用替代输出 |

## 6. 写进 Skill 的格式

```markdown
## 脚本

- `scripts/normalize_input.py`：清洗用户导出的广告报表。
- `scripts/classify_rules.py`：按 `references/rules.json` 标记异常。
- `scripts/render_report.py`：生成 HTML 和 CSV 交付物。

运行顺序：
1. `python scripts/normalize_input.py --input ... --output ...`
2. `python scripts/classify_rules.py --input ... --rules references/rules.json --output ...`
3. `python scripts/render_report.py --input ... --html ... --csv ...`
```

## 7. Token 节省策略

- 把长字段映射表放入配置文件，脚本读取，不要每次塞进 prompt。
- 把固定输出模板写进脚本或 HTML 模板。
- 把稳定规则写成配置，AI 只负责解释差异和处理例外。
- 用脚本输出结构化 JSON，再让 AI 写摘要，避免 AI 从原始大表中反复理解。
