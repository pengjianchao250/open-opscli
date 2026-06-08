from opscli.keepa.time import (
    add_keepa_time_conversions,
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)


def test_keepa_minutes_convert_to_utc_unix_epoch():
    assert keepa_minutes_to_unix_seconds(7588958) == 1749177480
    assert keepa_minutes_to_unix_milliseconds(7588958) == 1749177480000
    assert keepa_minutes_to_utc_iso(7588958) == "2025-06-06T02:38:00Z"


def test_add_keepa_time_conversions_preserves_original_values():
    payload = {
        "asin": "B0088PUEPK",
        "lastUpdate": 7588958,
        "salesRank": 7588958,
        "timestamp": 1749177480000,
        "csv": [[7588958, 1299, 7588960, 1399]],
    }

    converted = add_keepa_time_conversions(payload)

    assert converted["lastUpdate"] == 7588958
    assert converted["lastUpdateUnixSeconds"] == 1749177480
    assert converted["lastUpdateUnixMilliseconds"] == 1749177480000
    assert converted["lastUpdateUtc"] == "2025-06-06T02:38:00Z"
    assert "salesRankUnixSeconds" not in converted
    assert "timestampUnixSeconds" not in converted
    assert converted["csv"][0][0] == 7588958
    assert converted["csvUnixSeconds"][0] == [1749177480, 1299, 1749177600, 1399]
