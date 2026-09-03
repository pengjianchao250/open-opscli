import asyncio

from opscli.shared.collection_storage.result_cache import (
    DEFAULT_RESULT_CACHE_TTL_SECONDS,
    attach_cache_metadata,
    build_cache_key,
    find_cached_result,
    result_cache_ttl_seconds,
)


def test_cache_key_is_stable_for_equivalent_mapping_order():
    first = build_cache_key(
        "keepa",
        {"scenario": "product", "params": {"history": False, "asin": "B0TEST"}},
    )
    second = build_cache_key(
        "keepa",
        {"params": {"asin": "B0TEST", "history": False}, "scenario": "product"},
    )

    assert first == second
    assert len(first) == 64


def test_attach_cache_metadata_does_not_mutate_source_payload():
    source = {"normalized_params": {"asin": "B0TEST"}}

    payload = attach_cache_metadata(
        source,
        cache_key="a" * 64,
        cache_scope="shared",
        result_metadata={"row_count": 1},
    )

    assert "_cache" not in source
    assert payload["_cache"] == {
        "version": 1,
        "cache_key": "a" * 64,
        "cache_scope": "shared",
        "result": {"row_count": 1},
    }


def test_cache_ttl_defaults_to_one_day_for_invalid_values(monkeypatch):
    monkeypatch.setenv("OPSCLI_COLLECTION_RESULT_CACHE_TTL_SECONDS", "invalid")

    assert result_cache_ttl_seconds() == DEFAULT_RESULT_CACHE_TTL_SECONDS


def test_live_cache_mode_skips_repository_lookup():
    class Repository:
        def find_cached_result(self, **_kwargs):
            raise AssertionError("live 模式不得读取缓存")

    result = asyncio.run(
        find_cached_result(
            Repository(),
            source_system="keepa",
            data_environment="production",
            scenario="product",
            site="US",
            cache_key="a" * 64,
            cache_scope="shared",
            cache_mode="live",
        )
    )

    assert result is None


def test_cache_lookup_failure_falls_back_to_live():
    class Repository:
        def find_cached_result(self, **_kwargs):
            raise RuntimeError("mysql unavailable")

    result = asyncio.run(
        find_cached_result(
            Repository(),
            source_system="keepa",
            data_environment="production",
            scenario="product",
            site="US",
            cache_key="a" * 64,
            cache_scope="shared",
        )
    )

    assert result is None
