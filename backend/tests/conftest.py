"""Shared fixtures: a rolled-back Postgres session and mock hotel data."""

from collections.abc import AsyncIterator

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from foresight.config import settings
from tests.fixtures.mock_hotel_data import write_csv


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
