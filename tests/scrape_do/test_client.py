import asyncio
import traceback

import httpx
import pytest
import respx

from opscli.scrape_do.api.client import ScrapeDoApiClient, _redact_token
from opscli.scrape_do.domain.exceptions import ScrapeDoApiError


def _run(coro):
    return asyncio.run(coro)


@respx.mock
def test_get_json_returns_payload_and_billing_headers():
    route = respx.get("https://api.scrape.do/plugin/amazon/pdp").mock(
        return_value=httpx.Response(
            200,
            json={"asin": "B0C7BKZ883", "status": "success"},
            headers={"Scrape.do-Request-Cost": "1", "Scrape.do-Remaining-Credits": "99"},
        )
    )

    async def scenario():
        async with ScrapeDoApiClient(timeout_seconds=10) as client:
            return await client.get_json(
                "/plugin/amazon/pdp",
                {"token": "secret-token", "asin": "B0C7BKZ883", "geocode": "US"},
            )

    result = _run(scenario())

    assert route.called
    assert result.payload["asin"] == "B0C7BKZ883"
    assert result.billing == {"request_cost": 1, "remaining_credits": 99}
    assert "secret-token" not in result.safe_url
    assert "token=***" in result.safe_url


@respx.mock
def test_get_json_maps_scrape_do_error_without_leaking_token():
    respx.get("https://api.scrape.do/plugin/amazon/pdp").mock(
        return_value=httpx.Response(400, json={"error": "invalid_zipcode", "message": "bad zip"})
    )

    async def scenario():
        async with ScrapeDoApiClient(timeout_seconds=10) as client:
            with pytest.raises(ScrapeDoApiError) as excinfo:
                await client.get_json(
                    "/plugin/amazon/pdp",
                    {"token": "secret-token", "asin": "B0C7BKZ883", "geocode": "US", "zipcode": "bad"},
                )
            return excinfo.value

    error = _run(scenario())
    assert error.status_code == 400
    assert error.error_code == "invalid_zipcode"
    assert "bad zip" in str(error)
    assert "secret-token" not in str(error)
    assert "secret-token" not in (error.response_excerpt or "")


@respx.mock
def test_get_json_redacts_token_echoed_in_error_message():
    respx.get("https://api.scrape.do/plugin/amazon/pdp").mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_token", "message": "token secret-token is invalid"},
        )
    )

    async def scenario():
        async with ScrapeDoApiClient(timeout_seconds=10) as client:
            with pytest.raises(ScrapeDoApiError) as excinfo:
                await client.get_json(
                    "/plugin/amazon/pdp",
                    {"token": "secret-token", "asin": "B0C7BKZ883", "geocode": "US"},
                )
            return excinfo.value

    error = _run(scenario())
    assert "secret-token" not in str(error)
    assert "secret-token" not in (error.response_excerpt or "")
    assert "token *** is invalid" in str(error)


@respx.mock
def test_get_json_wraps_http_error_without_leaking_token():
    request = httpx.Request(
        "GET",
        "https://api.scrape.do/plugin/amazon/pdp?token=secret-token&asin=B0C7BKZ883",
    )
    respx.get("https://api.scrape.do/plugin/amazon/pdp").mock(
        side_effect=httpx.ConnectError("connection failed for token secret-token", request=request)
    )

    async def scenario():
        async with ScrapeDoApiClient(timeout_seconds=10) as client:
            with pytest.raises(ScrapeDoApiError) as excinfo:
                await client.get_json(
                    "/plugin/amazon/pdp",
                    {"token": "secret-token", "asin": "B0C7BKZ883", "geocode": "US"},
                )
            return excinfo.value

    error = _run(scenario())
    rendered_traceback = "".join(traceback.format_exception(error))
    assert "connection failed" in str(error)
    assert "secret-token" not in str(error)
    assert "secret-token" not in rendered_traceback
    assert "ScrapeDoApiError" in rendered_traceback
    assert error.__cause__ is None
    assert error.response_excerpt is not None
    assert "secret-token" not in error.response_excerpt
    assert "token=***" in error.response_excerpt


def test_redact_token_handles_query_strings():
    assert _redact_token("https://api.scrape.do/plugin/amazon/pdp?token=abc&asin=B0") == (
        "https://api.scrape.do/plugin/amazon/pdp?token=***&asin=B0"
    )
