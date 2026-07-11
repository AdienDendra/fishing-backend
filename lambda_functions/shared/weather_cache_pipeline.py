import json
from datetime import datetime, timezone

import boto3

from cache_keys import make_cache_key
from weather_data import (
    get_weather_data,
    filter_daily_for_date,
    filter_tide_for_date,
)

class WeatherCachePipeline:
    """
    Shared weather cache pipeline.

    Used by:
    - weather_handler: on-demand API request
    - weather_processor: scheduled pre-warm job

    This class builds the initial partial cache and triggers weather_activity.
    It does not calculate fish activity and does not call Gemini directly.
    """

    def __init__(
        self,
        bucket_name: str,
        activity_function_name: str,
        s3_client=None,
        lambda_client=None,
    ):
        self.bucket_name = bucket_name
        self.activity_function_name = activity_function_name
        self.s3 = s3_client or boto3.client("s3")
        self.lambda_client = lambda_client or boto3.client("lambda")

    @staticmethod
    def extract_hhmm(value: str | None) -> str | None:
        """
        Extract HH:MM from an Open-Meteo local ISO timestamp.

        Example:
            2026-07-10T07:00 -> 07:00
        """
        if not value:
            return None

        text = str(value)

        if "T" in text and len(text) >= 16:
            return text[11:16]

        return text[:5] if len(text) >= 5 else None

    def fetch_weather_bundle(self, lat: float, lon: float):
        """
        Fetch marine, weather, tide, and sea coordinates from Open-Meteo.
        """
        return get_weather_data(lat, lon)

    @staticmethod
    def get_day_start_index(all_times: list, target_date_str: str) -> int:
        """
        Find first hourly index for YYYY-MM-DD in Open-Meteo hourly time array.
        """
        return next(
            (
                index
                for index, timestamp in enumerate(all_times)
                if timestamp.startswith(target_date_str)
            ),
            -1,
        )

    @staticmethod
    def build_partial_payload(
        *,
        location_name: str,
        lat: float,
        lon: float,
        date_str: str,
        start_idx: int,
        res_m: dict,
        res_w: dict,
        res_t: list,
        sea_lat: float,
        sea_lon: float,
        state: str | None = None,
    ) -> dict:
        """
        Build the canonical partial weather cache payload.

        Sunrise and sunset are extracted immediately from the Open-Meteo
        daily response, while fish activity and AI analysis continue
        asynchronously.
        """
        daily = filter_daily_for_date(res_w, date_str)

        payload = {
            "status": "partial",
            "activity_status": "pending",
            "analysis_status": "pending",

            "name": location_name,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "sea_lat": sea_lat,
            "sea_lon": sea_lon,
            "date": date_str,
            "fetched_at": datetime.now(timezone.utc).isoformat(),

            "marine": {
                key: value[start_idx:start_idx + 24]
                for key, value in res_m.get("hourly", {}).items()
            },
            "weather": {
                key: value[start_idx:start_idx + 24]
                for key, value in res_w.get("hourly", {}).items()
            },

            "daily": daily,
            "tide": filter_tide_for_date(res_t, date_str),

            # Available immediately from Open-Meteo.
            "sr": WeatherCachePipeline.extract_hhmm(
                daily.get("sunrise")
            ),
            "ss": WeatherCachePipeline.extract_hhmm(
                daily.get("sunset")
            ),

            "analysis": None,
            "model_used": None,

            "activity_schema_version": "2.1",
            "astronomy": None,
            "fish_activity": None,
        }

        if state:
            payload["state"] = state

        return payload

    def write_partial_cache(self, cache_key: str, payload: dict) -> None:
        """
        Write partial weather cache to S3.
        """
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=cache_key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )

        print(f"✅ Partial cache written: {cache_key}")

    def trigger_weather_activity(
        self,
        *,
        lat: float,
        lon: float,
        date_str: str,
        location_name: str,
        cache_key: str,
    ) -> None:
        """
        Trigger weather_activity asynchronously.

        weather_activity will:
        - read the partial cache from S3
        - calculate astronomy + fish_activity
        - update cache to activity_ready
        - trigger weather_analysis
        """
        activity_payload = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "date_str": date_str,
            "location_name": location_name,
            "cache_key": cache_key,
        }

        self.lambda_client.invoke(
            FunctionName=self.activity_function_name,
            InvocationType="Event",
            Payload=json.dumps(activity_payload),
        )

        print(f"🚀 Triggered weather_activity async for {location_name} {date_str}")

    def build_and_write_partial_cache(
        self,
        *,
        location_name: str,
        lat: float,
        lon: float,
        date_str: str,
        state: str | None = None,
        weather_bundle=None,
    ) -> dict:
        """
        Build partial cache for one location and one date.

        If weather_bundle is provided, it reuses an existing Open-Meteo response.
        This is useful for weather_processor because one Open-Meteo response
        contains multiple forecast days.
        """
        if weather_bundle is None:
            weather_bundle = self.fetch_weather_bundle(lat, lon)

        res_m, res_w, res_t, sea_lat, sea_lon = weather_bundle

        all_times = res_w.get("hourly", {}).get("time", [])
        start_idx = self.get_day_start_index(all_times, date_str)

        if start_idx == -1:
            raise ValueError(f"No data available for date: {date_str}")

        cache_key = make_cache_key(lat, lon, date_str)

        payload = self.build_partial_payload(
            location_name=location_name,
            lat=lat,
            lon=lon,
            date_str=date_str,
            start_idx=start_idx,
            res_m=res_m,
            res_w=res_w,
            res_t=res_t,
            sea_lat=sea_lat,
            sea_lon=sea_lon,
            state=state,
        )

        self.write_partial_cache(cache_key, payload)

        self.trigger_weather_activity(
            lat=lat,
            lon=lon,
            date_str=date_str,
            location_name=location_name,
            cache_key=cache_key,
        )

        return payload
