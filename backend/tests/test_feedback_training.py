"""Training uses the manager's feedback from after the night (decision 0041).

`apply_feedback` is tested on its own; the direction test fits a real model;
the last tests run `train` against the real database (the `session` fixture
rolls back) and check which feedback each model version records.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from foresight.database.enums import FeedbackTiming, FeedbackVerdict
from foresight.database.models import PricingModelFeedback
from foresight.repository import feedback as feedback_repo
from foresight.repository import hotel as hotel_repo
from foresight.services.domain import pricing_model as training
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.feedback import DEFAULT, FeedbackSettings, apply_feedback

V = FeedbackVerdict
DAY = date(2025, 3, 1)


def _nights(n: int = 4, rate: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stay_date": [DAY + timedelta(days=i) for i in range(n)],
            "room_type": "Standard",
            "rate": rate,
        }
    )


def _feedback(*rows: tuple[int, FeedbackVerdict, float | None]) -> pd.DataFrame:
    """(night index, verdict, manager's rate) -> the frame `apply_feedback` takes."""
    return pd.DataFrame(
        {
            "id": [100 + i for i, _, _ in rows],
            "stay_date": [DAY + timedelta(days=i) for i, _, _ in rows],
            "room_type": "Standard",
            "verdict": [v for _, v, _ in rows],
            "rate": [np.nan if r is None else r for _, _, r in rows],
        }
    )


def _apply(feedback, nights=None, weights=None, settings=DEFAULT):
    nights = _nights() if nights is None else nights
    weights = np.full(len(nights), 0.8) if weights is None else weights
    return apply_feedback(nights, feedback, nights["rate"], weights, settings)


# Which feedback changes what, with and without a rate


def test_a_night_with_no_feedback_trains_as_recorded() -> None:
    effect = _apply(_feedback((1, V.TOO_LOW, 120.0)))

    assert effect.rate.iloc[[0, 2, 3]].tolist() == [100.0] * 3
    assert effect.weights[[0, 2, 3]].tolist() == [0.8] * 3


def test_no_feedback_at_all_changes_nothing() -> None:
    effect = _apply(_feedback())

    assert effect.rate.tolist() == [100.0] * 4
    assert effect.weights.tolist() == [0.8] * 4
    assert effect.used.empty


def test_too_low_with_a_rate_replaces_the_rate() -> None:
    effect = _apply(_feedback((1, V.TOO_LOW, 125.0)))

    assert effect.rate.iloc[1] == 125.0
    assert effect.weights[1] == DEFAULT.replaced  # flat, not the vacancy weight
    [row] = effect.used.to_dict("records")
    assert (row["feedback_id"], row["rate_replaced"]) == (101, True)
    assert row["training_rate"] == 125.0


def test_too_high_with_a_rate_replaces_the_rate() -> None:
    effect = _apply(_feedback((2, V.TOO_HIGH, 85.0)))

    assert effect.rate.iloc[2] == 85.0


@pytest.mark.parametrize("verdict", [V.TOO_HIGH, V.TOO_LOW])
def test_a_verdict_without_a_rate_only_lowers_the_nights_weight(verdict) -> None:
    effect = _apply(_feedback((1, verdict, None)))

    assert effect.rate.iloc[1] == 100.0  # the rate stands
    assert effect.weights[1] == pytest.approx(0.8 * DEFAULT.wrong_no_rate)
    [row] = effect.used.to_dict("records")
    assert row["rate_replaced"] is False


def test_about_right_raises_the_nights_weight_and_keeps_its_rate() -> None:
    effect = _apply(_feedback((1, V.ABOUT_RIGHT, None)))

    assert effect.rate.iloc[1] == 100.0
    assert effect.weights[1] == pytest.approx(0.8 * DEFAULT.about_right)


def test_about_right_ignores_a_rate_the_manager_also_gave() -> None:
    effect = _apply(_feedback((1, V.ABOUT_RIGHT, 140.0)))

    assert effect.rate.iloc[1] == 100.0


@pytest.mark.parametrize(("verdict", "rate"), [(V.TOO_LOW, 80.0), (V.TOO_HIGH, 120.0)])
def test_a_rate_that_contradicts_the_verdict_is_not_used(verdict, rate) -> None:
    effect = _apply(_feedback((1, verdict, rate)))

    assert effect.rate.iloc[1] == 100.0
    assert effect.weights[1] == pytest.approx(0.8 * DEFAULT.wrong_no_rate)


def test_feedback_for_a_night_not_trained_on_is_ignored() -> None:
    effect = _apply(_feedback((50, V.TOO_LOW, 120.0)))

    assert effect.used.empty
    assert effect.rate.tolist() == [100.0] * 4


def test_two_pieces_of_feedback_for_one_night_are_refused() -> None:
    with pytest.raises(ValueError, match="at most one"):
        _apply(_feedback((1, V.TOO_LOW, 120.0), (1, V.TOO_HIGH, 90.0)))


# A few pieces can't swing the model


@pytest.mark.parametrize(("manager", "expected"), [(1000.0, 130.0), (1.0, 70.0)])
def test_an_outlandish_rate_is_held_within_the_cap(manager, expected) -> None:
    verdict = V.TOO_LOW if manager > 100 else V.TOO_HIGH

    effect = _apply(_feedback((1, verdict, manager)))

    assert effect.rate.iloc[1] == pytest.approx(expected)
    assert effect.used["training_rate"].iloc[0] == pytest.approx(expected)


def test_the_cap_can_be_set() -> None:
    effect = _apply(
        _feedback((1, V.TOO_LOW, 1000.0)),
        settings=FeedbackSettings(max_rate_change=0.1),
    )

    assert effect.rate.iloc[1] == pytest.approx(110.0)


def test_feedback_never_makes_a_weight_zero_or_huge() -> None:
    weights = np.full(4, 0.05)  # the floor
    effect = _apply(
        _feedback((0, V.TOO_HIGH, None), (1, V.ABOUT_RIGHT, None)), weights=weights
    )

    assert (effect.weights > 0).all()
    assert effect.weights.max() <= weights.max() * DEFAULT.about_right


# Nights with feedback move the way the manager said


def _fit_predict(fb: pd.DataFrame) -> np.ndarray:
    """Train on a flat 100 rate with and without feedback; predict a Fri and a Mon."""
    days = pd.date_range("2024-01-01", periods=300)
    nights = pd.DataFrame(
        {"stay_date": [d.date() for d in days], "room_type": "Standard", "rate": 100.0}
    )
    x = pd.DataFrame(
        {
            "room_type": pd.Categorical(nights["room_type"]),
            "day_of_week": days.dayofweek.to_numpy(),
            "month": days.month.to_numpy(),
        }
    )
    weights = np.full(len(nights), 0.8)
    effect = apply_feedback(nights, fb, nights["rate"], weights)
    model = EBMModel(interactions=0).fit(x, effect.rate, sample_weight=effect.weights)
    probe = x.iloc[[days.get_loc(pd.Timestamp("2024-02-02")), 0]]  # a Friday, a Monday
    assert probe["day_of_week"].tolist() == [4, 0]
    return model.predict(probe)


def test_nights_with_feedback_move_toward_the_managers_rate() -> None:
    days = pd.date_range("2024-01-01", periods=300)
    fridays = [d.date() for d in days if d.dayofweek == 4][:30]
    mondays = [d.date() for d in days if d.dayofweek == 0][:30]
    rows = [(d, V.TOO_LOW, 125.0) for d in fridays] + [
        (d, V.TOO_HIGH, 80.0) for d in mondays
    ]
    fb = pd.DataFrame(
        {
            "id": range(len(rows)),
            "stay_date": [d for d, _, _ in rows],
            "room_type": "Standard",
            "verdict": [v for _, v, _ in rows],
            "rate": [r for _, _, r in rows],
        }
    )

    without = _fit_predict(fb.iloc[:0])
    with_feedback = _fit_predict(fb)

    assert with_feedback[0] > without[0] + 5  # the Friday moved up
    assert with_feedback[1] < without[1] - 5  # the Monday moved down


# Training: which feedback a model version used


def _local_today() -> date:
    return datetime.now(ZoneInfo("Europe/Dublin")).date()


async def _trained_hotel(session, priced) -> list[date]:
    """140 past nights of a flat 100 rate; returns the nights, oldest first."""
    nights = [_local_today() - timedelta(days=200 - i) for i in range(140)]
    await hotel_repo.upsert_daily_performance(
        session,
        [
            {
                "room_type_id": priced.room_type_id,
                "stay_date": night,
                "rate": Decimal("100.00"),
                "rooms_available": 10,
                "rooms_sold": 8,
                "room_revenue": Decimal("800.00"),
            }
            for night in nights
        ],
    )
    return nights


async def _say(session, priced, night, verdict, rate, timing):
    return await feedback_repo.create_feedback(
        session,
        hotel_id=priced.hotel_id,
        room_type_id=priced.room_type_id,
        stay_date=night,
        snapshot_id=None,
        user_id=None,
        verdict=verdict,
        rate=None if rate is None else Decimal(str(rate)),
        reason_tags=[],
        reason_text=None,
        timing=timing,
    )


async def _train(session, priced):
    hotel = await hotel_repo.get_hotel(session, priced.hotel_id)
    return await training.train(
        session,
        hotel,
        description=None,
        start=None,
        end=None,
        activate=False,
        params={"interactions": 0},
    )


async def _links(session, model_id) -> dict[int, PricingModelFeedback]:
    from sqlalchemy import select

    rows = await session.scalars(
        select(PricingModelFeedback).where(
            PricingModelFeedback.pricing_model_id == model_id
        )
    )
    return {link.feedback_id: link for link in rows}


async def test_training_with_no_feedback_records_none(session, priced) -> None:
    await _trained_hotel(session, priced)

    result = await _train(session, priced)

    assert result.feedback_used == 0
    assert await _links(session, result.model.id) == {}
    assert result.model.metrics["feedback_nights"] == 0


async def test_a_model_records_the_feedback_it_used(session, priced) -> None:
    nights = await _trained_hotel(session, priced)
    with_rate = await _say(
        session, priced, nights[10], V.TOO_LOW, 120, FeedbackTiming.AFTER
    )
    no_rate = await _say(
        session, priced, nights[20], V.TOO_HIGH, None, FeedbackTiming.AFTER
    )
    right = await _say(
        session, priced, nights[30], V.ABOUT_RIGHT, None, FeedbackTiming.AFTER
    )

    result = await _train(session, priced)

    links = await _links(session, result.model.id)
    assert set(links) == {with_rate.id, no_rate.id, right.id}
    assert (links[with_rate.id].rate_replaced, links[with_rate.id].training_rate) == (
        True,
        Decimal("120.00"),
    )
    assert links[no_rate.id].rate_replaced is False
    assert links[no_rate.id].weight_factor == Decimal("0.500")
    assert links[right.id].weight_factor == Decimal("2.000")
    assert result.feedback_used == 3
    assert result.model.metrics["feedback_nights"] == 3
    assert result.model.metrics["feedback_rates_replaced"] == 1


async def test_feedback_from_before_the_night_is_not_used(session, priced) -> None:
    nights = await _trained_hotel(session, priced)
    await _say(session, priced, nights[10], V.TOO_LOW, 120, FeedbackTiming.BEFORE)

    result = await _train(session, priced)

    assert result.feedback_used == 0
    assert await _links(session, result.model.id) == {}


async def test_the_latest_version_is_the_one_used(session, priced) -> None:
    nights = await _trained_hotel(session, priced)
    await _say(session, priced, nights[10], V.TOO_HIGH, 90, FeedbackTiming.AFTER)
    latest = await _say(
        session, priced, nights[10], V.TOO_LOW, 115, FeedbackTiming.AFTER
    )

    result = await _train(session, priced)

    links = await _links(session, result.model.id)
    assert set(links) == {latest.id}
    assert links[latest.id].training_rate == Decimal("115.00")


async def test_a_before_version_that_is_the_latest_hides_an_earlier_after_one(
    session, priced
) -> None:
    nights = await _trained_hotel(session, priced)
    await _say(session, priced, nights[10], V.TOO_LOW, 120, FeedbackTiming.AFTER)
    await _say(session, priced, nights[10], V.TOO_HIGH, 90, FeedbackTiming.BEFORE)

    result = await _train(session, priced)

    assert result.feedback_used == 0  # the latest counts, and it isn't usable


async def test_a_before_version_replaced_by_an_after_one_is_used(
    session, priced
) -> None:
    nights = await _trained_hotel(session, priced)
    await _say(session, priced, nights[10], V.TOO_HIGH, 90, FeedbackTiming.BEFORE)
    after = await _say(
        session, priced, nights[10], V.TOO_LOW, 115, FeedbackTiming.AFTER
    )

    result = await _train(session, priced)

    assert set(await _links(session, result.model.id)) == {after.id}


async def test_each_model_version_keeps_its_own_record(session, priced) -> None:
    nights = await _trained_hotel(session, priced)
    first = await _train(session, priced)
    said = await _say(
        session, priced, nights[10], V.ABOUT_RIGHT, None, FeedbackTiming.AFTER
    )

    second = await _train(session, priced)

    assert await _links(session, first.model.id) == {}
    assert set(await _links(session, second.model.id)) == {said.id}
