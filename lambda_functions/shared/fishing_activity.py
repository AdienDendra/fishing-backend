from __future__ import annotations


def time_to_minutes(value: str | None) -> int | None:
    """
    Convert HH:MM string into minutes after midnight.
    """
    if not value or not isinstance(value, str):
        return None

    try:
        hour, minute = value.split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return None


def event_time_to_minutes(value: str | None) -> int | None:
    """
    Convert backend event timestamp into minutes after midnight.

    Supports:
    - 2026-07-08T07:00
    - 07:00
    """
    if not value:
        return None

    text = str(value)

    if "T" in text:
        text = text.split("T", 1)[1]

    return time_to_minutes(text[:5])


def circular_distance_minutes(a: int, b: int) -> int:
    """
    Return shortest distance between two times on a 24-hour clock.
    """
    diff = abs(a - b)
    return min(diff, 1440 - diff)


def period_center_minutes(period: dict) -> int | None:
    """
    Estimate the center time of a period.

    Handles normal periods and midnight-crossing periods, e.g.
    23:28 - 01:28.
    """
    start = time_to_minutes(period.get("start"))
    end = time_to_minutes(period.get("end"))

    if start is None or end is None:
        return None

    if end < start:
        end += 1440

    return ((start + end) // 2) % 1440


def format_periods(periods: list[dict], emoji: str) -> str:
    """
    Convert period list into frontend-friendly text.
    """
    labels = [
        period.get("label")
        for period in periods
        if period.get("label")
    ]

    if not labels:
        return ""

    return f"{emoji} {' & '.join(labels)}"


def score_moon_phase(astronomy: dict) -> int:
    """
    Score moon phase contribution.

    New Moon and Full Moon are usually treated as stronger solunar periods.
    Quarter phases are still useful, but not peak.
    """
    phase = str(astronomy.get("moon_phase") or "").lower()
    illumination = astronomy.get("moon_illumination")

    if "new moon" in phase or "full moon" in phase:
        return 20

    if "quarter" in phase:
        return 14

    if isinstance(illumination, (int, float)):
        # Stronger around very dark or very bright moons.
        if illumination <= 15 or illumination >= 85:
            return 18
        if 35 <= illumination <= 65:
            return 14
        return 12

    return 10


def score_sun_overlap_for_period(period: dict, astronomy: dict, is_major: bool) -> int:
    """
    Score whether a solunar period overlaps sunrise or sunset.

    Fish often feed more actively around light transitions, so a major/minor
    period near sunrise/sunset receives a bonus.
    """
    center = period_center_minutes(period)
    sunrise = time_to_minutes(astronomy.get("sunrise"))
    sunset = time_to_minutes(astronomy.get("sunset"))

    if center is None:
        return 0

    candidates = [
        value
        for value in [sunrise, sunset]
        if value is not None
    ]

    if not candidates:
        return 0

    nearest = min(
        circular_distance_minutes(center, candidate)
        for candidate in candidates
    )

    if nearest <= 60:
        return 25 if is_major else 16

    if nearest <= 120:
        return 16 if is_major else 10

    return 0


def score_tide_alignment_for_period(period: dict, tide: dict, is_major: bool) -> int:
    """
    Score whether a high/low tide event is close to a solunar period.

    Uses estimated tide events from the backend. This is for fishing guidance,
    not official tide prediction.
    """
    center = period_center_minutes(period)
    if center is None:
        return 0

    events = tide.get("events") or tide.get("extremes") or []

    if not events:
        return 0

    event_minutes = [
        event_time_to_minutes(event.get("time"))
        for event in events
    ]
    event_minutes = [
        value
        for value in event_minutes
        if value is not None
    ]

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


def label_from_score(score: int) -> str:
    """
    Convert activity score into a user-facing label.
    """
    if score >= 85:
        return "Excellent"

    if score >= 70:
        return "Good"

    if score >= 50:
        return "Fair"

    if score >= 30:
        return "Poor"

    return "Low"


def build_period_candidates(astronomy: dict, tide: dict) -> list[dict]:
    """
    Build score candidates from major and minor solunar periods.
    """
    candidates = []

    for period in astronomy.get("major_periods") or []:
        sun_score = score_sun_overlap_for_period(
            period,
            astronomy,
            is_major=True,
        )
        tide_score = score_tide_alignment_for_period(
            period,
            tide,
            is_major=True,
        )

        candidates.append(
            {
                "type": "major",
                "period": period,
                "solunar_score": 35,
                "sun_score": sun_score,
                "tide_score": tide_score,
                "total": 35 + sun_score + tide_score,
            }
        )

    for period in astronomy.get("minor_periods") or []:
        sun_score = score_sun_overlap_for_period(
            period,
            astronomy,
            is_major=False,
        )
        tide_score = score_tide_alignment_for_period(
            period,
            tide,
            is_major=False,
        )

        candidates.append(
            {
                "type": "minor",
                "period": period,
                "solunar_score": 22,
                "sun_score": sun_score,
                "tide_score": tide_score,
                "total": 22 + sun_score + tide_score,
            }
        )

    return candidates


def build_reason_list(
    best_candidate: dict | None,
    moon_score: int,
    tide: dict,
    label: str,
) -> list[str]:
    """
    Build human-readable reasons for the activity score.
    """
    reasons = []

    if best_candidate:
        period_type = best_candidate["type"]
        period_label = best_candidate["period"].get("label")

        reasons.append(
            f"Best {period_type} solunar window is {period_label}."
        )

        if best_candidate["sun_score"] >= 16:
            reasons.append(
                "This window aligns well with sunrise or sunset."
            )

        if best_candidate["tide_score"] >= 10:
            reasons.append(
                "Estimated tide movement is favourable near this window."
            )

    if moon_score >= 18:
        reasons.append("Moon phase provides strong solunar support.")
    elif moon_score >= 14:
        reasons.append("Moon phase provides moderate solunar support.")
    else:
        reasons.append("Moon phase support is limited today.")

    if tide.get("is_official") is False:
        reasons.append(
            "Tide alignment uses estimated tide data, not an official tide table."
        )

    reasons.append(f"Overall fish activity is rated {label}.")

    return reasons


def build_fish_activity(
    astronomy: dict,
    tide: dict,
    weather: dict,
    marine: dict,
) -> dict:
    """
    Build deterministic fish activity guidance.

    Inputs:
    - astronomy: sunrise, sunset, major/minor solunar periods, moon phase
    - tide: estimated tide events from Open-Meteo sea level model
    - weather/marine: reserved for future refinement

    This function deliberately avoids Gemini. Gemini may explain the result,
    but the score itself should be deterministic and testable.
    """
    major_periods = astronomy.get("major_periods") or []
    minor_periods = astronomy.get("minor_periods") or []

    moon_score = score_moon_phase(astronomy)
    candidates = build_period_candidates(astronomy, tide)

    best_candidate = max(
        candidates,
        key=lambda candidate: candidate["total"],
        default=None,
    )

    if best_candidate:
        solunar_score = best_candidate["solunar_score"]
        sun_score = best_candidate["sun_score"]
        tide_score = best_candidate["tide_score"]
        best_window = best_candidate["period"].get("label")
    else:
        solunar_score = 0
        sun_score = 0
        tide_score = 0
        best_window = None

    score = min(
        100,
        round(solunar_score + moon_score + sun_score + tide_score),
    )

    label = label_from_score(score)

    major_emoji = "🐟🐟🔥" if score >= 70 else "🐟🐟"

    return {
        "major": format_periods(major_periods, major_emoji),
        "minor": format_periods(minor_periods, "🐟"),
        "low": "💤 Outside the Major and Minor periods",
        "score": score,
        "label": label,
        "best_window": best_window,
        "score_basis": {
            "solunar_period": solunar_score,
            "moon_phase": moon_score,
            "sunrise_sunset_overlap": sun_score,
            "tide_alignment": tide_score,
        },
        "reasons": build_reason_list(
            best_candidate=best_candidate,
            moon_score=moon_score,
            tide=tide,
            label=label,
        ),
    }