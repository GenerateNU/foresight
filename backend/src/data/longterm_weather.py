import openmeteo_requests

import pandas as pd
import requests_cache
from retry_requests import retry

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://climate-api.open-meteo.com/v1/climate"
params = {
    "latitude": 53.331,
    "longitude": -6.2489,
    "start_date": "2026-01-01",
    "end_date": "2030-12-31",
    "models": ["CMCC_CM2_VHR4", "FGOALS_f3_H", "HiRAM_SIT_HR", "MRI_AGCM3_2_S", "EC_Earth3P_HR", "MPI_ESM1_2_XR", "NICAM16_8S"],
    "timeformat": "unixtime",
    "wind_speed_unit": "mph",
    "temperature_unit": "fahrenheit",
    "precipitation_unit": "inch",
    "daily": ["temperature_2m_mean", "wind_speed_10m_mean", "cloud_cover_mean", "shortwave_radiation_sum", "precipitation_sum"],
}
responses = openmeteo.weather_api(url, params = params)

# Process 1 location and 7 models
for response in responses:
    print(f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E")
    print(f"Elevation: {response.Elevation()} m asl")
    print(f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s")
    print(f"Model Nº: {response.Model()}")

    # Process daily data. The order of variables needs to be the same as requested.
    daily = response.Daily()
    daily_temperature_2m_mean = daily.Variables(0).ValuesAsNumpy()
    daily_wind_speed_10m_mean = daily.Variables(1).ValuesAsNumpy()
    daily_cloud_cover_mean = daily.Variables(2).ValuesAsNumpy()
    daily_precipitation_sum = daily.Variables(4).ValuesAsNumpy()

    daily_data = {
    "date": pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left",
    ).date
}
    
    daily_data["temp_mean"] = daily_temperature_2m_mean
    daily_data["wind_speed_mean"] = daily_wind_speed_10m_mean
    daily_data["cloud_cover_mean"] = daily_cloud_cover_mean
    daily_data["precipitation_sum"] = daily_precipitation_sum

    daily_dataframe = pd.DataFrame(data = daily_data)
    print("\nDaily data\n", daily_dataframe)
    print(daily_dataframe.isnull().values.any())