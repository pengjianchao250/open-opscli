"""支持使用 `python -m scripts.seller_sprite_history_migration` 执行迁移。"""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
