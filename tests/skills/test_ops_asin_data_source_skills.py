import json
from pathlib import Path


ROOT = Path("opscli/skills/templates")


def read_skill(name: str) -> str:
    return (ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def read_version(name: str) -> dict:
    path = ROOT / name / "data" / "VERSION.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_router_delegates_to_three_source_skills():
    text = read_skill("ops-asin-data-collector")

    assert "ops-asin-data-basic" in text
    assert "ops-asin-data-bi" in text
    assert "ops-asin-data-category-top" in text
    assert "live-data" not in text
    assert "fetch-file" not in text
    assert "asin_data_" not in text


def test_router_version_is_0_2_0():
    assert read_version("ops-asin-data-collector")["version"] == "0.2.0"


def test_basic_skill_uses_only_basic_command_and_defines_source_precedence():
    text = read_skill("ops-asin-data-basic")

    assert "opscli asin-data basic" in text
    assert "--source listing" in text
    assert "--source crawler" in text
    assert "listing" in text and "crawler" in text
    assert "A+" in text and "QA" in text and "reviews" in text
    assert "live-data" not in text
    assert "fetch-file" not in text
    assert "asin_data_" not in text
    assert read_version("ops-asin-data-basic")["version"] == "0.1.0"


def test_bi_skill_covers_domains_dates_and_empty_results():
    text = read_skill("ops-asin-data-bi")

    assert "opscli asin-data bi" in text
    assert "--date-from" in text and "--date-to" in text
    for domain in (
        "sales_traffic",
        "sp_search_term",
        "sqp",
        "deals",
        "turnover_inventory",
    ):
        assert f"`{domain}`" in text
    assert "row_count" in text
    assert "0" in text and "success" in text
    assert "live-data" not in text
    assert "asin_data_" not in text
    assert read_version("ops-asin-data-bi")["version"] == "0.1.0"
