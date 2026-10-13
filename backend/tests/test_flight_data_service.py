from datetime import date
from typing import Any

import httpx
import pytest

from foresight.services import flight_data_service
from foresight.services.flight_data_service import (
    RateLimitedError,
    fetch_aerodatabox,
)

JUNE_1 = date(2026, 6, 1)


def _arrival(number: str, local: str) -> dict[str, Any]:
    return {
        "number": number,
        "movement": {
            "airport": {"iata": "LHR"},
            "scheduledTime": {"local": local, "utc": f"{local[:16]}Z"},
        },
    }


def _fake_api(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response) -> list[str]:
    """Answer each request with the next response; returns the URLs asked for."""
    urls, queue = [], list(responses)

    def get(url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        response = queue.pop(0)
        response.request = httpx.Request("GET", url)
        return response

    monkeypatch.setattr(flight_data_service.httpx, "get", get)
    monkeypatch.setattr(flight_data_service, "sleep", lambda seconds: None)
    return urls


def test_fetches_both_halves_of_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = _fake_api(monkeypatch, httpx.Response(204), httpx.Response(204))

    assert fetch_aerodatabox(JUNE_1, JUNE_1).empty
    assert [url.split("/DUB/")[1] for url in urls] == [
        "2026-06-01T00:00/2026-06-01T11:59",
        "2026-06-01T12:00/2026-06-01T23:59",
    ]


def test_skips_duplicates_and_the_day_before(monkeypatch: pytest.MonkeyPatch) -> None:
    ei1 = _arrival("EI 1", "2026-06-01 10:05+01:00")
    late = _arrival("FR 2", "2026-05-31 23:50+01:00")
    _fake_api(
        monkeypatch,
        httpx.Response(200, json={"arrivals": [ei1, late]}),
        httpx.Response(200, json={"arrivals": [ei1]}),
    )

    assert list(fetch_aerodatabox(JUNE_1, JUNE_1)["flight_number"]) == ["EI 1"]


def test_rate_limit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    quota = [httpx.Response(429, text="exceeded the MONTHLY quota") for _ in range(4)]
    urls = _fake_api(monkeypatch, *quota)

    with pytest.raises(RateLimitedError, match="MONTHLY quota"):
        fetch_aerodatabox(JUNE_1, JUNE_1)
    assert len(urls) == 4  # 1 try + 3 retries


def test_retries_a_rate_limit_then_carries_on(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = _fake_api(
        monkeypatch, httpx.Response(429), httpx.Response(204), httpx.Response(204)
    )

    assert fetch_aerodatabox(JUNE_1, JUNE_1).empty
    assert len(urls) == 3  # the morning window was asked twice
