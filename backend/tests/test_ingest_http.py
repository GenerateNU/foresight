"""The shared retrying request every external adapter goes through."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from foresight.services.ingest.http import RetriesExhaustedError, send

if TYPE_CHECKING:
    from collections.abc import Callable

URL = "https://api.example/thing"


class FakeSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _client(*responses: httpx.Response | Exception) -> httpx.AsyncClient:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _send(client: httpx.AsyncClient, sleep: Callable, **kw) -> httpx.Response:
    async with client:
        return await send(client, "GET", URL, sleep=sleep, **kw)


async def test_success_returns_immediately() -> None:
    sleep = FakeSleep()
    response = await _send(_client(httpx.Response(200)), sleep)
    assert response.status_code == 200
    assert sleep.waits == []


async def test_backs_off_exponentially_then_succeeds() -> None:
    sleep = FakeSleep()
    client = _client(httpx.Response(503), httpx.Response(429), httpx.Response(200))
    response = await _send(client, sleep, backoff=1.0)
    assert response.status_code == 200
    assert sleep.waits == [1.0, 2.0]


async def test_retry_after_overrides_backoff() -> None:
    sleep = FakeSleep()
    client = _client(
        httpx.Response(429, headers={"Retry-After": "9"}), httpx.Response(200)
    )
    await _send(client, sleep)
    assert sleep.waits == [9.0]


async def test_network_errors_are_retried() -> None:
    sleep = FakeSleep()
    client = _client(httpx.ConnectError("down"), httpx.Response(200))
    assert (await _send(client, sleep)).status_code == 200
    assert len(sleep.waits) == 1


async def test_a_4xx_is_returned_not_retried() -> None:
    sleep = FakeSleep()
    response = await _send(_client(httpx.Response(402)), sleep)
    assert response.status_code == 402
    assert sleep.waits == []


async def test_gives_up_with_the_last_response() -> None:
    sleep = FakeSleep()
    client = _client(*(httpx.Response(429, text="quota") for _ in range(3)))
    with pytest.raises(RetriesExhaustedError) as caught:
        await _send(client, sleep, max_retries=2)
    assert caught.value.response is not None
    assert caught.value.response.text == "quota"
    assert len(sleep.waits) == 2  # no wait after the final attempt
