import json
import os
from datetime import datetime, timezone

import boto3
from google import genai

from ai_analysis import generate_weather_analysis

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
BUCKET_NAME = os.environ["BUCKET_NAME"]

_gemini_client = None


def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = ssm.get_parameter(
            Name="/fishing-backend/gemini-api-key", WithDecryption=True
        )["Parameter"]["Value"]
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def extract_tide_values(tide: dict | list) -> list:
    """
    Extract angler-facing tide heights from the cached tide structure.
    """
    if isinstance(tide, list):
        return tide

    if not isinstance(tide, dict):
        return []

    values = []

    for item in tide.get("heights") or []:
        if not isinstance(item, dict):
            continue

        value = (
            item.get("display_height")
            if item.get("display_height") is not None
            else item.get("height_msl")
        )

        values.append(value)

    return values

def format_data_points(cached: dict) -> str:
    """
    Format the canonical daily cache payload for Gemini.

    Hourly arrays contain one local Sydney calendar day:
    index 0 = 00:00
    index 1 = 01:00
    ...
    index 23 = 23:00
    """
    marine = cached.get("marine") or {}
    weather = cached.get("weather") or {}
    tide = cached.get("tide") or {}

    astronomy = cached.get("astronomy") or {}
    fish_activity = cached.get("fish_activity") or {}

    return (
        f"Wave height (m): "
        f"{marine.get('wave_height', [])}\n"

        f"Wave period (s): "
        f"{marine.get('wave_period', [])}\n"

        f"Swell height (m): "
        f"{marine.get('swell_wave_height', [])}\n"

        f"Swell period (s): "
        f"{marine.get('swell_wave_period', [])}\n"

        f"Wind speed (km/h): "
        f"{weather.get('wind_speed_10m', [])}\n"

        f"Wind gusts (km/h): "
        f"{weather.get('wind_gusts_10m', [])}\n"

        f"Wind direction (degrees): "
        f"{weather.get('wind_direction_10m', [])}\n"

        f"Temperature (C): "
        f"{weather.get('temperature_2m', [])}\n"

        f"Apparent temperature (C): "
        f"{weather.get('apparent_temperature', [])}\n"

        f"Pressure (hPa): "
        f"{weather.get('pressure_msl', [])}\n"

        f"Tide height (m): "
        f"{extract_tide_values(tide)}\n"

        f"Sunrise: "
        f"{astronomy.get('sunrise')}\n"

        f"Sunset: "
        f"{astronomy.get('sunset')}\n"

        f"Moon phase: "
        f"{astronomy.get('moon_phase')}\n"

        f"Moon illumination: "
        f"{astronomy.get('moon_illumination')}%\n"

        f"Major periods: "
        f"{astronomy.get('major_periods', [])}\n"

        f"Minor periods: "
        f"{astronomy.get('minor_periods', [])}\n"

        f"Strike score: "
        f"{fish_activity.get('score')}\n"

        f"Strike label: "
        f"{fish_activity.get('label')}\n"

        f"Best fishing window: "
        f"{fish_activity.get('best_window')}\n"

        f"Best window type: "
        f"{fish_activity.get('best_window_type')}\n"

        f"Score breakdown: "
        f"{fish_activity.get('score_basis', {})}\n"

        f"Conditions at best window: "
        f"{fish_activity.get('conditions_at_best_window', {})}\n"

        f"Backend reasons: "
        f"{fish_activity.get('reasons', [])}"
    )

def handler(event, context):
    try:
        cache_key = event["cache_key"]
        location_name = event["location_name"]
        date_str = event["date_str"]
    except KeyError as exc:
        print(f"❌ Missing required event field: {exc}")
        return {"statusCode": 400}

    # Read the activity-ready cache from S3.
    try:
        obj = s3.get_object(
            Bucket=BUCKET_NAME,
            Key=cache_key,
        )
        cached = json.loads(obj["Body"].read())
    except Exception as exc:
        print(f"❌ Failed to read activity cache: {exc}")
        return {"statusCode": 500}

    data_points = format_data_points(cached)

    try:
        client = get_gemini_client()

        ai_text, model_used = generate_weather_analysis(
            client,
            location_name,
            date_str,
            data_points,
        )

        print(
            f"✅ Analysis done for {location_name} "
            f"{date_str} using {model_used}"
        )

    except Exception as exc:
        print(f"❌ Gemini analysis failed: {exc}")

        cached["analysis_status"] = "error"
        cached["analysis_error"] = str(exc)
        cached["analysis_failed_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=cache_key,
            Body=json.dumps(cached),
            ContentType="application/json",
        )

        return {"statusCode": 500}

    cached["status"] = "complete"
    cached["activity_status"] = "ready"
    cached["analysis_status"] = "ready"

    cached["analysis"] = ai_text
    cached["model_used"] = model_used
    cached["analysis_at"] = datetime.now(timezone.utc).isoformat()

    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=cache_key,
            Body=json.dumps(cached),
            ContentType="application/json",
        )

        print(f"✅ Cache updated to complete: {cache_key}")

    except Exception as exc:
        print(f"❌ Failed to write complete cache: {exc}")
        return {"statusCode": 500}

    return {"statusCode": 200}