# imports
from pathlib import Path

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

DATA_DIR = Path(__file__).resolve().parent


# Shared Open-Meteo client setup
cache_session = requests_cache.CachedSession(".cache", expire_after=3600)

retry_session = retry(cache_session, retries=5, backoff_factor=0.2)

openmeteo = openmeteo_requests.Client(session=retry_session)


def fetch_longterm_weather(location_name, latitude, longitude):
    url = "https://climate-api.open-meteo.com/v1/climate"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": "2026-01-01",
        "end_date": "2030-12-31",
        "models": [
            "CMCC_CM2_VHR4",
            "FGOALS_f3_H",
            "HiRAM_SIT_HR",
            "MRI_AGCM3_2_S",
            "EC_Earth3P_HR",
            "MPI_ESM1_2_XR",
            "NICAM16_8S",
        ],
        "timeformat": "unixtime",
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "daily": [
            "temperature_2m_mean",
            "wind_speed_10m_mean",
            "cloud_cover_mean",
            "precipitation_sum",
        ],
    }

    print("\n" + "=" * 60)
    print(f"LONG-TERM WEATHER: {location_name}")
    print(f"Latitude: {latitude}")
    print(f"Longitude: {longitude}")
    print("=" * 60)

    responses = openmeteo.weather_api(url, params=params)

    all_longterm_data = []

    for response in responses:
        daily = response.Daily()

        daily_temperature_2m_mean = daily.Variables(0).ValuesAsNumpy()

        daily_wind_speed_10m_mean = daily.Variables(1).ValuesAsNumpy()

        daily_cloud_cover_mean = daily.Variables(2).ValuesAsNumpy()

        daily_precipitation_sum = daily.Variables(3).ValuesAsNumpy()

        daily_data = {
            "date": pd.date_range(
                start=pd.to_datetime(daily.Time(), unit="s", utc=True),
                end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=daily.Interval()),
                inclusive="left",
            ).date,
            "location": location_name,
            "model_number": response.Model(),
            "temperature_mean_f": daily_temperature_2m_mean,
            "wind_speed_mean_mph": daily_wind_speed_10m_mean,
            "cloud_cover_mean_pct": daily_cloud_cover_mean,
            "precipitation_sum_in": daily_precipitation_sum,
        }

        daily_dataframe = pd.DataFrame(daily_data)

        daily_dataframe = daily_dataframe.round(
            {
                "temperature_mean_f": 2,
                "wind_speed_mean_mph": 2,
                "cloud_cover_mean_pct": 2,
                "precipitation_sum_in": 3,
            }
        )

        print(f"\nModel {response.Model()} sample:")

        print(daily_dataframe.head())

        print("\nMissing values:")
        print(daily_dataframe.isnull().sum())

        all_longterm_data.append(daily_dataframe)

    combined_longterm = pd.concat(all_longterm_data, ignore_index=True)

    filename = DATA_DIR / f"longterm_weather_{location_name}.csv"

    combined_longterm.to_csv(filename, index=False)

    print(f"\nSaved long-term weather to: {filename}")

    return combined_longterm


def fetch_shortterm_weather(location_name, latitude, longitude, timezone):
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": [
            "apparent_temperature_max",
            "precipitation_sum",
            "uv_index_clear_sky_max",
            "daylight_duration",
            "wind_gusts_10m_max",
        ],
        "timezone": timezone,
        "forecast_days": 16,
    }

    print("\n" + "=" * 60)
    print(f"SHORT-TERM WEATHER: {location_name}")
    print(f"Latitude: {latitude}")
    print(f"Longitude: {longitude}")
    print("=" * 60)

    responses = openmeteo.weather_api(url, params=params)

    response = responses[0]

    daily = response.Daily()

    daily_apparent_temperature_max = daily.Variables(0).ValuesAsNumpy()

    daily_precipitation_sum = daily.Variables(1).ValuesAsNumpy()

    daily_uv_index_clear_sky_max = daily.Variables(2).ValuesAsNumpy()

    daily_daylight_duration = daily.Variables(3).ValuesAsNumpy()

    daily_wind_gusts_10m_max = daily.Variables(4).ValuesAsNumpy()

    daily_data = {
        "date": pd.date_range(
            start=pd.to_datetime(daily.Time(), unit="s", utc=True),
            end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=daily.Interval()),
            inclusive="left",
        ).tz_convert(response.Timezone().decode()),
        "location": location_name,
        "apparent_temperature_max": daily_apparent_temperature_max,
        "precipitation_sum": daily_precipitation_sum,
        "uv_index_clear_sky_max": daily_uv_index_clear_sky_max,
        "daylight_duration": daily_daylight_duration,
        "wind_gusts_10m_max": daily_wind_gusts_10m_max,
    }

    daily_dataframe = pd.DataFrame(daily_data)

    daily_dataframe = daily_dataframe.round(
        {
            "apparent_temperature_max": 2,
            "precipitation_sum": 3,
            "uv_index_clear_sky_max": 2,
            "daylight_duration": 2,
            "wind_gusts_10m_max": 2,
        }
    )

    # Remove incomplete forecast rows
    daily_dataframe = daily_dataframe.dropna().reset_index(drop=True)

    print("\nShort-term weather sample:")
    print(daily_dataframe.head())

    print("\nMissing values:")
    print(daily_dataframe.isnull().sum())

    filename = DATA_DIR / f"shortterm_weather_{location_name}.csv"

    daily_dataframe.to_csv(filename, index=False)

    print(f"\nSaved short-term weather to: {filename}")

    return daily_dataframe


if __name__ == "__main__":
    test_locations = [
        ("Dublin", 53.331, -6.2489, "Europe/Dublin"),
        ("Boston", 42.3601, -71.0589, "America/New_York"),
        ("Madrid", 40.4168, -3.7038, "Europe/Madrid"),
    ]

    for name, latitude, longitude, timezone in test_locations:
        fetch_longterm_weather(name, latitude, longitude)

        fetch_shortterm_weather(name, latitude, longitude, timezone)
