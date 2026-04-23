"""amazon parser 兼容导出。"""

from opscli.amazon.scraping.parser import normalize_text, parse_price, parse_rating, parse_review_count

__all__ = ["normalize_text", "parse_price", "parse_rating", "parse_review_count"]
