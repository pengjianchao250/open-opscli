# 3D 标签字典规范

## 维度 1：结构/版型（Structural/Fit）

| 内部字段 | 取值示例 | 标签标准化规则 |
|---------|---------|--------------|
| development_type | 自主研发 / OEM贴牌 / 外采成品 | 直接使用，去空格 |
| sku_type | A级 / B级 / C级 | 统一为大写字母+级 |
| style_name | 简约 / 复古 / 工业 | 建立同义词映射表 |
| protection_level | 高 / 中 / 低 | 统一为中文 |

## 维度 2：材料/工艺（Material/Process）

| 内部字段 | 取值示例 | 标签标准化规则 |
|---------|---------|--------------|
| category | Kitchen / Home / Electronics | 直接使用 |
| sec_category | Gadgets / Decor / Tools | 直接使用 |
| model | 型号编码 | 按前缀聚类 |
| pmc_type | PMC等级 | 映射为高/中/低 |

## 维度 3：设计元素（Design Elements）

| 内部字段 | 取值示例 | 标签标准化规则 |
|---------|---------|--------------|
| level_name | 普通 / 精品 / 旗舰 | 直接使用 |
| platform_name | Amazon / Walmart | 直接使用 |
| country_name | US / UK / DE | 大写标准化 |
| channel_name | FBA / FBM | 直接使用 |

## 标签优先级规则

当多个标签描述同一属性时，优先级：
1. `query_product_set` 字段优先于 `order_sale_trend_*` 字段
2. 枚举值优先于自由文本
3. 中文标签优先于英文标签
