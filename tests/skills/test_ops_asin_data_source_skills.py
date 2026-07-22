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
