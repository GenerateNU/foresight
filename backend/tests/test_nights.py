"""Which events affect each night, and the routes that serve them.

No database: the repository read and the hotel lookup are replaced, so the
tests exercise the night rule and the HTTP mapping on their own.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from foresight.database.enums import EventCategory, EventStatus
from foresight.database.models.signals.event import Event
from foresight.database.session import get_session
from foresight.main import app
from foresight.services.domain import event as event_service
from foresight.services.domain import recommendation as recommendation_service
from foresight.services.errors import InvalidRequestError

D = date


def make_event(
    id: int,
    title: str,
    start: date,
    end: date | None = None,
    *,
    category: EventCategory = EventCategory.FESTIVALS,
    status: EventStatus = EventStatus.ACTIVE,
    venue: str | None = "Example Hall",
    attendance: int | None = None,
    local_rank: int | None = None,
) -> Event:
    return Event(
        id=id,
        title=title,
        category=category,
        status=status,
        venue=venue,
        start_local_date=start,
        end_local_date=end or start,
        expected_attendance=attendance,
        local_rank=local_rank,
    )


@pytest.fixture
def stored_events(monkeypatch: pytest.MonkeyPatch) -> list[Event]:
    """Events the fake repository returns for any range, like the real query
    does for ones overlapping it; tests append to it."""
    events: list[Event] = []

    async def get_hotel(session, hotel_id):
        return SimpleNamespace(id=hotel_id, city_id=1)

    async def list_events_overlapping(session, *, city_id, start, end):
        return [
            e for e in events if e.end_local_date >= start and e.start_local_date <= end
        ]

    monkeypatch.setattr(event_service, "get_hotel", get_hotel)
    monkeypatch.setattr(
        event_service.event_repo, "list_events_overlapping", list_events_overlapping
    )
    return events


async def nights(start: date, end: date):
    return await event_service.events_by_night(None, 1, start=start, end=end)


async def test_single_day_event_shows_on_its_night_only(stored_events) -> None:
    stored_events.append(make_event(1, "Match", D(2025, 5, 2), attendance=40000))

    result = await nights(D(2025, 5, 1), D(2025, 5, 3))

    assert list(result) == [D(2025, 5, 1), D(2025, 5, 2), D(2025, 5, 3)]
    assert result[D(2025, 5, 1)] == []
    assert result[D(2025, 5, 3)] == []
    [shown] = result[D(2025, 5, 2)]
    assert (shown.title, shown.venue, shown.category) == (
        "Match",
        "Example Hall",
        EventCategory.FESTIVALS,
    )
    assert shown.expected_attendance == 40000
    assert (shown.day_number, shown.day_count) == (1, 1)


async def test_multi_day_event_shows_on_each_night_as_day_n_of_m(
    stored_events,
) -> None:
    stored_events.append(make_event(1, "Festival", D(2025, 6, 6), D(2025, 6, 8)))

    result = await nights(D(2025, 6, 5), D(2025, 6, 9))

    days = {
        night: [(e.day_number, e.day_count) for e in events]
        for night, events in result.items()
    }
    assert days == {
        D(2025, 6, 5): [],
        D(2025, 6, 6): [(1, 3)],
        D(2025, 6, 7): [(2, 3)],
        D(2025, 6, 8): [(3, 3)],
        D(2025, 6, 9): [],
    }


async def test_event_started_before_the_range_keeps_its_day_numbers(
    stored_events,
) -> None:
    stored_events.append(make_event(1, "Festival", D(2025, 6, 6), D(2025, 6, 8)))

    result = await nights(D(2025, 6, 7), D(2025, 6, 7))

    [shown] = result[D(2025, 6, 7)]
    assert (shown.day_number, shown.day_count) == (2, 3)


async def test_overlapping_events_are_sorted_by_attendance_then_rank(
    stored_events,
) -> None:
    night = D(2025, 7, 10)
    stored_events += [
        make_event(1, "Small", night, attendance=500, local_rank=90),
        make_event(2, "Big", night, D(2025, 7, 12), attendance=20000, local_rank=10),
        make_event(3, "Mid, high rank", night, attendance=5000, local_rank=80),
        make_event(4, "Mid, low rank", night, attendance=5000, local_rank=20),
        make_event(5, "Unknown", night, attendance=None, local_rank=None),
    ]

    result = await nights(night, D(2025, 7, 11))

    assert [e.title for e in result[night]] == [
        "Big",
        "Mid, high rank",
        "Mid, low rank",
        "Small",
        "Unknown",
    ]
    assert [e.title for e in result[D(2025, 7, 11)]] == ["Big"]


async def test_event_without_venue_or_attendance_still_shows(stored_events) -> None:
    stored_events.append(make_event(1, "Fair", D(2025, 8, 1), venue=None))

    [shown] = (await nights(D(2025, 8, 1), D(2025, 8, 1)))[D(2025, 8, 1)]

    assert shown.title == "Fair"
    assert shown.venue is None
    assert shown.expected_attendance is None


@pytest.mark.parametrize("status", [EventStatus.CANCELLED, EventStatus.DELETED])
async def test_withdrawn_events_are_hidden(stored_events, status: EventStatus) -> None:
    night = D(2025, 9, 1)
    stored_events += [
        make_event(1, "Gone", night, D(2025, 9, 2), status=status, attendance=99999),
        make_event(2, "Live", night, attendance=10),
    ]

    result = await nights(night, D(2025, 9, 2))

    assert [e.title for e in result[night]] == ["Live"]
    assert result[D(2025, 9, 2)] == []


async def test_provisional_events_are_shown(stored_events) -> None:
    stored_events.append(
        make_event(1, "Rumoured", D(2025, 9, 1), status=EventStatus.PROVISIONAL)
    )

    result = await nights(D(2025, 9, 1), D(2025, 9, 1))

    assert [e.title for e in result[D(2025, 9, 1)]] == ["Rumoured"]


async def test_holidays_show_and_categories_the_model_ignores_do_not(
    stored_events,
) -> None:
    night = D(2025, 12, 25)
    stored_events += [
        make_event(1, "Christmas", night, category=EventCategory.PUBLIC_HOLIDAYS),
        make_event(2, "Winter break", night, category=EventCategory.SCHOOL_HOLIDAYS),
        make_event(3, "Concert", night, category=EventCategory.CONCERTS),
        make_event(4, "Storm", night, category=EventCategory.SEVERE_WEATHER),
        make_event(5, "Delays", night, category=EventCategory.AIRPORT_DELAYS),
    ]

    result = await nights(night, night)

    assert {e.title for e in result[night]} == {"Christmas", "Winter break", "Concert"}


async def test_end_before_start_is_invalid(stored_events) -> None:
    with pytest.raises(InvalidRequestError):
        await nights(D(2025, 1, 2), D(2025, 1, 1))


# Routes


@pytest.fixture
async def client():
    async def no_session():
        return None

    app.dependency_overrides[get_session] = no_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_night_route_returns_full_details(client, stored_events) -> None:
    stored_events += [
        make_event(1, "Festival", D(2025, 6, 6), D(2025, 6, 8), attendance=9000),
        make_event(2, "Gone", D(2025, 6, 7), status=EventStatus.CANCELLED),
    ]

    response = await client.get("/hotels/1/events/2025-06-07")

    assert response.status_code == 200
    assert response.json() == {
        "hotel_id": 1,
        "stay_date": "2025-06-07",
        "events": [
            {
                "event_id": 1,
                "title": "Festival",
                "venue": "Example Hall",
                "category": "festivals",
                "expected_attendance": 9000,
                "day_number": 2,
                "day_count": 3,
            }
        ],
    }


async def test_range_route_returns_rates_with_event_names_only(
    client, stored_events, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored_events += [
        make_event(1, "Small", D(2025, 6, 6), attendance=10),
        make_event(2, "Big", D(2025, 6, 6), D(2025, 6, 7), attendance=1000),
        make_event(3, "Gone", D(2025, 6, 6), status=EventStatus.DELETED),
    ]

    async def get_recommendation(session, hotel_id, stay_date, *, room_type_id):
        return SimpleNamespace(recommended_rate=Decimal("150.00"), currency="EUR")

    monkeypatch.setattr(
        recommendation_service, "get_recommendation", get_recommendation
    )

    response = await client.get(
        "/hotels/1/recommendations/range?start=2025-06-06&end=2025-06-08"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "stay_date": "2025-06-06",
            "recommended_rate": "150.00",
            "currency": "EUR",
            "event_names": ["Big", "Small"],
        },
        {
            "stay_date": "2025-06-07",
            "recommended_rate": "150.00",
            "currency": "EUR",
            "event_names": ["Big"],
        },
        {
            "stay_date": "2025-06-08",
            "recommended_rate": "150.00",
            "currency": "EUR",
            "event_names": [],
        },
    ]


async def test_range_route_rejects_an_oversized_or_reversed_range(
    client, stored_events
) -> None:
    too_long = await client.get(
        "/hotels/1/recommendations/range?start=2025-01-01&end=2025-12-31"
    )
    reversed_ = await client.get(
        "/hotels/1/recommendations/range?start=2025-02-01&end=2025-01-01"
    )

    assert too_long.status_code == 422
    assert reversed_.status_code == 422
