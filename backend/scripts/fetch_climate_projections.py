import argparse
from pathlib import Path

import pandas as pd

from foresight.ingest.weather import _get_client

CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "weather"

_CLIMATE_MODELS = (
    "CMCC_CM2_VHR4",
    "FGOALS_f3_H",
    "HiRAM_SIT_HR",
    "MRI_AGCM3_2_S",
    "EC_Earth3P_HR",
    "MPI_ESM1_2_XR",
    "NICAM16_8S",
)


def fetch_climate_projections(
    city: str,
    latitude: float,
    longitude: float,
    *,
    start: str = "2026-01-01",
    end: str = "2030-12-31",
    models: tuple[str, ...] = _CLIMATE_MODELS,
) -> pd.DataFrame:
    """Multi-model climate projections, written to CSV.

    Not persisted: these are per-model projections of a future decade, and
    `weather` holds one row per city per day. Kept for exploration until we
    decide whether the models belong in the schema at all.
    """
    responses = _get_client().weather_api(
        CLIMATE_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start,
            "end_date": end,
            "models": list(models),
            "daily": ["temperature_2m_mean", "precipitation_sum"],
        },
    )

    frames = []
    for response in responses:
        daily = response.Daily()
        frames.append(
            pd.DataFrame(
                {
                    "date": pd.date_range(
                        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
                        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
                        freq=pd.Timedelta(seconds=daily.Interval()),
                        inclusive="left",
                    ).date,
                    "city": city,
                    "model": response.Model(),
                    "temp_mean_c": daily.Variables(0).ValuesAsNumpy(),
                    "precip_mm": daily.Variables(1).ValuesAsNumpy(),
                }
            )
        )

    combined = pd.concat(frames, ignore_index=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT_DIR / f"climate_{city}.csv", index=False)
    return combined


def main():
    parser = argparse.ArgumentParser(
        description="Write multi-model climate projections for a city to CSV."
    )
    parser.add_argument("--city", required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    args = parser.parse_args()
    frame = fetch_climate_projections(args.city, args.lat, args.lon)
    print(f"{len(frame)} rows -> {OUTPUT_DIR / f'climate_{args.city}.csv'}")


if __name__ == "__main__":
    main()
