"""Generates mock hotel data with a known pricing rule.

Run from backend/: uv run python scripts/generate_mock_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "mock_hotel_data.csv"

# RoomType.name: (base_rate, room_count)
ROOM_TYPES = {
    "standard": (120.0, 30),
    "deluxe": (180.0, 15),
    "suite": (300.0, 5),
}

# CompetitorRate.hotel_name: typical nightly rate
COMPETITORS = {
    "harbour_view": 140.0,
    "the_grand": 230.0,
    "city_lodge": 160.0,
    "riverside": 190.0,
}
COMPETITOR_REF = np.mean(list(COMPETITORS.values()))


def generate(seed: int = 9, start: str = "2024-01-01", days: int = 730) -> pd.DataFrame:
    """Generates one row per room type per night.

    Args:
        seed (int): Random seed for reproducible data.
        start (str): First stay date, as YYYY-MM-DD.
        days (int): Number of nights to generate.

    Returns:
        pd.DataFrame: Mock nightly data, sorted by stay_date then room_type.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=days, freq="D")
    doy = dates.dayofyear.to_numpy()
    is_weekend = dates.dayofweek.isin([4, 5]).astype(int)  # Fri, Sat nights
    season = 0.15 * np.sin(2 * np.pi * (doy - 100) / 365)

    # Weather: warm summers, rain on ~35% of days.
    temp_max_c = 12 + 7 * np.sin(2 * np.pi * (doy - 110) / 365) + rng.normal(0, 2, days)
    temp_min_c = temp_max_c - rng.normal(6, 1.5, days)
    rainy = rng.random(days) < 0.35
    precip_mm = np.where(rainy, rng.exponential(6, days), 0.0)
    wind_kph = rng.gamma(2, 8, days) + 8 * rainy
    condition = np.where(
        rainy, "rain", np.where(rng.random(days) < 0.5, "cloudy", "sunny")
    )

    # Events: total expected attendance of the day's events, ~10% of days.
    has_event = rng.random(days) < 0.10
    expected_attendance = np.where(has_event, rng.lognormal(9.5, 0.7, days), 0)

    demand = np.clip(
        0.55
        + season
        + 0.15 * is_weekend
        + 0.25 * np.minimum(expected_attendance / 40_000, 1)
        - 0.05 * rainy
        - 0.03 * (wind_kph > 30)
        + rng.normal(0, 0.03, days),
        0.05,
        1.0,
    )

    # Flights into the city.
    flight_count = (
        400 + 300 * season + 60 * is_weekend + expected_attendance / 200
    ) + rng.normal(0, 25, days)
    avg_fare_eur = 110 + 150 * (demand - 0.55) + rng.normal(0, 10, days)

    # Competitors: each lists a rate or sells out; summarized per night.
    listed = np.column_stack(
        [
            typical * (1 + 0.8 * (demand - 0.55)) * rng.normal(1, 0.05, days)
            for typical in COMPETITORS.values()
        ]
    )
    sold_out = rng.random(listed.shape) < np.clip(2 * (demand - 0.8), 0, 0.5)[:, None]
    all_sold_out = sold_out.all(axis=1)
    competitor_rate = np.where(
        all_sold_out,  # no rate to observe; fall back to what they'd have listed
        listed.mean(axis=1),
        np.nanmean(np.where(sold_out, np.nan, listed), axis=1),
    )
    competitors_sold_out = sold_out.sum(axis=1)

    frames = []
    for room_type, (base_rate, room_count) in ROOM_TYPES.items():
        # Pricing rule the models should learn.
        fair_rate = base_rate * (0.75 + 0.5 * demand)
        rate = (
            fair_rate
            + 0.3 * base_rate * (competitor_rate / COMPETITOR_REF - 1)
            + 0.05 * base_rate * is_weekend
            + rng.normal(0, 0.03 * base_rate, days)
        )
        occupancy_prob = np.clip(
            demand + rng.normal(0, 0.05, days) - 1.5 * (rate / fair_rate - 1), 0, 1
        )
        rooms_sold = rng.binomial(room_count, occupancy_prob)

        frames.append(
            pd.DataFrame(
                {
                    # DailyPerformance / RoomType
                    "stay_date": dates.date,
                    "room_type": room_type,
                    "base_rate": base_rate,
                    "rooms_available": room_count,
                    "rate": rate.round(2),
                    "rooms_sold": rooms_sold,
                    "room_revenue": (rate.round(2) * rooms_sold).round(2),
                    "occupancy": (rooms_sold / room_count).round(4),
                    # From stay_date
                    "day_of_week": dates.dayofweek,
                    "month": dates.month,
                    "is_weekend": is_weekend,
                    # Weather
                    "temp_max_c": temp_max_c.round(1),
                    "temp_min_c": temp_min_c.round(1),
                    "precip_mm": precip_mm.round(1),
                    "wind_kph": wind_kph.round(1),
                    "condition": condition,
                    # Event
                    "expected_attendance": expected_attendance.round().astype(int),
                    # CompetitorRate
                    "competitor_rate": competitor_rate.round(2),
                    "competitors_sold_out": competitors_sold_out,
                    # FlightArrival
                    "flight_count": flight_count.round().astype(int),
                    "avg_fare_eur": avg_fare_eur.round(2),
                }
            )
        )

    return (
        pd.concat(frames)
        .sort_values(["stay_date", "room_type"], kind="stable")
        .reset_index(drop=True)
    )


def write_csv(path: Path = CSV_PATH) -> Path:
    """Generates the mock data and writes it to a CSV.

    Args:
        path (Path): Where to write the CSV.

    Returns:
        Path: The path written to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    generate().to_csv(path, index=False)
    return path


if __name__ == "__main__":
    print(f"Wrote {write_csv()}")
