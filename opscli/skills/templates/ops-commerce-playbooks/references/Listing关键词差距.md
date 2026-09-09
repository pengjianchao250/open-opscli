# Listing 关键词差距

## 适用请求

比较自己的 ASIN 与一组已经确认的竞品，识别已有词、共同词、缺失词和不应使用的词，并映射到 Listing 与广告验证动作。

如果用户还没有可靠竞品，先读取 [如何找竞品.md](如何找竞品.md)，不要让模型随意指定竞品。

## 输入

- 自己的 ASIN：1 个。
- 已确认竞品 ASIN：建议 3—10 个，且不包含自己的 ASIN。
- 站点和周期。
- 可选：核心关键词、产品用途和不能宣称的属性。

先归并同一父体下的变体，避免一个竞品家族重复加权。

## 数据步骤

### 1. 建立自己的关键词基线

```bash
opscli seller-sprite run keyword-reverse \
  --site US \
  --period 30d \
  --params '{"asin":"B0MYASIN00"}' \
  --export-format json
```

### 2. 建立竞品合并词池

```bash
opscli seller-sprite run traffic-extend \
  --site US \
  --period 30d \
  --params '{"asins":["B0COMP0001","B0COMP0002","B0COMP0003"]}' \
  --export-format json
```

### 3. 比较流量词覆盖

```bash
opscli seller-sprite run keyword-comparison \
  --site US \
  --period 30d \
  --params '{"ownAsin":"B0MYASIN00","competitorAsins":["B0COMP0001","B0COMP0002","B0COMP0003"]}' \
  --export-format json
```

当前 `traffic-extend` 和 `keyword-comparison` 只覆盖既定视图的第一页最多 100 条，结论必须注明范围。

### 4. 验证相关性

读取自己与竞品的 Amazon 商品页面。只有关键词真实对应产品用途、规格、功能或买家问题时，才进入 Listing 候选；品牌词、错配规格、竞品独有功能和无法兑现的承诺进入排除词。

需要市场转化线索时，可按 `ops-seller-sprite` 规则追加 `keyword-conversion-rate` 或 `aba-reverse`；需要长期趋势时再使用 Google Trends。它们是增强证据，不替代自己的广告搜索词和订单结果。

## 判断与输出

将关键词分为：

- 已覆盖核心词
- 竞品共同覆盖而自己缺失的词
- 细分属性、场景和问题长尾词
- 品牌词
- 不相关或不能兑现的排除词

输出：

| 关键词 | 分类 | 自己证据 | 竞品证据 | 产品相关性 | 建议位置 | 验证动作 |
| --- | --- | --- | --- | --- | --- | --- |

`建议位置` 可使用标题、五点、图片、A+、后台 Search Terms、广告测试或排除。关键词缺失不等于必须写入 Listing；没有产品证据时，只能建议验证，不能生成确定性卖点。
