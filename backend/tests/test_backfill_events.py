from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from foresight.config import settings
from foresight.database.models.event import Event, EventObservation
from foresight.repository.upsert import Outcome
from foresight.services.backfill.events import backfill, month_chunks
from foresight.services.ingest import predicthq
from foresight.services.ingest.predicthq import (
    API_URL,
    MAX_RETRIES,
    Market,
    OutOfCreditsError,
    PredictHQRetriesExhaustedError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

DUBLIN = Market(city="Dublin", latitude=53.3498, longitude=-6.2603)


class FakeSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _raw(event_id: str, day: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "title": f"Gig {event_id}",
        "category": "concerts",
        "state": "active",
        "start": f"{day}T19:00:00Z",
        "end": f"{day}T22:00:00Z",
        "timezone": "Europe/Dublin",
        "location": [-6.2286, 53.3478],
        "country": "IE",
        "updated": "2025-01-01T00:00:00Z",
    }


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _drain(*args: Any, **kwargs: Any) -> Any:
    """Run a backfill to the end and return its last report."""
    report = None
    async for report in backfill(*args, **kwargs):  # noqa: B007
        pass
    return report


def _replies(*responses: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    queue = list(responses)
    return lambda request: queue.pop(0)


def test_month_chunks_split_partial_months() -> None:
    assert month_chunks(date(2024, 1, 15), date(2024, 3, 10)) == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 10)),
    ]


def test_month_chunks_single_day() -> None:
    day = date(2025, 6, 30)
    assert month_chunks(day, day) == [(day, day)]


def test_chunk_params_cover_the_chunk_with_slack_and_no_revision_filter() -> None:
    params = predicthq.window_params(DUBLIN, date(2025, 3, 1), date(2025, 3, 31))

    assert params["active.gte"] == "2025-02-28"
    assert params["active.lte"] == "2025-04-01"
    assert params["within"] == "10km@53.3498,-6.2603"
    assert "updated.gte" not in params


async def test_success_never_waits() -> None:
    sleep = FakeSleep()
    async with _client(_replies(httpx.Response(200, json={"results": []}))) as client:
        assert await predicthq.get_page(client, API_URL, None, sleep=sleep) == {
            "results": []
        }
    assert sleep.waits == []


async def test_rate_limit_backs_off_then_succeeds() -> None:
    sleep = FakeSleep()
    handler = _replies(
        httpx.Response(429), httpx.Response(429), httpx.Response(200, json={})
    )
    async with _client(handler) as client:
        await predicthq.get_page(client, API_URL, None, sleep=sleep)
    assert sleep.waits == [2.0, 4.0]


async def test_rate_limit_honours_retry_after() -> None:
    sleep = FakeSleep()
    handler = _replies(
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})
    )
    async with _client(handler) as client:
        await predicthq.get_page(client, API_URL, None, sleep=sleep)
    assert sleep.waits == [7.0]


async def test_gives_up_after_every_retry() -> None:
    sleep = FakeSleep()
    async with _client(lambda request: httpx.Response(429)) as client:
        with pytest.raises(PredictHQRetriesExhaustedError):
            await predicthq.get_page(client, API_URL, None, sleep=sleep)
    assert len(sleep.waits) == MAX_RETRIES


async def test_out_of_credits_stops_without_waiting() -> None:
    sleep = FakeSleep()
    async with _client(_replies(httpx.Response(402, text="quota exceeded"))) as client:
        with pytest.raises(OutOfCreditsError, match="quota exceeded"):
            await predicthq.get_page(client, API_URL, None, sleep=sleep)
    assert sleep.waits == []


async def test_dry_run_counts_without_a_database() -> None:
    page = {"results": [_raw("phq-a", "2025-03-05"), {"id": "phq-bad"}]}
    report = await _drain(
        None,
        DUBLIN,
        date(2025, 3, 1),
        date(2025, 3, 31),
        token="t",
        transport=httpx.MockTransport(_replies(httpx.Response(200, json=page))),
        sleep=FakeSleep(),
    )

    assert (report.fetched, len(report.rejected), report.chunks_done) == (2, 1, 1)
    assert report.stopped is None


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(settings.database_url)
    try:
        conn = await engine.connect()
    except (OSError, ConnectionError) as exc:
        await engine.dispose()
        pytest.skip(f"Postgres unavailable: {exc}")

    trans = await conn.begin()
    async with AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint"
    ) as session:
        await session.execute(delete(EventObservation))
        await session.execute(delete(Event))
        yield session
    await trans.rollback()
    await conn.close()
    await engine.dispose()


async def test_out_of_credits_keeps_earlier_pages_and_rerun_adds_no_duplicates(
    session: AsyncSession,
) -> None:
    page_1 = {
        "results": [_raw("phq-a", "2025-03-05"), _raw("phq-b", "2025-03-12")],
        "next": f"{API_URL}?page=2",
    }
    page_2 = {"results": [_raw("phq-c", "2025-03-20")]}
    march = (date(2025, 3, 1), date(2025, 3, 31))

    stopped = await _drain(
        session,
        DUBLIN,
        *march,
        token="t",
        transport=httpx.MockTransport(
            _replies(httpx.Response(200, json=page_1), httpx.Response(402))
        ),
        sleep=FakeSleep(),
    )
    assert stopped.stopped is not None
    assert stopped.resume_from == date(2025, 3, 1)
    assert await session.scalar(select(func.count()).select_from(Event)) == 2

    resumed = await _drain(
        session,
        DUBLIN,
        *march,
        token="t",
        transport=httpx.MockTransport(
            _replies(httpx.Response(200, json=page_1), httpx.Response(200, json=page_2))
        ),
        sleep=FakeSleep(),
    )
    assert resumed.stopped is None
    assert resumed.outcomes[Outcome.NEW] == 1
    assert await session.scalar(select(func.count()).select_from(Event)) == 3


async def test_yields_after_each_month_without_committing() -> None:
    empty = httpx.Response(200, json={"results": []})
    reports = [
        report.chunks_done
        async for report in backfill(
            None,
            DUBLIN,
            date(2025, 1, 15),
            date(2025, 3, 10),
            token="t",
            transport=httpx.MockTransport(lambda request: empty),
            sleep=FakeSleep(),
        )
    ]
    assert reports == [1, 2, 3]
