import json
import os
from datetime import datetime, timezone, timedelta

import boto3
from google import genai

from weather_data import get_weather_data, get_astronomy_data
from ai_analysis import generate_weather_analysis

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
BUCKET_NAME = os.environ["BUCKET_NAME"]

BOTANY_BAY_LAT = -33.9929
BOTANY_BAY_LON = 151.2172

_gemini_client = None


def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = ssm.get_parameter(
            Name="/fishing-backend/gemini-api-key", WithDecryption=True
        )["Parameter"]["Value"]
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def make_cache_key(lat: float, lon: float, date_str: str) -> str:
    # Per-date cache key — satu file per hari per lokasi
    # Contoh: weather-cache/-33.9929_151.2172/2026-06-19.json
    return f"weather-cache/{round(lat, 4)}_{round(lon, 4)}/{date_str}.json"


def get_day_start_index(all_times, target_date_str):
    # Cari index jam pertama untuk tanggal tertentu dari array time Open-Meteo
    return next((i for i, t in enumerate(all_times) if t.startswith(target_date_str)), -1)


def format_data_points(res_m, res_w, res_t, start_idx, hours=24):
    hm = res_m.get("hourly", {})
    hw = res_w.get("hourly", {})
    end_idx = start_idx + hours
    return (
        f"Wave height (m): {hm.get('wave_height', [])[start_idx:end_idx]}\n"
        f"Swell height (m): {hm.get('swell_wave_height', [])[start_idx:end_idx]}\n"
        f"Swell period (s): {hm.get('swell_wave_period', [])[start_idx:end_idx]}\n"
        f"Wind speed (km/h): {hw.get('wind_speed_10m', [])[start_idx:end_idx]}\n"
        f"Temperature (C): {hw.get('temperature_2m', [])[start_idx:end_idx]}\n"
        f"Pressure (hPa): {hw.get('surface_pressure', [])[start_idx:end_idx]}\n"
        f"Tide height (m): {(res_t or [])[start_idx:end_idx]}"
    )


def handler(event, context):
    # Fetch semua data sekaligus — satu call ke Open-Meteo dapat 7 hari
    res_m, res_w, res_t, sea_lat, sea_lon = get_weather_data(BOTANY_BAY_LAT, BOTANY_BAY_LON)
    client = get_gemini_client()

    all_times = res_w.get("hourly", {}).get("time", [])
    today = datetime.utcnow() + timedelta(hours=10)  # aproksimasi AEST, belum handle AEDT

    # Loop 7 hari — tulis satu file JSON per hari ke S3
    for day_offset in range(7):
        target_dt = today + timedelta(days=day_offset)
        date_str = target_dt.strftime("%Y-%m-%d")

        start_idx = get_day_start_index(all_times, date_str)
        if start_idx == -1:
            # Data untuk tanggal ini belum tersedia di response Open-Meteo, skip
            print(f"⚠️ No data found for {date_str}, skipping.")
            continue

        astro = get_astronomy_data(target_dt, BOTANY_BAY_LAT, BOTANY_BAY_LON)
        data_points = format_data_points(res_m, res_w, res_t, start_idx)
        ai_text, model_used = generate_weather_analysis(client, "Botany Bay", date_str, data_points)

        # Payload per hari — hanya data 24 jam untuk tanggal ini
        payload = {
            "name": "Botany Bay",
            "state": "NSW",
            "lat": BOTANY_BAY_LAT,
            "lon": BOTANY_BAY_LON,
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
            **astro,
            "analysis": ai_text,
            "model_used": model_used,
        }

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=make_cache_key(BOTANY_BAY_LAT, BOTANY_BAY_LON, date_str),
            Body=json.dumps(payload),
            ContentType="application/json",
        )
        print(f"✅ Cache written: {date_str}")

    return {"statusCode": 200}