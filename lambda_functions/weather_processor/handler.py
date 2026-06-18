import json
import os
from datetime import datetime, timezone

import boto3

s3 = boto3.client("s3")
BUCKET_NAME = os.environ["BUCKET_NAME"]

BOTANY_BAY_LAT = -33.9645
BOTANY_BAY_LON = 151.2316


def make_cache_key(lat: float, lon: float) -> str:
    return f"weather-cache/{round(lat, 4)}_{round(lon, 4)}.json"


def handler(event, context):
    # TODO: ganti dengan panggilan ke logic existing kamu
    # raw_data = get_weather_data(BOTANY_BAY_LAT, BOTANY_BAY_LON)
    # analysis = ...

    payload = {
        "name": "Botany Bay",
        "state": "NSW",
        "lat": BOTANY_BAY_LAT,
        "lon": BOTANY_BAY_LON,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        # TODO: field hasil analysis lainnya
    }

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=make_cache_key(BOTANY_BAY_LAT, BOTANY_BAY_LON),
        Body=json.dumps(payload),
        ContentType="application/json",
    )

    return {"statusCode": 200}