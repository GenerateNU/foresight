"""Shared fixtures: a rolled-back Postgres session, mock hotel data, ML splits."""

from collections.abc import AsyncIterator

import pandas as pd
import pytest
from generate_mock_data import write_csv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from foresight.config import settings


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session whose transaction is always rolled back; skips with no Postgres."""
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
        yield session
    await trans.rollback()
    await conn.close()
    await engine.dispose()


# Known only after the night, so never used to predict price.
POST_STAY_COLUMNS = ["rooms_sold", "occupancy", "room_revenue"]
TEST_FRAC = 0.2


@pytest.fixture(scope="session")
def df():
    """Mock nightly data, freshly generated to data/, sorted by stay_date."""
    df = pd.read_csv(write_csv(), parse_dates=["stay_date"])
    return df.sort_values("stay_date", kind="stable").reset_index(drop=True)


@pytest.fixture(scope="session")
def price_split(df):
    """x_train, x_test, y_train, y_test for predicting rate.

    The test set is the most recent TEST_FRAC of nights.
    """
    x = df.drop(columns=["rate", "stay_date", *POST_STAY_COLUMNS])
    x = pd.get_dummies(x, columns=["room_type", "condition"], dtype=float)
    y = df["rate"]

    cut = int(len(df) * (1 - TEST_FRAC))
    return x.iloc[:cut], x.iloc[cut:], y.iloc[:cut], y.iloc[cut:]


# SARIMAX inputs besides past prices; same for every room type on a night.
TS_EXOG_COLUMNS = [
    "is_weekend",
    "temp_max_c",
    "precip_mm",
    "expected_attendance",
    "competitor_rate",
    "competitors_sold_out",
    "flight_count",
    "avg_fare_eur",
]


@pytest.fixture(scope="session")
def ts_split(df):
    """x_train, x_test, y_train, y_test for forecasting the nightly mean rate.

    One row per night at daily frequency; the test set is the most recent
    TEST_FRAC of nights.
    """
    # SARIMAX needs one row per day, so average the room types for each night.
    daily = df.groupby("stay_date")[["rate", *TS_EXOG_COLUMNS]].mean().asfreq("D")
    x, y = daily[TS_EXOG_COLUMNS], daily["rate"]

    cut = int(len(daily) * (1 - TEST_FRAC))
    return x.iloc[:cut], x.iloc[cut:], y.iloc[:cut], y.iloc[cut:]
