import math

from datetime import datetime
from zoneinfo import ZoneInfo

from config import LUNAR_ANCHOR, LUNATION_CYCLE


UTC = ZoneInfo("UTC")


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


def format_hour_float(hour_value):
    """
    Convert decimal hour to HH:MM.
    """
    hour_value = hour_value % 24
    hour = int(hour_value)
    minute = int(round((hour_value - hour) * 60))

    if minute == 60:
        hour = (hour + 1) % 24
        minute = 0

    return f"{hour:02d}:{minute:02d}"


def format_period(center_hour, window_hours=1):
    """
    Build a fishing activity period around a center hour.
    window_hours=1 means 2-hour total window.
    """
    start = format_hour_float(center_hour - window_hours)
    end = format_hour_float(center_hour + window_hours)

    return {
        "start": start,
        "end": end,
        "label": f"{start} - {end}",
    }


def moon_phase_label(phase_fraction):
    """
    Convert moon phase fraction into a human-readable phase label.

    0.00 = New Moon
    0.25 = First Quarter
    0.50 = Full Moon
    0.75 = Last Quarter
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


def get_lunar_info(date_str, lon, timezone_name):
    """
    Lightweight lunar estimate using a known new moon anchor.

    This is good enough for portfolio solunar scoring, but it is not a
    precision astronomy engine. Later, this can be replaced with Skyfield.
    """
    timezone = ZoneInfo(timezone_name)
    local_noon = datetime.fromisoformat(date_str).replace(
        hour=12,
        minute=0,
        second=0,
        tzinfo=timezone,
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

    # Approximation based on lunar cycle position and longitude.
    transit_base = (days_in_cycle / LUNATION_CYCLE) * 24
    moon_transit = (12 + transit_base - location_correction + local_offset_hours) % 24
    moon_antitransit = (moon_transit + 12) % 24

    minor_1 = (moon_transit - 6) % 24
    minor_2 = (moon_transit + 6) % 24

    return {
        "moon_phase": moon_phase_label(phase_fraction),
        "moon_phase_fraction": round(phase_fraction, 3),
        "moon_illumination": illumination,
        "moon_transit": format_hour_float(moon_transit),
        "moon_antitransit": format_hour_float(moon_antitransit),
        "major_periods": [
            format_period(moon_transit),
            format_period(moon_antitransit),
        ],
        "minor_periods": [
            format_period(minor_1),
            format_period(minor_2),
        ],
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

    Sunrise/sunset come from Open-Meteo daily forecast.
    Moon/solunar values are lightweight deterministic estimates.
    """
    daily = daily or {}
    lunar = get_lunar_info(date_str, lon, timezone_name)

    sunrise = format_iso_time(daily.get("sunrise"))
    sunset = format_iso_time(daily.get("sunset"))

    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "moonrise": None,
        "moonset": None,
        "moon_transit": lunar["moon_transit"],
        "moon_antitransit": lunar["moon_antitransit"],
        "moon_phase": lunar["moon_phase"],
        "moon_phase_fraction": lunar["moon_phase_fraction"],
        "moon_illumination": lunar["moon_illumination"],
        "major_periods": lunar["major_periods"],
        "minor_periods": lunar["minor_periods"],
        "timezone": timezone_name,
        "daylight_duration": daily.get("daylight_duration"),
        "calculation_method": "open_meteo_sun_times_lunar_anchor_estimate",
    }