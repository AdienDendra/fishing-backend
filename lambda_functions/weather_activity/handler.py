import json
import os
from datetime import datetime, timezone

import boto3

from astronomy import get_astronomy_data
from fishing_activity import build_fish_activity

s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")

BUCKET_NAME = os.environ["BUCKET_NAME"]
ANALYSIS_FUNCTION_NAME = os.environ["ANALYSIS_FUNCTION_NAME"]


def handler(event, context):
    try:
        lat = float(event["lat"])
        lon = float(event["lon"])
        date_str = event["date_str"]
        location_name = event["location_name"]
        cache_key = event["cache_key"]
    except KeyError as exc:
        print(f"❌ Missing required event field: {exc}")
        return {"statusCode": 400}

    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=cache_key)
        cached = json.loads(obj["Body"].read())
    except Exception as exc:
        print(f"❌ Failed to read partial cache: {exc}")
        return {"statusCode": 500}

    try:
        astronomy = get_astronomy_data(
            date_str=date_str,
            lat=lat,
            lon=lon,
            timezone_name="Australia/Sydney",
            daily=cached.get("daily") or {},
        )

        fish_activity = build_fish_activity(
            astronomy=astronomy,
            tide=cached.get("tide") or [],
            weather=cached.get("weather") or {},
            marine=cached.get("marine") or {},
        )

    except Exception as exc:
        print(f"❌ Activity calculation failed: {exc}")
        return {"statusCode": 500}

    cached["status"] = "activity_ready"
    cached["activity_schema_version"] = "1.0"
    cached["astronomy"] = astronomy
    cached["fish_activity"] = fish_activity
    # Backward-compatible aliases for current frontend weather-fetch.js.
    cached["sr"] = astronomy.get("sunrise")
    cached["ss"] = astronomy.get("sunset")
    cached["major"] = fish_activity.get("major")
    cached["minor"] = fish_activity.get("minor")
    cached["low"] = fish_activity.get("low")
    cached["activity_calculated_at"] = datetime.now(timezone.utc).isoformat()


    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=cache_key,
            Body=json.dumps(cached),
            ContentType="application/json",
        )
        print(f"✅ Cache updated to activity_ready: {cache_key}")
    except Exception as exc:
        print(f"❌ Failed to write activity cache: {exc}")
        return {"statusCode": 500}

    try:
        lambda_client.invoke(
            FunctionName=ANALYSIS_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({
                "lat": lat,
                "lon": lon,
                "date_str": date_str,
                "location_name": location_name,
                "cache_key": cache_key,
            }),
        )
        print(f"🚀 Triggered weather_analysis async for {location_name} {date_str}")
    except Exception as exc:
        print(f"⚠️ Failed to trigger analysis: {exc}")

    return {"statusCode": 200}