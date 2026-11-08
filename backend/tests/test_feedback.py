"""Manager feedback: added, changed (a new version), listed and validated.

The manager sends the rate they chose and the recommendation they saw; the
verdict is worked out from the two (decision 0050).

Service tests run against the real database (the `session` fixture rolls back).
Route tests send real requests as a signed-in user linked to the hotel.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from foresight.database.enums import (
    FeedbackReasonTag,
    FeedbackTiming,
    FeedbackVerdict,
)
from foresight.database.models import City, Hotel, RoomType
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain import feedback as service
from foresight.services.domain import user as user_service
from foresight.services.errors import InvalidRequestError, NotFoundError
from tests.test_access import make_user


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Dublin")).date()  # the test city's zone


FUTURE = _today() + timedelta(days=30)
PAST = _today() - timedelta(days=30)
RECOMMENDED = Decimal("200.00")  # every test snapshot's rate


async def _give(session, priced, stay_date=FUTURE, **overrides):
    """Saves feedback; unless a snapshot_id is given, against a new snapshot
    for the night (and room type) recommending RECOMMENDED."""
    if "snapshot_id" not in overrides:
        snapshot = await _snapshot(
            session,
            priced,
            stay_date,
            room_type_id=overrides.get("room_type_id"),
        )
        overrides["snapshot_id"] = snapshot.id
    args = {
        "room_type_id": priced.room_type_id,
        "stay_date": stay_date,
        "rate": Decimal("210.00"),
        "reason_tags": [],
        "reason_text": None,
    } | overrides
    return await service.add_feedback(session, priced.hotel_id, **args)


async def _snapshot(session, priced, stay_date, hotel_id=None, room_type_id=None):
    return await snapshot_repo.create_recommendation_snapshot(
        session,
        hotel_id=hotel_id or priced.hotel_id,
        room_type_id=room_type_id or priced.room_type_id,
        stay_date=stay_date,
        model_id=priced.model_id,
        model_version="ebm-v1",
        rate=RECOMMENDED,
        interval_low=Decimal("180.00"),
        interval_high=Decimal("220.00"),
        interval_level=0.8,
        uncertainty=Decimal("5.00"),
        factors={},
        inputs={},
        inputs_hash="",
    )


# Adding


async def test_feedback_can_be_added_for_a_future_night(session, priced) -> None:
    saved = await _give(
        session,
        priced,
        FUTURE,
        rate=Decimal("310.50"),
        reason_tags=[FeedbackReasonTag.GROUP_OR_WEDDING_BLOCK],
        reason_text="Wedding block of 20 rooms",
    )

    assert (saved.version, saved.timing) == (1, FeedbackTiming.BEFORE)
    assert saved.rate == Decimal("310.50")
    assert saved.reason_tags == [FeedbackReasonTag.GROUP_OR_WEDDING_BLOCK]
    assert saved.reason_text == "Wedding block of 20 rooms"
    assert saved.created_at is not None


async def test_feedback_can_be_added_for_a_past_night(session, priced) -> None:
    saved = await _give(session, priced, PAST)

    assert (saved.version, saved.timing) == (1, FeedbackTiming.AFTER)


async def test_tonight_is_still_before_the_night(session, priced) -> None:
    saved = await _give(session, priced, _today())

    assert saved.timing == FeedbackTiming.BEFORE


async def test_the_reason_is_optional(session, priced) -> None:
    saved = await _give(session, priced)

    assert (saved.reason_tags, saved.reason_text) == ([], None)


async def test_a_repeated_tag_is_kept_once(session, priced) -> None:
    saved = await _give(
        session,
        priced,
        reason_tags=[
            FeedbackReasonTag.OTHER,
            FeedbackReasonTag.VENUE_SOLD_OUT,
            FeedbackReasonTag.OTHER,
        ],
    )

    assert saved.reason_tags == [
        FeedbackReasonTag.OTHER,
        FeedbackReasonTag.VENUE_SOLD_OUT,
    ]


async def test_a_night_can_be_tagged_as_a_one_off(session, priced) -> None:
    saved = await _give(session, priced, reason_tags=[FeedbackReasonTag.ONE_OFF])

    assert saved.reason_tags == [FeedbackReasonTag.ONE_OFF]


async def test_who_gave_it_is_empty_when_not_given(session, priced) -> None:
    saved = await _give(session, priced)

    assert saved.user_id is None


async def test_who_gave_it_is_recorded(session, priced) -> None:
    user = await make_user(session)

    saved = await _give(session, priced, user_id=user.id)

    assert saved.user_id == user.id


# The verdict comes from the manager's rate


@pytest.mark.parametrize(
    ("rate", "verdict"),
    [
        pytest.param("200.01", FeedbackVerdict.TOO_LOW, id="higher: ours too low"),
        pytest.param("199.99", FeedbackVerdict.TOO_HIGH, id="lower: ours too high"),
        pytest.param("200.00", FeedbackVerdict.ABOUT_RIGHT, id="same: about right"),
        pytest.param("200", FeedbackVerdict.ABOUT_RIGHT, id="same, fewer digits"),
    ],
)
def test_the_verdict_compares_the_managers_rate_with_ours(rate, verdict) -> None:
    assert service.verdict_for(Decimal(rate), RECOMMENDED) == verdict


async def test_saved_feedback_carries_the_worked_out_verdict(session, priced) -> None:
    higher = await _give(session, priced, FUTURE, rate=Decimal("250.00"))
    lower = await _give(session, priced, PAST, rate=Decimal("150.00"))

    assert higher.verdict == FeedbackVerdict.TOO_LOW
    assert lower.verdict == FeedbackVerdict.TOO_HIGH


# The snapshot the manager saw


async def test_the_snapshot_the_manager_saw_is_recorded(session, priced) -> None:
    snapshot = await _snapshot(session, priced, FUTURE)

    saved = await _give(session, priced, FUTURE, snapshot_id=snapshot.id)

    assert saved.snapshot_id == snapshot.id


async def test_a_snapshot_for_another_night_is_rejected(session, priced) -> None:
    snapshot = await _snapshot(session, priced, FUTURE)

    with pytest.raises(InvalidRequestError):
        await _give(
            session, priced, FUTURE + timedelta(days=1), snapshot_id=snapshot.id
        )


async def test_an_unknown_snapshot_is_not_found(session, priced) -> None:
    with pytest.raises(NotFoundError):
        await _give(session, priced, snapshot_id=999_999)


async def test_another_hotels_snapshot_is_not_found(session, priced) -> None:
    other = await _another_hotel(session)
    theirs = await _snapshot(
        session,
        priced,
        FUTURE,
        hotel_id=other.hotel_id,
        room_type_id=other.room_type_id,
    )

    with pytest.raises(NotFoundError):
        await _give(session, priced, FUTURE, snapshot_id=theirs.id)


# The hotel and room type


async def test_an_unknown_hotel_is_not_found(session, priced) -> None:
    snapshot = await _snapshot(session, priced, FUTURE)

    with pytest.raises(NotFoundError):
        await service.add_feedback(
            session,
            999_999,
            room_type_id=priced.room_type_id,
            stay_date=FUTURE,
            rate=Decimal("210.00"),
            reason_tags=[],
            reason_text=None,
            snapshot_id=snapshot.id,
        )


async def test_another_hotels_room_type_is_not_found(session, priced) -> None:
    other = await _another_hotel(session)
    snapshot = await _snapshot(session, priced, FUTURE)

    with pytest.raises(NotFoundError):
        await _give(
            session,
            priced,
            room_type_id=other.room_type_id,
            snapshot_id=snapshot.id,
        )


# Changing it adds a version


async def test_changing_feedback_adds_a_version_and_keeps_the_first(
    session, priced
) -> None:
    first = await _give(session, priced, rate=Decimal("180.00"))
    second = await _give(session, priced, rate=Decimal("400.00"))

    assert (first.version, second.version) == (1, 2)
    assert first.id != second.id
    assert (first.rate, first.verdict) == (
        Decimal("180.00"),
        FeedbackVerdict.TOO_HIGH,
    )  # untouched
    current = await _listed(session, priced)
    assert [(f.version, f.verdict) for f in current] == [(2, FeedbackVerdict.TOO_LOW)]


async def test_history_returns_every_version_oldest_first_with_times(
    session, priced
) -> None:
    for rate in ("190.00", "210.00", "200.00"):
        await _give(session, priced, rate=Decimal(rate))

    history = await _listed(session, priced, include_history=True)

    assert [f.version for f in history] == [1, 2, 3]
    assert [f.verdict for f in history] == [
        FeedbackVerdict.TOO_HIGH,
        FeedbackVerdict.TOO_LOW,
        FeedbackVerdict.ABOUT_RIGHT,
    ]
    assert all(f.created_at for f in history)


async def test_each_night_and_room_type_has_its_own_versions(session, priced) -> None:
    second_room = RoomType(
        hotel_id=priced.hotel_id, name="Suite", room_count=2, base_rate=Decimal("300")
    )
    session.add(second_room)
    await session.flush()

    a = await _give(session, priced, FUTURE)
    b = await _give(session, priced, FUTURE + timedelta(days=1))
    c = await _give(session, priced, FUTURE, room_type_id=second_room.id)

    assert (a.version, b.version, c.version) == (1, 1, 1)


# Listing


async def _listed(session, priced, start=FUTURE, end=FUTURE, **kwargs):
    return await service.list_feedback(
        session, priced.hotel_id, start=start, end=end, **kwargs
    )


async def test_listing_covers_the_range_oldest_night_first(session, priced) -> None:
    await _give(session, priced, FUTURE + timedelta(days=2))
    await _give(session, priced, FUTURE)
    await _give(session, priced, FUTURE + timedelta(days=9))  # outside the range

    listed = await _listed(session, priced, FUTURE, FUTURE + timedelta(days=5))

    assert [f.stay_date for f in listed] == [FUTURE, FUTURE + timedelta(days=2)]


async def test_listing_includes_both_ends_of_the_range(session, priced) -> None:
    end = FUTURE + timedelta(days=3)
    await _give(session, priced, FUTURE)
    await _give(session, priced, end)

    listed = await _listed(session, priced, FUTURE, end)

    assert len(listed) == 2


async def test_listing_can_be_limited_to_a_room_type(session, priced) -> None:
    suite = RoomType(
        hotel_id=priced.hotel_id, name="Suite", room_count=2, base_rate=Decimal("300")
    )
    session.add(suite)
    await session.flush()
    await _give(session, priced)
    await _give(session, priced, room_type_id=suite.id)

    listed = await _listed(session, priced, room_type_id=suite.id)

    assert [f.room_type_id for f in listed] == [suite.id]


async def test_listing_leaves_out_other_hotels(session, priced) -> None:
    other = await _another_hotel(session)
    theirs = await _snapshot(
        session,
        priced,
        FUTURE,
        hotel_id=other.hotel_id,
        room_type_id=other.room_type_id,
    )
    await service.add_feedback(
        session,
        other.hotel_id,
        room_type_id=other.room_type_id,
        stay_date=FUTURE,
        rate=Decimal("210.00"),
        reason_tags=[],
        reason_text=None,
        snapshot_id=theirs.id,
    )

    assert await _listed(session, priced) == []


async def test_listing_rejects_a_bad_range(session, priced) -> None:
    with pytest.raises(InvalidRequestError):
        await _listed(session, priced, FUTURE, FUTURE - timedelta(days=1))
    with pytest.raises(InvalidRequestError):
        await _listed(session, priced, FUTURE, FUTURE + timedelta(days=366))


async def test_listing_an_unknown_hotel_is_not_found(session) -> None:
    with pytest.raises(NotFoundError):
        await service.list_feedback(session, 999_999, start=FUTURE, end=FUTURE)


# The database backs up the request checks


async def test_the_database_rejects_a_rate_of_zero(session, priced) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await _give(session, priced, rate=Decimal("0"))


# Routes


@pytest.fixture
async def member(session, priced, sign_in_as):
    """A signed-in user linked to the hotel the `priced` fixture made."""
    user = await make_user(session)
    await user_service.link_user_to_hotel(
        session, user_id=user.id, hotel_id=priced.hotel_id
    )
    sign_in_as(user)
    return user


@pytest.fixture
async def seen(session, priced):
    """The recommendation the manager saw for FUTURE: RECOMMENDED."""
    return await _snapshot(session, priced, FUTURE)


def _body(priced, snapshot_id, **overrides) -> dict:
    return {
        "room_type_id": priced.room_type_id,
        "stay_date": FUTURE.isoformat(),
        "rate": "210.00",
        "snapshot_id": snapshot_id,
    } | overrides


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"rate": None}, id="null rate"),
        pytest.param({"rate": 0}, id="rate of 0"),
        pytest.param({"rate": "0.00"}, id="rate of 0.00"),
        pytest.param({"rate": -5}, id="negative rate"),
        pytest.param({"rate": "abc"}, id="rate that isn't a number"),
        pytest.param({"snapshot_id": None}, id="null snapshot"),
        pytest.param({"verdict": "too_low"}, id="verdict is set by the server"),
        pytest.param({"reason_tags": ["astrology"]}, id="unknown tag"),
        pytest.param({"reason_text": ""}, id="empty reason text"),
        pytest.param({"stay_date": "tomorrow"}, id="bad date"),
        pytest.param({"colour": "red"}, id="unknown field"),
    ],
)
async def test_invalid_feedback_is_a_422(
    client, priced, member, seen, overrides
) -> None:
    response = await client.post(
        f"/hotels/{priced.hotel_id}/feedback",
        json=_body(priced, seen.id) | overrides,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["rate", "snapshot_id"])
async def test_a_missing_rate_or_snapshot_is_a_422(
    client, priced, member, seen, field
) -> None:
    body = _body(priced, seen.id)
    del body[field]

    response = await client.post(f"/hotels/{priced.hotel_id}/feedback", json=body)

    assert response.status_code == 422
    assert field in response.text


async def test_listing_without_a_range_is_a_422(client, priced, member) -> None:
    url = f"/hotels/{priced.hotel_id}/feedback"

    assert (await client.get(url)).status_code == 422
    assert (await client.get(f"{url}?start=2025-01-01")).status_code == 422


async def test_listing_with_a_bad_range_is_a_422(client, priced, member) -> None:
    url = f"/hotels/{priced.hotel_id}/feedback"

    reversed_ = await client.get(f"{url}?start=2025-02-01&end=2025-01-01")
    too_long = await client.get(f"{url}?start=2025-01-01&end=2026-12-31")

    assert (reversed_.status_code, too_long.status_code) == (422, 422)


async def test_feedback_can_be_added_changed_and_listed_over_http(
    client, priced, member, seen
) -> None:
    url = f"/hotels/{priced.hotel_id}/feedback"
    first = await client.post(
        url,
        json=_body(
            priced,
            seen.id,
            rate="180.00",
            reason_tags=["venue_sold_out", "other"],
            reason_text="Venue next door sold out",
        ),
    )
    second = await client.post(url, json=_body(priced, seen.id, rate="355.00"))
    window = f"?start={FUTURE}&end={FUTURE}"
    current = await client.get(url + window)
    history = await client.get(url + window + "&include_history=true")

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["reason_tags"] == ["venue_sold_out", "other"]
    assert first.json()["timing"] == "before"
    assert first.json()["verdict"] == "too_high"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert [f["version"] for f in current.json()] == [2]
    assert current.json()[0]["verdict"] == "too_low"
    assert current.json()[0]["rate"] == "355.00"
    assert current.json()[0]["snapshot_id"] == seen.id
    assert [f["version"] for f in history.json()] == [1, 2]
    assert history.json()[0]["created_at"] and history.json()[1]["created_at"]


async def test_who_gave_it_is_the_signed_in_user_over_http(
    client, priced, member, seen
) -> None:
    response = await client.post(
        f"/hotels/{priced.hotel_id}/feedback", json=_body(priced, seen.id)
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == member.id


async def test_a_users_other_hotel_is_a_404_over_http(
    client, session, priced, member, seen
) -> None:
    other = await _another_hotel(session)

    response = await client.post(
        f"/hotels/{other.hotel_id}/feedback", json=_body(other, seen.id)
    )

    assert response.status_code == 404


async def test_a_unknown_hotel_is_a_404_over_http(client, priced, member, seen) -> None:
    response = await client.post("/hotels/999999/feedback", json=_body(priced, seen.id))

    assert response.status_code == 404


# Helpers


class _Other:
    def __init__(self, hotel_id: int, room_type_id: int) -> None:
        self.hotel_id = hotel_id
        self.room_type_id = room_type_id


async def _another_hotel(session) -> _Other:
    city = City(
        name="Otherville",
        slug="otherville",
        timezone="Europe/Dublin",
        latitude=51.9,
        longitude=-8.5,
    )
    session.add(city)
    await session.flush()
    hotel = Hotel(name="The Other", city_id=city.id, total_rooms=5)
    session.add(hotel)
    await session.flush()
    room = RoomType(
        hotel_id=hotel.id, name="Standard", room_count=5, base_rate=Decimal("90")
    )
    session.add(room)
    await session.flush()
    return _Other(hotel.id, room.id)
