import pytest

from opscli.sif.operation_time_machine.scenarios import (
    change_type_for_section,
    normalize_last_months,
    normalize_operation_granularity,
    operation_time_machine_payload,
)


def test_operation_time_machine_payloads_match_sif_contract():
    assert operation_time_machine_payload(asin="B01NBNDC1T", granularity="day", last_months=6) == {
        "granularity": "day",
        "asin": "B01NBNDC1T",
        "endDay": None,
        "interval": None,
        "listingSearch": False,
        "lastMonths": 6,
    }
    assert operation_time_machine_payload(
        asin="B01NBNDC1T",
        granularity="week",
        last_months=12,
        change_type="all",
    )["type"] == "all"


def test_operation_time_machine_param_validation():
    assert normalize_operation_granularity(None) == "day"
    assert normalize_last_months(None) == 6
    assert change_type_for_section("keyword_count_change") == "all"
    with pytest.raises(ValueError):
        normalize_operation_granularity("year")
    with pytest.raises(ValueError):
        normalize_last_months(9)
