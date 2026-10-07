"""Prices upcoming nights using real events from the events table.

Run from backend/ after ingesting events:
    uv run python scripts/forecast_events.py --city Dublin --days 21
    uv run python scripts/forecast_events.py --city Dublin \\
        --lat 53.3498 --lon -6.2603 --radius-km 5 --room-type deluxe

The model is trained on mock history, and only expected_attendance is real.
Weather, competitor and flight features are mock placeholders until those
sources are ingested, simulated so competitors and flights respond to the real
events as they would in the mock world. "no events" reruns the same simulation
with zero attendance, so the effect column is the events' price impact alone.
"""

import argparse
import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd
from compare_models import POST_STAY_COLUMNS, load_data
from generate_mock_data import ROOM_TYPES, generate

from foresight.database.session import async_session_factory, engine
from foresight.ingest.normalize import EventStatus
from foresight.services.features.events import (
    FEATURE,
    load_events,
    nightly_attendance,
)
from foresight.services.ml.regression import GBMModel


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", required=True, help="market, as ingested")
    parser.add_argument("--days", type=int, default=14, help="nights to price")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--lat", type=float, help="hotel latitude")
    parser.add_argument("--lon", type=float, help="hotel longitude")
    parser.add_argument("--radius-km", type=float, help="drop events farther away")
    parser.add_argument("--room-type", choices=list(ROOM_TYPES), default="standard")
    return parser


async def _events(args, start: date, end: date):
    # DEBUG=true turns on SQL echo, which would bury the table.
    engine.echo = False
    try:
        async with async_session_factory() as session:
            return await load_events(session, args.city, start, end)
    finally:
        await engine.dispose()


def _nights(args, attendance: np.ndarray) -> pd.DataFrame:
    """Placeholder nights for one room type, driven by `attendance`."""
    frame = generate(
        start=args.start.isoformat(), days=args.days, expected_attendance=attendance
    )
    return frame[frame["room_type"] == args.room_type].reset_index(drop=True)


def _features(frame: pd.DataFrame, columns: pd.Index) -> pd.DataFrame:
    """Same columns, dummies and order the model was trained on."""
    x = frame.drop(columns=["rate", "stay_date", *POST_STAY_COLUMNS])
    x = pd.get_dummies(x, columns=["room_type", "condition"], dtype=float)
    return x.reindex(columns=columns, fill_value=0.0)


def _biggest(events, night: date) -> str:
    on = [
        e
        for e in events
        if e.start_local_date <= night <= e.end_local_date
        and e.expected_attendance
        and e.status not in {EventStatus.DELETED, EventStatus.CANCELLED}
    ]
    return max(on, key=lambda e: e.expected_attendance).title[:40] if on else ""


def main() -> None:
    args = _parser().parse_args()
    start = args.start
    end = start + timedelta(days=args.days - 1)

    events = asyncio.run(_events(args, start, end))
    attendance = nightly_attendance(
        events,
        start,
        end,
        latitude=args.lat,
        longitude=args.lon,
        radius_km=args.radius_km,
    )

    x_train, y_train = load_data()
    model = GBMModel(seed=9).fit(x_train, y_train)

    with_events = _nights(args, attendance.to_numpy())
    without = _nights(args, np.zeros(args.days))

    rate, lo, hi = model.predict_interval(_features(with_events, x_train.columns))
    baseline = model.predict(_features(without, x_train.columns))

    print(
        f"{args.city} | {args.room_type} | {start} to {end} | "
        f"{len(events)} stored events overlap"
    )
    print(
        f"{'night':<14}{'attendance':>11}{'no events':>11}{'with':>9}"
        f"{'effect':>9}{'95% range':>17}  biggest event"
    )
    for i, night in enumerate(with_events["stay_date"]):
        print(
            f"{night:%a %Y-%m-%d}{with_events[FEATURE][i]:>11,}"
            f"{baseline[i]:>11.2f}{rate[i]:>9.2f}{rate[i] - baseline[i]:>+9.2f}"
            f"{f'{lo[i]:.0f}-{hi[i]:.0f}':>17}  {_biggest(events, night)}"
        )


if __name__ == "__main__":
    main()
