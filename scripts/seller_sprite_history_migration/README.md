# SellerSprite 历史数据迁移

本目录是一次性历史数据迁移工具，不属于 SellerSprite 在线业务逻辑。

工具只在当前进程读取显式传入的 `api_runs` 目录，统一把 XLSX、旧 JSON v1 和 JSON v2
转换为格式化 Dataset/Record，再写入现有采集 MySQL。数据库不保存 raw payload 或本地路径。

推荐入口：

```powershell
uv run python -m scripts.seller_sprite_history_migration audit --source-dir "<api_runs>"
uv run python -m scripts.seller_sprite_history_migration init-schema
uv run python -m scripts.seller_sprite_history_migration migrate --source-dir "<api_runs>" --batch-id "<batch>"
uv run python -m scripts.seller_sprite_history_migration verify --source-dir "<api_runs>" --batch-id "<batch>"
uv run python -m scripts.seller_sprite_history_migration purge --source-dir "<api_runs>" --batch-id "<batch>" --confirm DELETE_VERIFIED_SOURCE
```

`purge` 只有在数据库核验通过且源目录没有残留文件时才会把批次标记为完成；不完整任务和孤立文件不会被自动删除。
