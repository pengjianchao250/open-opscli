from opscli.amazon.parser import normalize_text, parse_review_count


def test_normalize_text_removes_zero_width_characters():
    assert normalize_text("New York 10001\u200c") == "New York 10001"


def test_parse_review_count_ignores_rating_only_text():
    assert parse_review_count("4.8 out of 5 stars") is None


def test_parse_review_count_prefers_labeled_review_count():
    value = "4.8 out of 5 stars 29,832 ratings"

    assert parse_review_count(value) == 29832


def test_parse_review_count_supports_amazon_compact_counts():
    assert parse_review_count("(29.8K)") == 29800
