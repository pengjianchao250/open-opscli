# Keepa Lightning Deal Object 格式化合同

> 实现文件：`opscli/keepa/lightning_deal_formatter.py`；接入场景：`lightning-deals`。

- `dealPrice`、`currentPrice` 按站点货币最小单位派生十进制金额。
- `lastUpdate`、`startTime`、`endTime` 派生 UTC 与 Unix 时间。
- `rating` 除以 10；`image` 派生 Amazon CDN URL。
- `dealState`、`percentClaimed`、`percentOff` 保留官方原值。
- `variation` 从主表移除，每个 dimension/value 输出到 `lightning_variations`。
- 完整原始对象仍保存在 `raw.json`。
- 2026-08-20 完整 US 列表真实验证：返回 23,788 个 Deal Object 和 45,374 条 variation，主表与变体表均无嵌套单元格。
