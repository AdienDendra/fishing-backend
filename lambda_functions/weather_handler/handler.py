import json
import os
from datetime import datetime, timezone

import boto3

from weather_data import get_weather_data

s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")
BUCKET_NAME = os.environ["BUCKET_NAME"]
ACTIVITY_FUNCTION_NAME = os.environ["ACTIVITY_FUNCTION_NAME"]


# Whitelist origin yang diizinkan — production + localhost untuk development
ALLOWED_ORIGINS = [
    "https://fishing.adiendendra.com",
    "http://localhost:1313",
    "http://localhost:8080",
]


def cors_response(status_code: int, body: dict, origin: str = "") -> dict:
    # Kalau origin ada di whitelist, pakai itu — kalau tidak, fallback ke production
    cors_origin = origin if origin in ALLOWED_ORIGINS else "https://fishing.adiendendra.com"
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": cors_origin,
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }


def make_cache_key(lat: float, lon: float, date_str: str) -> str:
    return f"weather-cache/{round(lat, 4)}_{round(lon, 4)}/{date_str}.json"


def get_day_start_index(all_times, target_date_str):
    return next((i for i, t in enumerate(all_times) if t.startswith(target_date_str)), -1)


def handler(event, context):
    # Ambil origin dari request header — untuk CORS
    origin = event.get("headers", {}).get("origin", "")

    # Handle preflight CORS request dari browser
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return cors_response(200, {}, origin)

    # 1. Parse query parameters dari API Gateway
    params = event.get("queryStringParameters") or {}
    try:
        lat = round(float(params["lat"]), 4)
        lon = round(float(params["lon"]), 4)
        date_str = params["date"]       # format: YYYY-MM-DD
        location_name = params.get("name", f"{lat},{lon}")
    except (KeyError, ValueError, TypeError):
        return cors_response(400, {"error": "Missing or invalid parameters: lat, lon, date required"}, origin)

    cache_key = make_cache_key(lat, lon, date_str)

    # 2. Cek S3 cache dulu (cache-aside pattern)
    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=cache_key)
        cached = json.loads(obj["Body"].read())

        # Cache HIT — return langsung, apapun statusnya (partial atau complete)
        print(f"✅ Cache HIT: {cache_key}")
        return cors_response(200, cached, origin)

    except s3.exceptions.NoSuchKey:
        # Cache MISS — lanjut fetch dari Open-Meteo
        print(f"⚠️ Cache MISS: {cache_key}")

    except Exception as e:
        # S3 error lain — log tapi tetap lanjut fetch
        print(f"⚠️ S3 read error: {e}")

    # 3. Cache MISS — fetch data dari Open-Meteo
    try:
        res_m, res_w, res_t, sea_lat, sea_lon = get_weather_data(lat, lon)
    except Exception as e:
        return cors_response(500, {"error": f"Failed to fetch weather data: {str(e)}"}, origin)

    all_times = res_w.get("hourly", {}).get("time", [])
    start_idx = get_day_start_index(all_times, date_str)

    if start_idx == -1:
        return cors_response(404, {"error": f"No data available for date: {date_str}"}, origin)

    # 5. Susun payload "partial" — data cuaca lengkap, analysis belum ada
    payload = {
        "status": "partial",
        "name": location_name,
        "lat": lat,
        "lon": lon,
        "sea_lat": sea_lat,
        "sea_lon": sea_lon,
        "date": date_str,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "marine": {
            k: v[start_idx:start_idx + 24]
            for k, v in res_m.get("hourly", {}).items()
        },
        "weather": {
            k: v[start_idx:start_idx + 24]
            for k, v in res_w.get("hourly", {}).items()
        },
        "tide": (res_t or [])[start_idx:start_idx + 24],
        "analysis": None,
        "model_used": None,
        "activity_schema_version": "1.0",
        "astronomy": None,
        "fish_activity": None,
    }

    # 6. Tulis cache "partial" ke S3
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=cache_key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )
        print(f"✅ Partial cache written: {cache_key}")
    except Exception as e:
        print(f"⚠️ S3 write error (non-fatal): {e}")

    # 7. Trigger weather_activity Lambda secara async (fire-and-forget)
    try:
        activity_payload = {
            "lat": lat,
            "lon": lon,
            "date_str": date_str,
            "location_name": location_name,
            "cache_key": cache_key,
        }

        lambda_client.invoke(
            FunctionName=ACTIVITY_FUNCTION_NAME,
            InvocationType="Event",     # fire-and-forget
            Payload=json.dumps(activity_payload),
        )
        print(f"🚀 Triggered weather_activity async for {location_name} {date_str}")
    except Exception as e:
        print(f"⚠️ Failed to trigger activity (non-fatal): {e}")

    # 8. Return data cuaca ke frontend LANGSUNG tanpa tunggu Gemini
    return cors_response(200, payload, origin)