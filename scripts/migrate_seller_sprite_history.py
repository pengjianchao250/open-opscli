"""卖家精灵历史数据回流 MySQL 的受控脚本入口。"""

from opscli.seller_sprite.history_migration_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
