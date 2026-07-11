"""Deterministic daily Fish Activity scoring.

Each forecast date is evaluated per Major and Minor fishing window.
The engine selects the strongest window using solunar timing, Moon phase,
sunrise/sunset proximity, estimated tide timing, atmospheric pressure,
and local hourly wind conditions. Gemini only explains this result.

"""

from __future__ import annotations


# Score weights intentionally total 100 points.
MAX_SOLUNAR_SCORE = 30
MAX_MOON_SCORE = 15
MAX_SUN_SCORE = 20
MAX_TIDE_SCORE = 15
MAX_PRESSURE_SCORE = 12
MAX_WIND_SCORE = 8


def time_to_minutes(value: str | None) -> int | None:
    if not value or not isinstance(value, str):
        return None

    try:
        hour, minute = value.split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return None


def event_time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None

    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[1]

    return time_to_minutes(text[:5])


def circular_distance_minutes(a: int, b: int) -> int:
    difference = abs(a - b)
    return min(difference, 1440 - difference)


def signed_circular_offset_minutes(value: int, center: int) -> int:
    return ((value - center + 720) % 1440) - 720


def period_center_minutes(period: dict) -> int | None:
    start = time_to_minutes(period.get("start"))
    end = time_to_minutes(period.get("end"))

    if start is None or end is None:
        return None

    if end < start:
        end += 1440

    return ((start + end) // 2) % 1440


def period_radius_minutes(period: dict) -> int | None:
    start = time_to_minutes(period.get("start"))
    end = time_to_minutes(period.get("end"))

    if start is None or end is None:
        return None

    if end < start:
        end += 1440

    return max(0, (end - start) // 2)


def format_periods(periods: list[dict], emoji: str) -> str:
    labels = [
        period.get("label")
        for period in periods
        if period.get("label")
    ]

    if not labels:
        return ""

    return f"{emoji} {' & '.join(labels)}"


def safe_number(value) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    return None


def average(values: list[float]) -> float | None:
    if not values:
        return None

    return sum(values) / len(values)


def get_hourly_points(weather: dict, field_name: str) -> list[dict]:
    times = weather.get("time") or []
    values = weather.get(field_name) or []
    points = []

    for timestamp, raw_value in zip(times, values):
        minute = event_time_to_minutes(timestamp)
        value = safe_number(raw_value)

        if minute is None or value is None:
            continue

        points.append({"minute": minute, "value": value})

    return points


def get_period_values(
    weather: dict,
    field_name: str,
    period: dict,
) -> list[float]:
    center = period_center_minutes(period)
    radius = period_radius_minutes(period)

    if center is None or radius is None:
        return []

    maximum_distance = radius + 30

    return [
        point["value"]
        for point in get_hourly_points(weather, field_name)
        if circular_distance_minutes(point["minute"], center)
        <= maximum_distance
    ]


def get_pressure_trend_points(
    weather: dict,
    period: dict,
) -> list[dict]:
    center = period_center_minutes(period)

    if center is None:
        return []

    points = []

    for point in get_hourly_points(weather, "pressure_msl"):
        offset = signed_circular_offset_minutes(
            point["minute"],
            center,
        )

        if -180 <= offset <= 60:
            points.append({"offset": offset, "value": point["value"]})

    return sorted(points, key=lambda point: point["offset"])


def score_moon_phase(astronomy: dict) -> int:
    phase = str(astronomy.get("moon_phase") or "").lower()
    illumination = astronomy.get("moon_illumination")

    if "new moon" in phase or "full moon" in phase:
        return 15

    if "quarter" in phase:
        return 11

    if isinstance(illumination, (int, float)):
        if illumination <= 15 or illumination >= 85:
            return 14
        if 35 <= illumination <= 65:
            return 10
        return 9

    return 8


def score_sun_overlap_for_period(
    period: dict,
    astronomy: dict,
    is_major: bool,
) -> int:
    center = period_center_minutes(period)
    sunrise = time_to_minutes(astronomy.get("sunrise"))
    sunset = time_to_minutes(astronomy.get("sunset"))

    if center is None:
        return 0

    sun_events = [
        value
        for value in [sunrise, sunset]
        if value is not None
    ]

    if not sun_events:
        return 0

    nearest = min(
        circular_distance_minutes(center, event_minute)
        for event_minute in sun_events
    )

    if nearest <= 60:
        return 20 if is_major else 12
    if nearest <= 120:
        return 12 if is_major else 8

    return 0


def score_tide_alignment_for_period(
    period: dict,
    tide: dict,
    is_major: bool,
) -> int:
    center = period_center_minutes(period)

    if center is None:
        return 0

    events = tide.get("events") or tide.get("extremes") or []

    event_minutes = [
        event_time_to_minutes(event.get("time"))
        for event in events
        if isinstance(event, dict)
    ]
    event_minutes = [value for value in event_minutes if value is not None]

    if not event_minutes:
        return 0

    nearest = min(
        circular_distance_minutes(center, event_minute)
        for event_minute in event_minutes
    )

    if nearest <= 60:
        return 15 if is_major else 10
    if nearest <= 120:
        return 10 if is_major else 6
    if nearest <= 180:
        return 6 if is_major else 4

    return 2


def score_pressure_for_period(
    period: dict,
    weather: dict,
) -> dict:
    """Score local barometric conditions for one fishing window.

    The thresholds are an explicit Sydney shore-fishing empirical profile,
    not a universal biological rule. Absolute pressure and short-term
    tendency are scored separately so a high but rapidly falling system does
    not receive the same result as high, stable pressure.
    """
    period_values = get_period_values(weather, "pressure_msl", period)
    average_pressure = average(period_values)

    # Missing data must not receive neutral or bonus points.
    if average_pressure is None:
        return {
            "score": 0,
            "average_hpa": None,
            "level": "unknown",
            "level_score": 0,
            "trend_hpa": None,
            "trend": "unknown",
            "trend_score": 0,
            "samples": 0,
        }

    # Local empirical pressure bands for Sydney shore fishing.
    if average_pressure >= 1020:
        level_score = 6
        level_label = "high"
    elif average_pressure >= 1016:
        level_score = 5
        level_label = "moderately_high"
    elif average_pressure >= 1012:
        level_score = 3
        level_label = "normal"
    elif average_pressure >= 1008:
        level_score = 2
        level_label = "moderately_low"
    else:
        level_score = 1
        level_label = "low"

    trend_points = get_pressure_trend_points(weather, period)

    if len(trend_points) >= 2:
        raw_pressure_trend = (
            trend_points[-1]["value"]
            - trend_points[0]["value"]
        )
        pressure_trend = round(raw_pressure_trend, 1)
    else:
        pressure_trend = None

    if pressure_trend is None:
        trend_score = 0
        trend_label = "unknown"
    elif 0.3 < pressure_trend <= 2.5:
        trend_score = 6
        trend_label = "gently_rising"
    elif -0.3 <= pressure_trend <= 0.3:
        trend_score = 5
        trend_label = "stable"
    elif pressure_trend > 2.5:
        trend_score = 3
        trend_label = "rising_quickly"
    elif pressure_trend >= -1.5:
        trend_score = 3
        trend_label = "gently_falling"
    else:
        trend_score = 0
        trend_label = "falling_quickly"

    return {
        "score": min(MAX_PRESSURE_SCORE, level_score + trend_score),
        "average_hpa": round(average_pressure, 1),
        "level": level_label,
        "level_score": level_score,
        "trend_hpa": pressure_trend,
        "trend": trend_label,
        "trend_score": trend_score,
        "samples": len(period_values),
    }


def score_wind_for_period(
    period: dict,
    weather: dict,
) -> dict:
    """Score wind using a local 8-12 km/h empirical sweet spot.

    Gusts are applied as a penalty rather than an independent bonus. This
    prevents strong gusts from being hidden by a favourable average speed.
    """
    wind_values = get_period_values(weather, "wind_speed_10m", period)
    gust_values = get_period_values(weather, "wind_gusts_10m", period)

    average_wind = average(wind_values)
    average_gust = average(gust_values)

    if average_wind is None:
        return {
            "score": 0,
            "condition": "unknown",
            "speed_score": 0,
            "gust_penalty": 0,
            "average_speed_kmh": None,
            "average_gust_kmh": (
                round(average_gust, 1)
                if average_gust is not None
                else None
            ),
            "samples": 0,
        }

    if 8 <= average_wind <= 12:
        speed_score = 8
        condition_label = "sweet_spot"
    elif 5 <= average_wind < 8:
        speed_score = 7
        condition_label = "light"
    elif 12 < average_wind <= 16:
        speed_score = 6
        condition_label = "moderate"
    elif 0 <= average_wind < 5:
        speed_score = 5
        condition_label = "very_light"
    elif 16 < average_wind <= 22:
        speed_score = 4
        condition_label = "fresh"
    elif 22 < average_wind <= 30:
        speed_score = 2
        condition_label = "strong"
    else:
        speed_score = 0
        condition_label = "very_strong"

    if average_gust is None or average_gust <= 20:
        gust_penalty = 0
    elif average_gust <= 30:
        gust_penalty = 1
    elif average_gust <= 40:
        gust_penalty = 2
    else:
        gust_penalty = 4

    final_score = max(0, min(MAX_WIND_SCORE, speed_score - gust_penalty))

    return {
        "score": final_score,
        "condition": condition_label,
        "speed_score": speed_score,
        "gust_penalty": gust_penalty,
        "average_speed_kmh": round(average_wind, 1),
        "average_gust_kmh": (
            round(average_gust, 1)
            if average_gust is not None
            else None
        ),
        "samples": len(wind_values),
    }


def build_period_candidates(
    astronomy: dict,
    tide: dict,
    weather: dict,
) -> list[dict]:
    candidates = []

    period_groups = [
        ("major", astronomy.get("major_periods") or [], 30, True),
        ("minor", astronomy.get("minor_periods") or [], 18, False),
    ]

    for period_type, periods, solunar_score, is_major in period_groups:
        for period in periods:
            sun_score = score_sun_overlap_for_period(
                period,
                astronomy,
                is_major=is_major,
            )
            tide_score = score_tide_alignment_for_period(
                period,
                tide,
                is_major=is_major,
            )
            pressure = score_pressure_for_period(period, weather)
            wind = score_wind_for_period(period, weather)

            candidate_total = (
                solunar_score
                + sun_score
                + tide_score
                + pressure["score"]
                + wind["score"]
            )

            candidates.append(
                {
                    "type": period_type,
                    "period": period,
                    "solunar_score": solunar_score,
                    "sun_score": sun_score,
                    "tide_score": tide_score,
                    "pressure_score": pressure["score"],
                    "wind_score": wind["score"],
                    "pressure": pressure,
                    "wind": wind,
                    "total_without_moon": candidate_total,
                }
            )

    return candidates


def label_from_score(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    if score >= 30:
        return "Poor"

    return "Low"


def build_reason_list(
    best_candidate: dict | None,
    moon_score: int,
    tide: dict,
    label: str,
) -> list[str]:
    reasons = []

    if best_candidate:
        period_type = best_candidate["type"]
        period_label = best_candidate["period"].get("label")

        reasons.append(
            f"Best {period_type} solunar window is {period_label}."
        )

        if best_candidate["sun_score"] >= 12:
            reasons.append(
                "This window aligns well with sunrise or sunset."
            )

        if best_candidate["tide_score"] >= 10:
            reasons.append(
                "An estimated tide event occurs near this window."
            )

        pressure = best_candidate["pressure"]
        pressure_level = pressure.get("level")
        pressure_trend = pressure.get("trend")
        average_pressure = pressure.get("average_hpa")

        if pressure_trend == "gently_rising":
            reasons.append(
                f"Pressure is {pressure_level} and gently rising "
                f"around the window ({average_pressure} hPa average)."
            )
        elif pressure_trend == "stable":
            reasons.append(
                f"Pressure is {pressure_level} and stable around the "
                f"window ({average_pressure} hPa average)."
            )
        elif pressure_trend == "rising_quickly":
            reasons.append(
                "Pressure is rising quickly, suggesting changing conditions."
            )
        elif pressure_trend == "gently_falling":
            reasons.append(
                "Pressure is gently falling around this window."
            )
        elif pressure_trend == "falling_quickly":
            reasons.append(
                "Pressure is falling quickly around this window."
            )

        wind = best_candidate["wind"]
        average_wind = wind.get("average_speed_kmh")
        average_gust = wind.get("average_gust_kmh")

        if average_wind is not None:
            gust_text = (
                f" with gusts around {average_gust} km/h"
                if average_gust is not None
                else ""
            )
            wind_condition = wind.get("condition")

            if wind_condition == "sweet_spot":
                reasons.append(
                    f"Average wind is {average_wind} km/h, inside the "
                    f"local 8-12 km/h sweet spot{gust_text}."
                )
            else:
                reasons.append(
                    f"Average wind is {average_wind} km/h{gust_text}."
                )

    if moon_score >= 14:
        reasons.append("Moon phase provides strong solunar support.")
    elif moon_score >= 10:
        reasons.append("Moon phase provides moderate solunar support.")
    else:
        reasons.append("Moon phase support is limited today.")

    if tide.get("is_official") is False:
        reasons.append(
            "Tide timing uses estimated data, not an official tide table."
        )

    reasons.append(f"Overall fish activity is rated {label}.")

    return reasons


def serialize_candidate(candidate: dict, moon_score: int) -> dict:
    total_score = min(
        100,
        round(candidate["total_without_moon"] + moon_score),
    )

    return {
        "type": candidate["type"],
        "window": candidate["period"].get("label"),
        "score": total_score,
        "score_basis": {
            "solunar_period": candidate["solunar_score"],
            "moon_phase": moon_score,
            "sunrise_sunset_overlap": candidate["sun_score"],
            "tide_alignment": candidate["tide_score"],
            "pressure": candidate["pressure_score"],
            "wind": candidate["wind_score"],
        },
        "conditions": {
            "average_pressure_hpa": candidate["pressure"].get("average_hpa"),
            "pressure_level": candidate["pressure"].get("level"),
            "pressure_level_score": candidate["pressure"].get(
                "level_score"
            ),
            "pressure_trend_hpa": candidate["pressure"].get("trend_hpa"),
            "pressure_trend": candidate["pressure"].get("trend"),
            "pressure_trend_score": candidate["pressure"].get(
                "trend_score"
            ),
            "average_wind_kmh": candidate["wind"].get("average_speed_kmh"),
            "wind_condition": candidate["wind"].get("condition"),
            "wind_speed_score": candidate["wind"].get("speed_score"),
            "average_wind_gust_kmh": candidate["wind"].get(
                "average_gust_kmh"
            ),
            "wind_gust_penalty": candidate["wind"].get("gust_penalty"),
        },
    }


def build_fish_activity(
    astronomy: dict,
    tide: dict,
    weather: dict,
    marine: dict,
) -> dict:
    del marine

    major_periods = astronomy.get("major_periods") or []
    minor_periods = astronomy.get("minor_periods") or []

    moon_score = score_moon_phase(astronomy)
    candidates = build_period_candidates(astronomy, tide, weather)

    best_candidate = max(
        candidates,
        key=lambda candidate: candidate["total_without_moon"],
        default=None,
    )

    if best_candidate:
        solunar_score = best_candidate["solunar_score"]
        sun_score = best_candidate["sun_score"]
        tide_score = best_candidate["tide_score"]
        pressure_score = best_candidate["pressure_score"]
        wind_score = best_candidate["wind_score"]
        best_window = best_candidate["period"].get("label")
        best_window_type = best_candidate["type"]

        score = min(
            100,
            round(best_candidate["total_without_moon"] + moon_score),
        )

        conditions_at_best_window = {
            "average_pressure_hpa": best_candidate["pressure"].get(
                "average_hpa"
            ),
            "pressure_level": best_candidate["pressure"].get("level"),
            "pressure_level_score": best_candidate["pressure"].get(
                "level_score"
            ),
            "pressure_trend_hpa": best_candidate["pressure"].get(
                "trend_hpa"
            ),
            "pressure_trend": best_candidate["pressure"].get("trend"),
            "pressure_trend_score": best_candidate["pressure"].get(
                "trend_score"
            ),
            "average_wind_kmh": best_candidate["wind"].get(
                "average_speed_kmh"
            ),
            "wind_condition": best_candidate["wind"].get("condition"),
            "wind_speed_score": best_candidate["wind"].get(
                "speed_score"
            ),
            "average_wind_gust_kmh": best_candidate["wind"].get(
                "average_gust_kmh"
            ),
            "wind_gust_penalty": best_candidate["wind"].get(
                "gust_penalty"
            ),
        }
    else:
        solunar_score = 0
        sun_score = 0
        tide_score = 0
        pressure_score = 0
        wind_score = 0
        best_window = None
        best_window_type = None
        score = moon_score
        conditions_at_best_window = {
            "average_pressure_hpa": None,
            "pressure_level": "unknown",
            "pressure_level_score": 0,
            "pressure_trend_hpa": None,
            "pressure_trend": "unknown",
            "pressure_trend_score": 0,
            "average_wind_kmh": None,
            "wind_condition": "unknown",
            "wind_speed_score": 0,
            "average_wind_gust_kmh": None,
            "wind_gust_penalty": 0,
        }

    label = label_from_score(score)
    major_emoji = "🐟🐟🔥" if score >= 70 else "🐟🐟"

    return {
        "score_version": "2.1",
        "scoring_profile": "sydney_shore_empirical_v1",
        "method_note": (
            "Pressure and wind thresholds are local empirical heuristics, "
            "not catch guarantees."
        ),
        "major": format_periods(major_periods, major_emoji),
        "minor": format_periods(minor_periods, "🐟"),
        "low": "💤 Outside the Major and Minor periods",
        "score": score,
        "label": label,
        "best_window": best_window,
        "best_window_type": best_window_type,
        "score_basis": {
            "solunar_period": solunar_score,
            "moon_phase": moon_score,
            "sunrise_sunset_overlap": sun_score,
            "tide_alignment": tide_score,
            "pressure": pressure_score,
            "wind": wind_score,
        },
        "score_maximums": {
            "solunar_period": MAX_SOLUNAR_SCORE,
            "moon_phase": MAX_MOON_SCORE,
            "sunrise_sunset_overlap": MAX_SUN_SCORE,
            "tide_alignment": MAX_TIDE_SCORE,
            "pressure": MAX_PRESSURE_SCORE,
            "wind": MAX_WIND_SCORE,
        },
        "conditions_at_best_window": conditions_at_best_window,
        "evaluated_windows": [
            serialize_candidate(candidate, moon_score)
            for candidate in candidates
        ],
        "reasons": build_reason_list(
            best_candidate=best_candidate,
            moon_score=moon_score,
            tide=tide,
            label=label,
        ),
    }
