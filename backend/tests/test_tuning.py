"""Daily tune-up: a correction on top of the active model (decision 0051).

`TunedEBMModel` is tested on synthetic data; the service tests train a real
model against the database (the `session` fixture rolls back), then tune it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from foresight.database.enums import FeedbackTiming, FeedbackVerdict
from foresight.repository import feedback as feedback_repo
from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.services.domain import pricing_model as training
from foresight.services.domain import tuning
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.ebm import EBMModel, TunedEBMModel

# The model on its own


def _data(n: int, seed: int) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    x = pd.DataFrame({"day_of_week": rng.integers(0, 7, n), "temp": rng.random(n) * 20})
    return x, pd.Series(150 + 10 * x["day_of_week"] + rng.normal(0, 2, n))


@pytest.fixture(scope="module")
def base() -> EBMModel:
    x, y = _data(300, seed=0)
    return EBMModel(interactions=0).fit(x, y)


def test_the_correction_moves_predictions_toward_the_new_rates(base) -> None:
    x, _ = _data(20, seed=1)
    tuned = TunedEBMModel(base).fit(x, base.predict(x) + 30)

    moved = tuned.predict(x) - base.predict(x)

    assert np.allclose(moved, tuned.correction(x))
    assert moved.mean() > 20


def test_the_explanation_still_adds_up_to_the_prediction(base) -> None:
    x, _ = _data(20, seed=1)
    tuned = TunedEBMModel(base).fit(x, base.predict(x) + 30)

    total = tuned.intercept + tuned.explain(x).sum(axis=1).to_numpy()

    assert np.allclose(total, tuned.predict(x))
    assert list(tuned.explain(x).columns) == list(base.explain(x).columns)


def test_tuning_a_tuned_model_starts_again_from_its_base(base) -> None:
    x, _ = _data(20, seed=1)
    first = TunedEBMModel(base).fit(x, base.predict(x) + 30)
    second = TunedEBMModel(first).fit(x, base.predict(x) + 30)

    assert second.base is base
    # Rebuilt, not stacked: +30 again, not +60.
    assert abs((second.predict(x) - base.predict(x)).mean() - 30) < 10


def test_the_interval_is_the_bases(base) -> None:
    x, _ = _data(20, seed=1)
    tuned = TunedEBMModel(base).fit(x, base.predict(x) + 30)

    assert tuned.interval_margin(0.2) == base.interval_margin(0.2)


def test_a_tuned_model_loads_where_an_ebm_model_is_expected(base) -> None:
    x, _ = _data(20, seed=1)
    tuned = TunedEBMModel(base).fit(x, base.predict(x) + 30)

    loaded = EBMModel.from_bytes(tuned.to_bytes())

    assert isinstance(loaded, TunedEBMModel)
    assert np.allclose(loaded.predict(x), tuned.predict(x))


# The service


def _local_today() -> date:
    return datetime.now(ZoneInfo("Europe/Dublin")).date()


async def _trained(session, priced):
    """140 past nights at a flat 100, and a real model trained and active."""
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
    hotel = await hotel_repo.get_hotel(session, priced.hotel_id)
    result = await training.train(
        session,
        hotel,
        description=None,
        start=None,
        end=None,
        activate=True,
        params={"interactions": 0},
    )
    return hotel, result.model


async def _price(session, priced, nights: int, rate: str = "130.00"):
    """The manager prices `nights` future nights at `rate`."""
    for i in range(nights):
        await feedback_repo.create_feedback(
            session,
            hotel_id=priced.hotel_id,
            room_type_id=priced.room_type_id,
            stay_date=_local_today() + timedelta(days=10 + i),
            snapshot_id=None,
            user_id=None,
            verdict=FeedbackVerdict.TOO_LOW,
            rate=Decimal(rate),
            reason_tags=[],
            reason_text=None,
            timing=FeedbackTiming.BEFORE,
        )


async def test_a_tune_up_saves_and_serves_a_corrected_version(session, priced) -> None:
    hotel, trained = await _trained(session, priced)
    await _price(session, priced, tuning.MIN_TUNE_NIGHTS)

    result = await tuning.tune(session, hotel, activate=True)

    assert result.skipped is None
    assert result.activated and result.model.is_active
    assert result.model.algorithm == "ebm-tuned"
    assert result.model.metrics["base_model_id"] == trained.id
    assert result.model.metrics["tune_nights"] == tuning.MIN_TUNE_NIGHTS
    assert result.model.metrics["mean_correction"] > 10  # base says ~100, manager 130


async def test_too_few_manager_rates_skips_the_tune_up(session, priced) -> None:
    hotel, trained = await _trained(session, priced)
    await _price(session, priced, tuning.MIN_TUNE_NIGHTS - 1)

    result = await tuning.tune(session, hotel, activate=True)

    assert result.model is None
    assert result.skipped
    active = await model_repo.get_active_pricing_model(session, hotel.id)
    assert active.id == trained.id


async def test_a_second_tune_up_starts_from_the_same_base(session, priced) -> None:
    hotel, trained = await _trained(session, priced)
    await _price(session, priced, tuning.MIN_TUNE_NIGHTS)

    first = await tuning.tune(session, hotel, activate=True)
    second = await tuning.tune(session, hotel, activate=True)

    assert second.model.metrics["base_model_id"] == trained.id
    assert second.model.metrics["base_version"] == trained.version
    assert first.model.id != second.model.id


async def test_a_hotel_without_an_active_model_cant_be_tuned(session, priced) -> None:
    model = await model_repo.get_pricing_model(session, priced.model_id)
    model.is_active = False
    await session.flush()

    with pytest.raises(InvalidRequestError):
        await tuning.check_tunable(session, priced.hotel_id)
