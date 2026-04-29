# 补货计算公式

## 基础公式

```
补货量 = (目标库存天数 × 日均销量) - (平台库存 + 海外仓可售 + 在途)
```

## 考虑因素

1. **交期（Lead Time）**
   - 海运：30-45 天
   - 空运：7-14 天
   - 生产：14-30 天

2. **安全库存（Safety Stock）**
   - 公式：Lead Time × 日均销量 × 安全系数
   - 安全系数：稳定产品 1.2，波动大产品 1.5，新品 2.0

3. **季节性调整**
   - 旺季前 2-3 个月增加目标库存天数
   - 旺季倍数：参考历史同期销售倍数

4. **促销调整**
   - 大促前提前备货
   - 促销期间日均销量 = 正常日均 × 促销倍数

## 完整计算示例

```python
# SKU: ED-12345，水瓶
base_daily_sales = 15
seasonal_factor = 1.8  # 夏季旺季
lead_time = 35  # 海运
target_days = 60

adjusted_daily_sales = base_daily_sales * seasonal_factor  # 27
target_inventory = target_days * adjusted_daily_sales  # 1620
current_available = 400  # 平台 + 海外仓 + 在途
safety_stock = lead_time * adjusted_daily_sales * 1.2  # 1134

replenishment_qty = target_inventory - current_available + safety_stock
# = 1,620 - 400 + 1,134 = 2,354

# 建议：分两批发货
# 第一批：1,200（空运应急，10 天后到）
# 第二批：1,200（海运，45 天后到）
```
