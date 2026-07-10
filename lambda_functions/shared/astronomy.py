from __future__ import annotations

import math

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from config import LUNAR_ANCHOR, LUNATION_CYCLE
except ImportError:
    # Fallback only. Used if Skyfield/de421.bsp is not available.
    LUNAR_ANCHOR = (2000, 1, 6, 18, 14, 0)
    LUNATION_CYCLE = 29.530588853


UTC = ZoneInfo("UTC")
EPHEMERIS_FILENAME = "de421.bsp"


def format_iso_time(value):
    """
    Convert Open-Meteo local ISO timestamp to HH:MM.
    Example: 2026-07-07T07:01 -> 07:01
    """
    if not value:
        return None

    text = str(value)

    if "T" in text and len(text) >= 16:
        return text[11:16]

    return text[:5] if len(text) >= 5 else text


def time_to_minutes(value: str | None) -> int | None:
    """
    Convert HH:MM into minutes after midnight.
    """
    if not value:
        return None

    try:
        hour, minute = str(value).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return None


def minutes_to_time(value: int) -> str:
    """
    Convert minutes after midnight into HH:MM.
    Handles values outside 0..1439 by wrapping around 24 hours.
    """
    value = value % 1440
    hour = value // 60
    minute = value % 60

    return f"{hour:02d}:{minute:02d}"


def format_hour_float(hour_value):
    """
    Convert decimal hour to HH:MM.

    Kept for fallback calculation only.
    """
    hour_value = hour_value % 24
    hour = int(hour_value)
    minute = int(round((hour_value - hour) * 60))

    if minute == 60:
        hour = (hour + 1) % 24
        minute = 0

    return f"{hour:02d}:{minute:02d}"


def format_period_from_center(center_time: str | None, window_minutes: int = 60):
    """
    Build a fishing activity period around a center time.

    Example:
    center_time=07:00, window_minutes=60
    -> 06:00 - 08:00
    """
    center = time_to_minutes(center_time)

    if center is None:
        return None

    start = minutes_to_time(center - window_minutes)
    end = minutes_to_time(center + window_minutes)

    return {
        "start": start,
        "end": end,
        "label": f"{start} - {end}",
    }


def format_period(center_hour, window_hours=1):
    """
    Build a fishing activity period around a decimal-hour center.

    Used only by the fallback lunar estimate.
    """
    center_minutes = int(round((center_hour % 24) * 60))
    window_minutes = int(window_hours * 60)

    start = minutes_to_time(center_minutes - window_minutes)
    end = minutes_to_time(center_minutes + window_minutes)

    return {
        "start": start,
        "end": end,
        "label": f"{start} - {end}",
    }


def moon_phase_label_from_degrees(phase_degrees: float) -> str:
    """
    Convert Skyfield moon phase angle into a human-readable label.

    Skyfield convention:
    - 0 degrees   = New Moon
    - 90 degrees  = First Quarter
    - 180 degrees = Full Moon
    - 270 degrees = Last Quarter
    """
    degrees = phase_degrees % 360

    if degrees < 22.5 or degrees >= 337.5:
        return "New Moon"

    if degrees < 67.5:
        return "Waxing Crescent"

    if degrees < 112.5:
        return "First Quarter"

    if degrees < 157.5:
        return "Waxing Gibbous"

    if degrees < 202.5:
        return "Full Moon"

    if degrees < 247.5:
        return "Waning Gibbous"

    if degrees < 292.5:
        return "Last Quarter"

    return "Waning Crescent"


def moon_phase_label(phase_fraction):
    """
    Convert moon phase fraction into a human-readable phase label.

    Used only by the fallback lunar estimate.
    """
    phase_points = [
        (0.03, "New Moon"),
        (0.22, "Waxing Crescent"),
        (0.28, "First Quarter"),
        (0.47, "Waxing Gibbous"),
        (0.53, "Full Moon"),
        (0.72, "Waning Gibbous"),
        (0.78, "Last Quarter"),
        (0.97, "Waning Crescent"),
        (1.00, "New Moon"),
    ]

    for threshold, label in phase_points:
        if phase_fraction <= threshold:
            return label

    return "New Moon"


def nearest_minute(dt: datetime) -> datetime:
    """
    Round datetime to nearest minute.

    This mirrors Skyfield documentation guidance when formatting Python
    datetime objects rather than Skyfield's utc_strftime().
    """
    return (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)


def skyfield_time_to_local_hhmm(skyfield_time, timezone_name: str) -> str:
    """
    Convert a Skyfield Time object into local HH:MM.
    """
    timezone_local = ZoneInfo(timezone_name)

    dt_utc = skyfield_time.utc_datetime()

    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    dt_local = dt_utc.astimezone(timezone_local)
    dt_local = nearest_minute(dt_local)

    return dt_local.strftime("%H:%M")


def skyfield_time_to_local_date(skyfield_time, timezone_name: str) -> str:
    """
    Convert a Skyfield Time object into local YYYY-MM-DD.
    """
    timezone_local = ZoneInfo(timezone_name)

    dt_utc = skyfield_time.utc_datetime()

    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    return dt_utc.astimezone(timezone_local).date().isoformat()


def load_skyfield_runtime():
    """
    Load Skyfield lazily.

    Important for AWS Lambda:
    - This file is copied into multiple Lambda function folders.
    - Only weather_activity needs Skyfield.
    - Lazy import prevents unrelated Lambda functions from failing if they do not
      include the Skyfield dependency package.
    """
    from skyfield import almanac
    from skyfield.api import load, load_file, wgs84

    ephemeris_path = Path(__file__).resolve().with_name(EPHEMERIS_FILENAME)

    if not ephemeris_path.exists():
        raise FileNotFoundError(
            f"{EPHEMERIS_FILENAME} not found next to astronomy.py. "
            "Download it into lambda_functions/weather_activity/ before deploy."
        )

    timescale = load.timescale()
    ephemeris = load_file(str(ephemeris_path))

    return almanac, timescale, ephemeris, wgs84


def build_local_day_window(date_str: str, timezone_name: str, timescale):
    """
    Build Skyfield UTC search window covering one local calendar day.
    """
    timezone_local = ZoneInfo(timezone_name)

    start_local = datetime.fromisoformat(date_str).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=timezone_local,
    )
    end_local = start_local + timedelta(days=1)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    return (
        timescale.from_datetime(start_utc),
        timescale.from_datetime(end_utc),
        start_local,
    )


def first_valid_local_event(times, flags, date_str: str, timezone_name: str):
    """
    Pick the first valid rising/setting event that belongs to the requested
    local calendar day.
    """
    for event_time, is_valid in zip(times, flags):
        if not bool(is_valid):
            continue

        local_date = skyfield_time_to_local_date(event_time, timezone_name)

        if local_date == date_str:
            return skyfield_time_to_local_hhmm(event_time, timezone_name)

    return None


def get_skyfield_lunar_info(
    date_str: str,
    lat: float,
    lon: float,
    timezone_name: str,
) -> dict:
    """
    Build Moon and solunar data using Skyfield.

    Solunar convention used by this project:
    - Major periods: around moon meridian transit and antimeridian transit.
    - Minor periods: around moonrise and moonset.
    """
    almanac, timescale, ephemeris, wgs84 = load_skyfield_runtime()

    moon = ephemeris["Moon"]
    earth = ephemeris["Earth"]

    location = wgs84.latlon(lat, lon)
    observer = earth + location

    t0, t1, start_local = build_local_day_window(
        date_str,
        timezone_name,
        timescale,
    )

    # Moonrise / moonset.
    moonrise_times, moonrise_flags = almanac.find_risings(
        observer,
        moon,
        t0,
        t1,
    )
    moonset_times, moonset_flags = almanac.find_settings(
        observer,
        moon,
        t0,
        t1,
    )

    moonrise = first_valid_local_event(
        moonrise_times,
        moonrise_flags,
        date_str,
        timezone_name,
    )
    moonset = first_valid_local_event(
        moonset_times,
        moonset_flags,
        date_str,
        timezone_name,
    )

    # Moon meridian transit / antimeridian transit.
    transit_function = almanac.meridian_transits(
        ephemeris,
        moon,
        location,
    )
    transit_times, transit_types = almanac.find_discrete(
        t0,
        t1,
        transit_function,
    )

    moon_transit = None
    moon_antitransit = None

    for event_time, event_type in zip(transit_times, transit_types):
        if skyfield_time_to_local_date(event_time, timezone_name) != date_str:
            continue

        event_label = almanac.MERIDIAN_TRANSITS[int(event_type)]
        event_hhmm = skyfield_time_to_local_hhmm(event_time, timezone_name)

        if event_label == "Meridian transit":
            moon_transit = event_hhmm
        elif event_label == "Antimeridian transit":
            moon_antitransit = event_hhmm

    # Moon phase and illumination at local noon.
    local_noon = start_local + timedelta(hours=12)
    local_noon_utc = local_noon.astimezone(timezone.utc)
    noon_time = timescale.from_datetime(local_noon_utc)

    phase_angle = almanac.moon_phase(ephemeris, noon_time).degrees % 360
    phase_fraction = phase_angle / 360

    illumination = round(
        ((1 - math.cos(math.radians(phase_angle))) / 2) * 100
    )

    major_periods = [
        period
        for period in [
            format_period_from_center(moon_transit),
            format_period_from_center(moon_antitransit),
        ]
        if period
    ]

    minor_periods = [
        period
        for period in [
            format_period_from_center(moonrise),
            format_period_from_center(moonset),
        ]
        if period
    ]

    return {
        "moonrise": moonrise,
        "moonset": moonset,
        "moon_transit": moon_transit,
        "moon_antitransit": moon_antitransit,
        "moon_phase": moon_phase_label_from_degrees(phase_angle),
        "moon_phase_fraction": round(phase_fraction, 3),
        "moon_illumination": illumination,
        "major_periods": major_periods,
        "minor_periods": minor_periods,
        "calculation_method": "skyfield_de421",
        "ephemeris": EPHEMERIS_FILENAME,
    }


def get_lunar_info_fallback(date_str, lon, timezone_name):
    """
    Lightweight fallback lunar estimate.

    This is only used if Skyfield or de421.bsp is unavailable.
    It keeps the API resilient instead of breaking the weather_activity Lambda.
    """
    timezone_local = ZoneInfo(timezone_name)

    local_noon = datetime.fromisoformat(date_str).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=timezone_local,
    )

    utc_noon = local_noon.astimezone(UTC)
    anchor_utc = datetime(*LUNAR_ANCHOR, tzinfo=UTC)

    days_since_new_moon = (utc_noon - anchor_utc).total_seconds() / 86400
    phase_fraction = (days_since_new_moon / LUNATION_CYCLE) % 1
    days_in_cycle = days_since_new_moon % LUNATION_CYCLE

    illumination = round(
        ((1 - math.cos(2 * math.pi * phase_fraction)) / 2) * 100
    )

    local_offset_hours = local_noon.utcoffset().total_seconds() / 3600
    location_correction = lon / 15.0

    transit_base = (days_in_cycle / LUNATION_CYCLE) * 24
    moon_transit_float = (
        12 + transit_base - location_correction + local_offset_hours
    ) % 24
    moon_antitransit_float = (moon_transit_float + 12) % 24

    minor_1 = (moon_transit_float - 6) % 24
    minor_2 = (moon_transit_float + 6) % 24

    moon_transit = format_hour_float(moon_transit_float)
    moon_antitransit = format_hour_float(moon_antitransit_float)

    return {
        "moonrise": None,
        "moonset": None,
        "moon_phase": moon_phase_label(phase_fraction),
        "moon_phase_fraction": round(phase_fraction, 3),
        "moon_illumination": illumination,
        "moon_transit": moon_transit,
        "moon_antitransit": moon_antitransit,
        "major_periods": [
            format_period(moon_transit_float),
            format_period(moon_antitransit_float),
        ],
        "minor_periods": [
            format_period(minor_1),
            format_period(minor_2),
        ],
        "calculation_method": "fallback_lunar_anchor_estimate",
        "ephemeris": None,
    }


def get_astronomy_data(
    date_str: str,
    lat: float,
    lon: float,
    timezone_name: str = "Australia/Sydney",
    daily: dict | None = None,
) -> dict:
    """
    Build astronomy data for one forecast date.

    Data sources:
    - Sunrise/sunset: Open-Meteo daily forecast.
    - Moonrise/moonset/transit/phase: Skyfield + de421.bsp.
    - Fallback: lightweight lunar-cycle estimate if Skyfield is unavailable.
    """
    daily = daily or {}

    sunrise = format_iso_time(daily.get("sunrise"))
    sunset = format_iso_time(daily.get("sunset"))

    fallback_reason = None

    try:
        lunar = get_skyfield_lunar_info(
            date_str=date_str,
            lat=lat,
            lon=lon,
            timezone_name=timezone_name,
        )
    except Exception as exc:
        fallback_reason = str(exc)
        lunar = get_lunar_info_fallback(
            date_str=date_str,
            lon=lon,
            timezone_name=timezone_name,
        )

    result = {
        "sunrise": sunrise,
        "sunset": sunset,
        "moonrise": lunar["moonrise"],
        "moonset": lunar["moonset"],
        "moon_transit": lunar["moon_transit"],
        "moon_antitransit": lunar["moon_antitransit"],
        "moon_phase": lunar["moon_phase"],
        "moon_phase_fraction": lunar["moon_phase_fraction"],
        "moon_illumination": lunar["moon_illumination"],
        "major_periods": lunar["major_periods"],
        "minor_periods": lunar["minor_periods"],
        "timezone": timezone_name,
        "daylight_duration": daily.get("daylight_duration"),
        "calculation_method": (
            f"open_meteo_sun_times_{lunar['calculation_method']}"
        ),
        "ephemeris": lunar.get("ephemeris"),
    }

    if fallback_reason:
        result["fallback_reason"] = fallback_reason

    return result