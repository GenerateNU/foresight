"""Recommendations are stored as snapshots and reused while their inputs hold.

Runs against the real database (the `session` fixture rolls back). The model is
replaced by a stand-in that prices a night at 200 plus its max temperature and
counts how often it runs, so a test can tell a reused snapshot from a new one.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from foresight.database.models import PricingModel
from foresight.repository import pricing_model as model_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain import recommendation as service


class FakeModel:
    """Rate = 200, ±20; counts its runs."""

    alpha = 0.2
    intercept = 180.0
    runs = 0

    def _rates(self, x: pd.DataFrame) -> np.ndarray:
        return np.full(len(x), 200.0)

    def predict_interval(self, x):
        FakeModel.runs += 1
        pred = self._rates(x)
        return pred, pred - 20, pred + 20

    def predict_uncertainty(self, x):
        return np.full(len(x), 5.0)

    def explain(self, x):
        return pd.DataFrame({"day_of_week": self._rates(x) - 180.0}, index=x.index)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    FakeModel.runs = 0
    monkeypatch.setattr(service.EBMModel, "from_bytes", lambda _: FakeModel())


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Dublin")).date()  # the test city's zone


async def _recommend(session, priced, start: date, end: date | None = None):
    return await service.get_recommendations(
        session, priced.hotel_id, start=start, end=end or start
    )


async def _stored(session, priced, night: date):
    """The night's latest snapshot, or None."""
    found = await snapshot_repo.latest_snapshots(
        session, priced.room_type_id, start=night, end=night
    )
    return found.get(night)


async def test_a_range_saves_one_snapshot_per_night(session, priced):
    today = _today()

    recs = await _recommend(session, priced, today, today + timedelta(days=2))

    assert [r.stay_date for r in recs] == [today + timedelta(days=i) for i in range(3)]
    assert all(r.snapshot_id is not None for r in recs)
    assert len({r.snapshot_id for r in recs}) == 3
    assert FakeModel.runs == 1  # one batch for the whole range


async def test_unchanged_inputs_reuse_the_snapshot_without_running_the_model(
    session, priced
):
    today = _today()
    first = await _recommend(session, priced, today, today + timedelta(days=2))

    again = await _recommend(session, priced, today, today + timedelta(days=2))

    assert [r.snapshot_id for r in again] == [r.snapshot_id for r in first]
    assert FakeModel.runs == 1  # the second request never ran the model


async def test_a_newly_active_model_prices_every_night_again(session, priced):
    today = _today()
    first = await _recommend(session, priced, today, today + timedelta(days=2))
    newer = PricingModel(
        hotel_id=priced.hotel_id,
        version=2,
        algorithm="ebm",
        artifact=b"not a real model",
        features=[],
        metrics={},
        lib_versions={},
        data_start=date(2025, 1, 1),
        data_end=date(2025, 12, 31),
    )
    session.add(newer)
    await session.flush()
    await model_repo.activate_pricing_model(session, newer.id)

    again = await _recommend(session, priced, today, today + timedelta(days=2))

    assert all(
        a.snapshot_id != f.snapshot_id for a, f in zip(again, first, strict=True)
    )
    assert {r.model_id for r in again} == {newer.id}
    assert FakeModel.runs == 2


@pytest.mark.parametrize(
    ("model_id", "change", "same"),
    [
        (1, {}, True),
        (2, {}, False),  # a newly activated model
        (1, {"features": {"month": 12}}, False),
    ],
)
def test_the_fingerprint_covers_the_model_and_every_input(model_id, change, same):
    inputs = {"features": {"month": 11}}

    before = service._fingerprint(1, inputs)
    after = service._fingerprint(model_id, {**inputs, **change})

    assert (before == after) is same


async def test_a_future_night_with_no_snapshot_gets_one(session, priced):
    night = _today() + timedelta(days=5)

    [rec] = await _recommend(session, priced, night)

    stored = await _stored(session, priced, night)
    assert stored is not None
    assert (rec.snapshot_id, rec.recommended_rate) == (stored.id, Decimal("200.00"))


async def test_a_past_night_with_no_snapshot_is_priced_but_not_saved(session, priced):
    night = date(2000, 1, 1)

    [rec] = await _recommend(session, priced, night)

    assert rec.recommended_rate == Decimal("200.00")
    assert rec.snapshot_id is None
    assert await _stored(session, priced, night) is None


async def test_a_past_nights_snapshot_is_returned_as_it_was(session, priced):
    night = date(2000, 1, 1)
    saved = await snapshot_repo.create_recommendation_snapshot(
        session,
        hotel_id=priced.hotel_id,
        room_type_id=priced.room_type_id,
        stay_date=night,
        model_id=priced.model_id,
        model_version="ebm-v1",
        rate=Decimal("250.00"),
        interval_low=Decimal("230.00"),
        interval_high=Decimal("270.00"),
        interval_level=0.8,
        uncertainty=Decimal("5.00"),
        factors={"summary": "then", "baseline": "180.00", "factors": []},
        inputs={},
        inputs_hash="",  # its inputs differ from today's
    )

    [rec] = await _recommend(session, priced, night)

    assert (rec.snapshot_id, rec.recommended_rate) == (saved.id, Decimal("250.00"))
    assert FakeModel.runs == 0
