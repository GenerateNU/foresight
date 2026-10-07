"""PredictHQ adapter against a mocked API: request shape, paging, field mapping."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from foresight.ingest.normalize import EventCategory, EventStatus, Source
from foresight.ingest.predicthq import API_URL, fetch_events, to_normalized


def _raw(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "z13B8ehGzCCZjPM3Ff",
        "title": "Fontaines D.C.",
        "category": "concerts",
        "state": "active",
        # 20:00 in Dublin, which is already 19:00Z: the local and UTC dates agree.
        "start": "2026-11-14T19:00:00Z",
        "end": "2026-11-14T22:30:00Z",
        "timezone": "Europe/Dublin",
        "location": [-6.2286, 53.3478],
        "country": "IE",
        "rank": 68,
        "local_rank": 81,
        "phq_attendance": 13000,
        "entities": [
            {"type": "event-group", "name": "Fontaines D.C. Tour"},
            {"type": "venue", "name": "3Arena"},
        ],
        "updated": "2026-10-05T08:12:44Z",
    }
    return base | overrides


def test_maps_geojson_ranks_and_venue() -> None:
    event = to_normalized(_raw(), city="Dublin")

    assert event.source is Source.PREDICTHQ
    assert (event.latitude, event.longitude) == (53.3478, -6.2286)
    assert (event.impact_rank, event.local_rank) == (68, 81)
    assert event.venue == "3Arena"
    assert event.category is EventCategory.CONCERTS
    assert event.expected_attendance == 13000
    assert event.confidence == 1.0
    assert event.source_updated_at == datetime(2026, 10, 5, 8, 12, 44, tzinfo=UTC)
    assert event.payload["id"] == "z13B8ehGzCCZjPM3Ff"


def test_late_evening_event_keeps_its_local_night() -> None:
    # 21:30 in Los Angeles on 14 Nov is 05:30Z on 15 Nov.
    event = to_normalized(
        _raw(
            start="2026-11-15T05:30:00Z",
            end="2026-11-15T07:00:00Z",
            timezone="America/Los_Angeles",
            location=[-118.2673, 34.0430],
        ),
        city="Los Angeles",
    )

    assert event.start_local_date == date(2026, 11, 14)
    assert event.end_local_date == date(2026, 11, 14)


def test_deleted_state_becomes_deleted_status() -> None:
    event = to_normalized(
        _raw(state="deleted", deleted_reason="cancelled"), city="Dublin"
    )
    assert event.status is EventStatus.DELETED


def test_unknown_category_falls_back() -> None:
    event = to_normalized(_raw(category="something-new"), city="Dublin")
    assert event.category is EventCategory.UNKNOWN


async def test_fetch_filters_by_radius_and_revision_clock_and_follows_next() -> None:
    requests: list[httpx.Request] = []
    page_two = f"{API_URL}?offset=1&limit=500"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("offset") == "1":
            return httpx.Response(
                200,
                json={
                    "count": 3,
                    "next": None,
                    "results": [
                        _raw(id="b", state="deleted"),
                        _raw(id="bad", title="(Live)"),
                    ],
                },
            )
        return httpx.Response(
            200, json={"count": 3, "next": page_two, "results": [_raw(id="a")]}
        )

    result = await fetch_events(
        token="test-token",
        latitude=53.3498,
        longitude=-6.2603,
        city="Dublin",
        updated_since=datetime(2026, 9, 29, 14, 0, tzinfo=UTC),
        transport=httpx.MockTransport(handler),
    )

    first = requests[0]
    assert first.headers["Authorization"] == "Bearer test-token"
    assert first.url.params["within"] == "10km@53.3498,-6.2603"
    assert first.url.params["updated.gte"] == "2026-09-29T14:00:00"
    assert first.url.params["limit"] == "500"
    assert "deleted" in first.url.params["state"].split(",")
    assert len(requests) == 2

    assert result.fetched == 3
    assert [e.source_ref for e in result.events] == ["a", "b"]
    assert result.events[1].status is EventStatus.DELETED
    assert [r.source_ref for r in result.rejected] == ["bad"]
    assert "normalizes to empty" in result.rejected[0].reason


async def test_record_missing_required_field_is_rejected_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        broken = _raw(id="nostart")
        del broken["start"]
        return httpx.Response(200, json={"count": 1, "next": None, "results": [broken]})

    result = await fetch_events(
        token="t",
        latitude=0.0,
        longitude=0.0,
        city="Dublin",
        updated_since=datetime(2026, 9, 29, tzinfo=UTC),
        transport=httpx.MockTransport(handler),
    )

    assert result.events == []
    assert result.rejected[0].reason == "missing field 'start'"
