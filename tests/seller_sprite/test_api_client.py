import asyncio

import httpx
import pytest

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.api.client import SellerSpriteApiClient
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError


def _run(coro):
    return asyncio.run(coro)


def test_get_bytes_returns_official_xlsx_and_filename(tmp_path):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            content=b"PK\x03\x04official-workbook",
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content-disposition": (
                    "attachment; filename*=UTF-8''ABA-Reverse-B00000JBNX-US.xlsx"
                ),
            },
        )

    async def scenario():
        client = SellerSpriteApiClient(
            account=SellerSpriteAccount(
                name="default",
                username="user@example.com",
                password="secret",
            ),
            cookie_path=tmp_path / "cookies.json",
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await client.get_bytes(
                "/v2/aba/reverse/export",
                {"station": "US", "asin": "B00000JBNX"},
                referer="https://www.sellersprite.com/v2/aba/reverse/search",
            )
        finally:
            await client.aclose()

    content, filename = _run(scenario())

    assert content == b"PK\x03\x04official-workbook"
    assert filename == "ABA-Reverse-B00000JBNX-US.xlsx"
    assert requests[0].url.params["asin"] == "B00000JBNX"
    assert "spreadsheetml.sheet" in requests[0].headers["Accept"]


def test_get_bytes_rejects_login_html(tmp_path):
    async def handler(request):
        return httpx.Response(
            200,
            text='<a href="/cn/w/user/login">登录</a>',
            headers={"content-type": "text/html; charset=utf-8"},
        )

    async def scenario():
        client = SellerSpriteApiClient(
            account=SellerSpriteAccount(
                name="default",
                username="user@example.com",
                password="secret",
            ),
            cookie_path=tmp_path / "cookies.json",
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await client.get_bytes("/v2/aba/reverse/export", {})
        finally:
            await client.aclose()

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(scenario())

    assert exc_info.value.api_code == "ERR_GLOBAL_SESSION_EXPIRED"
