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


def format_data_points(marine, weather, tide, start_idx=0, hours=24):
    # Data sudah di-slice 24 jam oleh weather_handler sebelum dikirim
    # start_idx di sini selalu 0 karena array sudah dimulai dari jam pertama hari itu
    hm = marine
    hw = weather
    end_idx = start_idx + hours
    return (
        f"Wave height (m): {hm.get('wave_height', [])[start_idx:end_idx]}\n"
        f"Swell height (m): {hm.get('swell_wave_height', [])[start_idx:end_idx]}\n"
        f"Swell period (s): {hm.get('swell_wave_period', [])[start_idx:end_idx]}\n"
        f"Wind speed (km/h): {hw.get('wind_speed_10m', [])[start_idx:end_idx]}\n"
        f"Temperature (C): {hw.get('temperature_2m', [])[start_idx:end_idx]}\n"
        f"Pressure (hPa): {hw.get('surface_pressure', [])[start_idx:end_idx]}\n"
        f"Tide height (m): {(tide or [])[start_idx:end_idx]}"
    )


def handler(event, context):
    # event berisi payload dari weather_handler via lambda_client.invoke()
    try:
        lat = event["lat"]
        lon = event["lon"]
        date_str = event["date_str"]
        location_name = event["location_name"]
        cache_key = event["cache_key"]

        # Data sudah di-slice 24 jam oleh weather_handler
        marine = event["marine"]
        weather = event["weather"]
        tide = event["tide"]

    except KeyError as e:
        print(f"❌ Missing required field in event payload: {e}")
        return {"statusCode": 400}

    # 1. Format data points untuk prompt Gemini
    data_points = format_data_points(marine, weather, tide)

    # 2. Panggil Gemini — ini yang memakan waktu 5-15 detik
    client = get_gemini_client()
    ai_text, model_used = generate_weather_analysis(
        client, location_name, date_str, data_points
    )
    print(f"✅ Analysis done for {location_name} {date_str} using {model_used}")

    # 3. Baca cache partial yang sudah ditulis weather_handler
    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=cache_key)
        cached = json.loads(obj["Body"].read())
    except Exception as e:
        print(f"❌ Failed to read partial cache: {e}")
        return {"statusCode": 500}

    # 4. Update cache dari "partial" → "complete"
    cached["status"] = "complete"
    cached["analysis"] = ai_text
    cached["model_used"] = model_used
    cached["analysis_at"] = datetime.now(timezone.utc).isoformat()

    # 5. Overwrite cache di S3
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=cache_key,
            Body=json.dumps(cached),
            ContentType="application/json",
        )
        print(f"✅ Cache updated to complete: {cache_key}")
    except Exception as e:
        print(f"❌ Failed to write complete cache: {e}")
        return {"statusCode": 500}

    return {"statusCode": 200}