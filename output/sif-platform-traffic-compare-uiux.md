# Sif 平台查流量与多产品对比 CLI/Skill 体验

## 定位

本需求是 CLI 能力，不做 Web UI。这里的 UIUX 指：

- 命令怎么输入。
- 成功后终端怎么展示。
- 失败后怎么提示。
- 输出文件如何组织。
- Skill 如何把用户自然语言映射到命令。

## 命令体验

查流量：

```bash
opscli sif run 查流量 --asin B01NBNDC1T --site US
opscli sif run 查流量词 --asin B01NBNDC1T --site US --time-piece-value 7
opscli sif run 查流量 --asin B01NBNDC1T --site US --sections structure,keywords
```

多产品对比：

```bash
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF,B07QQ21GL2,B07YJPFJ43,B08PNQCKF7 --site US
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF --site US --sections sales,traffic-keywords
```

查询结果：

```bash
opscli sif status <job_id>
```

查看能力：

```bash
opscli sif features --pretty
```

## 成功输出

默认终端输出应是人可读摘要：

```text
Sif 执行成功
功能          查流量
ASIN          B01NBNDC1T
站点          US
时间范围      latelyDay=7
任务目录      <clickable path>
结构化结果    <clickable result.json>
流量结构      listingScoreChart_B01NBNDC1T_1780.xlsx
              <clickable path>
反查流量词    asinKeywordList_B01NBNDC1T_1780.xlsx
              <clickable path>
多变体自然位  asinMultiNfKeywordList_B01NBNDC1T_1780.xlsx
              <clickable path>
```

多产品对比：

```text
Sif 执行成功
功能          多产品对比
站点          US
ASIN 数量     5
时间范围      latelyDay=7
任务目录      <clickable path>
结构化结果    <clickable result.json>
对比销量      compareBoughtByAsin_5_1780.xlsx
对比流量词    compareSummaryTrafficWords_5_1780.xlsx
对比流量分    compareSummaryTrafficScore_5_1780.xlsx
重点流量词    compareMyTrafficKeywords_5_1780.xlsx
重点广告词    compareMyAdKeywords_5_1780.xlsx
```

如果加 `--json` 或 `--pretty`，输出结构化 JSON，不打印 Rich 表格。

## 失败输出

未登录：

```text
sif run 执行失败
错误码 SIF_LOGIN_REQUIRED
原因 未获取到 Sif 登录态或登录态已失效。
建议 先执行 opscli sif login-check，确认 Sif 账号密码或登录态可用。
```

部分下载子项失败：

```text
Sif 执行成功，部分子项失败
warning compare.traffic_score Sif 下载接口未返回有效 XLSX 文件
```

接口业务错误：

```text
sif run 执行失败
错误码 SIF_API_REQUEST_FAILED
原因 Sif 接口返回参数错误，请求参数可能与页面接口不一致。
建议 对照浏览器 Network 中同名接口的 Method、Query String、Request Payload。
```

## 文件体验

目录按平台和功能分组：

```text
~/.config/opscli/sif/traffic/runs/<job-id>/
~/.config/opscli/sif/compare/runs/<job-id>/
```

文件命名要让用户无需打开也能知道来源：

- `listingScoreChart`：查流量结构。
- `asinKeywordList`：反查流量词。
- `asinMultiNfKeywordList`：查多变体自然位。
- `compareBoughtByAsin`：多产品对比销量。
- `compareSummaryTrafficWords`：对比流量结构里的流量词。
- `compareSummaryTrafficScore`：对比流量结构里的流量分。
- `compareMyTrafficKeywords`：对比流量词里的重点流量词。
- `compareMyAdKeywords`：对比流量词里的重点广告词。

## Skill 体验

统一 Skill 名：

```text
ops-sif
```

触发词：

- 查销量、销量趋势、不同变体销量、同组变体销量。
- 查流量、查流量词、反查流量词、流量结构、广告流量、自然流量、多变体自然位。
- 多产品对比、对比销量、对比流量结构、对比流量词、重点流量词、重点广告词。

Skill 行为：

1. 根据意图选择 `feature`。
2. 只追问必填缺失参数：ASIN、多个 ASIN、站点。
3. 时间范围未给时默认最近 7 天。
4. 使用 CLI，不直接调用 Sif API。
5. 运行失败按项目规则提交 `ops-feedback`。
6. 最终答复只展示关键信息和文件名/路径，不打印完整 cookie/token/query。

## 默认值

| 项 | 默认 |
| --- | --- |
| site | `US` |
| timePieceType | `latelyDay` |
| timePieceValue | `7` |
| desc | `true` |
| 查流量 sections | `structure,keywords,multi-nf` |
| 多产品对比 sections | `sales,traffic-structure,traffic-keywords` |
| my asin | 多 ASIN 列表第一个 |

`--site` 支持站点名称和编码，CLI 内部统一转为 Sif `country` 编码：

```text
美国 / 美国站 / US -> US
英国 / 英国站 / UK / GB -> UK
加拿大 / 加拿大站 / CA -> CA
法国 / 法国站 / FR -> FR
西班牙 / 西班牙站 / ES -> ES
意大利 / 意大利站 / IT -> IT
澳大利亚 / 澳大利亚站 / AU -> AU
墨西哥 / 墨西哥站 / MX -> MX
阿联酋 / 阿联酋站 / AE -> AE
巴西 / 巴西站 / BR -> BR
沙特 / 沙特站 / SA -> SA
日本 / 日本站 / JP -> JP
德国 / 德国站 / DE -> DE
```

输出目录按 feature 分组：

```text
~/.config/opscli/sif/sales/runs/
~/.config/opscli/sif/traffic/runs/
~/.config/opscli/sif/compare/runs/
```

## 交互边界

- 不要求用户粘贴 Cookie。
- 不在命令示例中放账号密码。
- 不让用户填写 `_t` 或 `_m`，由客户端自动生成。
- 不把接口 payload 暴露给普通成功输出；调试时可用 `--json` 查看 sanitized 版本。
- 不把 `sales` 作为顶级入口重新暴露。
- 查流量结构 GET 下载所需的 `Referer`、`Origin` 等页面上下文由 CLI 自动补齐，不让用户手动填写。
