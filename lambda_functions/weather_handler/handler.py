import json
import os

import boto3

from cache_keys import make_cache_key
from weather_cache_pipeline import WeatherCachePipeline

s3 = boto3.client("s3")

BUCKET_NAME = os.environ["BUCKET_NAME"]
ACTIVITY_FUNCTION_NAME = os.environ["ACTIVITY_FUNCTION_NAME"]

pipeline = WeatherCachePipeline(
    bucket_name=BUCKET_NAME,
    activity_function_name=ACTIVITY_FUNCTION_NAME,
)


# Whitelist origin yang diizinkan — production + localhost untuk development
ALLOWED_ORIGINS = [
    "https://fishing.adiendendra.com",
    "http://localhost:1313",
    "http://localhost:8080",
]


def cors_response(status_code: int, body: dict, origin: str = "") -> dict:
    """
    Build API Gateway response with CORS headers.
    """
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


def handler(event, context):
    """
    API Gateway entrypoint.

    Responsibilities:
    - parse query parameters
    - handle CORS
    - return cache hit immediately
    - delegate cache miss creation to WeatherCachePipeline
    """
    origin = event.get("headers", {}).get("origin", "")

    # Handle preflight CORS request dari browser
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return cors_response(200, {}, origin)

    params = event.get("queryStringParameters") or {}

    try:
        lat = round(float(params["lat"]), 4)
        lon = round(float(params["lon"]), 4)
        date_str = params["date"]
        location_name = params.get("name", f"{lat},{lon}")
    except (KeyError, ValueError, TypeError):
        return cors_response(
            400,
            {"error": "Missing or invalid parameters: lat, lon, date required"},
            origin,
        )

    cache_key = make_cache_key(lat, lon, date_str)

    # Cache-aside read path
    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=cache_key)
        cached = json.loads(obj["Body"].read())

        print(f"✅ Cache HIT: {cache_key}")
        return cors_response(200, cached, origin)

    except s3.exceptions.NoSuchKey:
        print(f"⚠️ Cache MISS: {cache_key}")

    except Exception as exc:
        # Non-fatal. Continue to fetch from Open-Meteo.
        print(f"⚠️ S3 read error: {exc}")

    # Cache miss write path
    try:
        payload = pipeline.build_and_write_partial_cache(
            location_name=location_name,
            lat=lat,
            lon=lon,
            date_str=date_str,
        )

    except ValueError as exc:
        return cors_response(404, {"error": str(exc)}, origin)

    except Exception as exc:
        return cors_response(
            500,
            {"error": f"Failed to build weather cache: {str(exc)}"},
            origin,
        )

    # Return partial data immediately. weather_activity continues async.
    return cors_response(200, payload, origin)