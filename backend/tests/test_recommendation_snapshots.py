"""Recommendation snapshots: saving, skipping unchanged rates, reading back."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain import recommendation as service
from foresight.services.domain.recommendation import (
    ConfidenceInterval,
    Explanation,
    Recommendation,
)
from foresight.services.errors import NotFoundError


def _robot(priced, rates: dict[date, str] | None = None, default: str = "200.00"):
    """A stand-in for `get_recommendation`: returns `rates[night]` (or the
    default) for any night, with a range of ±20 around it."""

    async def fake(session, hotel_id, stay_date, *, room_type_id=None):
        rate = Decimal((rates or {}).get(stay_date, default))
        return Recommendation(
            hotel_id=priced.hotel_id,
            stay_date=stay_date,
            room_type="Standard",
            room_type_id=priced.room_type_id,
            recommended_rate=rate,
            currency="EUR",
            explanation=Explanation("test", Decimal("180.00"), []),
            confidence_interval=ConfidenceInterval(rate - 20, rate + 20, 0.8),
            uncertainty=Decimal("5.00"),
            model_id=priced.model_id,
            model_version="ebm-v1",
            is_placeholder=False,
        )

    return fake


async def test_a_range_saves_one_snapshot_per_night(session, priced, monkeypatch):
    # ARRANGE: swap in the fake robot
    monkeypatch.setattr(service, "get_recommendation", _robot(priced))

    # ACT: refresh 3 nights
    saved = await service.snapshot_recommendations(session, priced.hotel_id, days=3)

    # ASSERT: 3 snapshots, one per night, starting today
    assert len(saved) == 3
    assert [s.stay_date for s in saved] == [
        saved[0].stay_date + timedelta(days=i) for i in range(3)
    ]


async def test_rerunning_with_the_same_answers_saves_nothing(
    session, priced, monkeypatch
):
    # ARRANGE: a first refresh saves 3 nights
    monkeypatch.setattr(service, "get_recommendation", _robot(priced))
    await service.snapshot_recommendations(session, priced.hotel_id, days=3)

    # ACT: refresh again with the same answers
    saved = await service.snapshot_recommendations(session, priced.hotel_id, days=3)

    # ASSERT: nothing changed, so nothing saved
    assert saved == []


async def test_only_the_night_whose_rate_changed_is_saved(session, priced, monkeypatch):
    # ARRANGE: a first refresh, then the robot changes its mind about tomorrow
    monkeypatch.setattr(service, "get_recommendation", _robot(priced))
    first = await service.snapshot_recommendations(session, priced.hotel_id, days=3)
    tomorrow = first[1].stay_date
    monkeypatch.setattr(
        service, "get_recommendation", _robot(priced, {tomorrow: "230.00"})
    )

    # ACT
    saved = await service.snapshot_recommendations(session, priced.hotel_id, days=3)

    # ASSERT: only tomorrow, at its new rate
    assert [(s.stay_date, s.rate) for s in saved] == [(tomorrow, Decimal("230.00"))]


_LATEST = {
    "rate": Decimal("200.00"),
    "model_id": 1,
    "interval_low": Decimal("180.00"),
    "interval_high": Decimal("220.00"),
    "uncertainty": Decimal("5.00"),
}


@pytest.mark.parametrize(
    ("change", "changed"),
    [
        ({}, False),
        ({"uncertainty": Decimal("9.00")}, False),  # not part of "unchanged"
        ({"rate": Decimal("210.00")}, True),
        ({"model_id": 2}, True),
        ({"interval_low": Decimal("170.00")}, True),
        ({"interval_high": Decimal("230.00")}, True),
    ],
)
async def test_unchanged_means_same_model_rate_and_range(change, changed):
    # ARRANGE: the robot says 200 (180–220) with model 1; the latest
    # snapshot is the same except for `change`
    ids = SimpleNamespace(hotel_id=1, room_type_id=1, model_id=1)
    rec = await _robot(ids)(None, 1, date(2026, 11, 1))
    latest = SimpleNamespace(**{**_LATEST, **change})

    # ACT + ASSERT
    assert service._changed(latest, rec) is changed


async def test_a_future_night_with_no_snapshot_gets_one(session, priced, monkeypatch):
    # ARRANGE: no snapshots yet
    monkeypatch.setattr(service, "get_recommendation", _robot(priced))
    night = date.today() + timedelta(days=5)

    # ACT
    latest, previous = await service.get_snapshot(session, priced.hotel_id, night)

    # ASSERT: one was created now, with nothing before it
    assert (latest.stay_date, latest.rate) == (night, Decimal("200.00"))
    assert previous is None


async def test_a_night_returns_its_latest_and_previous_snapshot(
    session, priced, monkeypatch
):
    # ARRANGE: tonight saved at 200, then again at 230
    monkeypatch.setattr(service, "get_recommendation", _robot(priced))
    first = await service.snapshot_recommendations(session, priced.hotel_id, days=1)
    night = first[0].stay_date
    monkeypatch.setattr(
        service, "get_recommendation", _robot(priced, {night: "230.00"})
    )
    await service.snapshot_recommendations(session, priced.hotel_id, days=1)

    # ACT
    latest, previous = await service.get_snapshot(session, priced.hotel_id, night)

    # ASSERT: newest first (same transaction, so the id breaks the tie)
    assert (latest.rate, previous.rate) == (Decimal("230.00"), Decimal("200.00"))


async def test_a_past_night_with_no_snapshot_is_not_found(session, priced, monkeypatch):
    monkeypatch.setattr(service, "get_recommendation", _robot(priced))

    with pytest.raises(NotFoundError):
        await service.get_snapshot(session, priced.hotel_id, date(2000, 1, 1))


async def test_a_past_nights_snapshot_is_returned_as_it_was(
    session, priced, monkeypatch
):
    # ARRANGE: a past night saved at 200, and a robot that would now say 230
    night = date(2000, 1, 1)
    await snapshot_repo.create_recommendation_snapshot(
        session,
        hotel_id=priced.hotel_id,
        room_type_id=priced.room_type_id,
        stay_date=night,
        model_id=priced.model_id,
        model_version="ebm-v1",
        rate=Decimal("200.00"),
        interval_low=Decimal("180.00"),
        interval_high=Decimal("220.00"),
        uncertainty=Decimal("5.00"),
        factors={},
    )
    monkeypatch.setattr(service, "get_recommendation", _robot(priced, default="230.00"))

    # ACT
    latest, previous = await service.get_snapshot(session, priced.hotel_id, night)

    # ASSERT: untouched, still 200
    assert latest.rate == Decimal("200.00")
    assert previous is None
