# SellerSprite 官方导出回归基线

本目录保存从卖家精灵官网实际导出的只读 XLSX，用于核对本地导出的工作表、表头、列顺序、值类型和版式。

管理规则：

- 按正式或研究中的 `scenario` 分目录，保留官网原始文件名。
- 文件属于 immutable golden fixture；需要更新时新增文件并同步 `index.json`，不要静默覆盖。
- `index.json` 记录文件大小和 SHA-256；`tests/seller_sprite/test_official_export_fixtures.py` 校验清单完整性、哈希和 XLSX ZIP 结构。
- fixture 不放在 `output/`，避免与本地运行产物混淆。
- fixture 不放在 `opscli/seller_sprite/reference/`，避免被误认为运行时数据或进入发行包。
- 原件不得包含 Cookie、Authorization、账号密码或其他登录凭据；若包含个人信息或内部业务数据，应先脱敏再提交。
- 本地导出可以按场景明确排除官网 `Notes` 页；官方原件仍保持不变，用于证明两者差异。

当前场景：

| 场景 | 用途 |
| --- | --- |
| `ads-insights` | 广告洞察研究基线，场景尚未正式注册 |
| `keyword-comparison` | 流量词对比动态列和辅助工作表基线 |
| `traffic-extend` | 拓展流量词主表、词频表、ASIN 与 Notes 基线 |
| `keyword-conversion-rate` | 关键词转化率 33 列主表和 Notes 基线 |
| `real-time-bidding` | 实时查竞价列表导出的 46 列主表和 Notes 基线 |
