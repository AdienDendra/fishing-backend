import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import THE_LEAP_LAT, THE_LEAP_LON
from weather_cache_pipeline import WeatherCachePipeline

BUCKET_NAME = os.environ["BUCKET_NAME"]
ACTIVITY_FUNCTION_NAME = os.environ["ACTIVITY_FUNCTION_NAME"]

SYDNEY_TZ = ZoneInfo("Australia/Sydney")

pipeline = WeatherCachePipeline(
    bucket_name=BUCKET_NAME,
    activity_function_name=ACTIVITY_FUNCTION_NAME,
)


PREWARM_LOCATIONS = [
    {
        "name": "The Leap, Kurnell",
        "state": "NSW",
        "lat": THE_LEAP_LAT,
        "lon": THE_LEAP_LON,
    },
]


def handler(event, context):
    """
    Scheduled pre-warm entrypoint.

    Triggered by EventBridge cron. It prepares cache files for selected
    public website locations using the same partial cache contract as
    weather_handler.

    Difference from weather_handler:
    - weather_handler handles one user-requested lat/lon/date
    - weather_processor pre-warms configured locations for multiple days
    """
    today = datetime.now(SYDNEY_TZ).date()

    for location in PREWARM_LOCATIONS:
        location_name = location["name"]
        lat = round(location["lat"], 4)
        lon = round(location["lon"], 4)

        print(f"🌊 Pre-warming cache for {location_name}")

        try:
            # One Open-Meteo response contains multiple forecast days.
            weather_bundle = pipeline.fetch_weather_bundle(lat, lon)

        except Exception as exc:
            print(f"❌ Failed to fetch weather data for {location_name}: {exc}")
            continue

        for day_offset in range(7):
            date_str = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")

            try:
                pipeline.build_and_write_partial_cache(
                    location_name=location_name,
                    state=location.get("state"),
                    lat=lat,
                    lon=lon,
                    date_str=date_str,
                    weather_bundle=weather_bundle,
                )

            except ValueError as exc:
                print(f"⚠️ {location_name} {date_str}: {exc}")

            except Exception as exc:
                print(f"❌ Failed to pre-warm {location_name} {date_str}: {exc}")

    return {"statusCode": 200}