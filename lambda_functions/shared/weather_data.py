import math
import requests

from datetime import datetime, timedelta
from config import LUNAR_ANCHOR, LUNATION_CYCLE

LUNAR_ANCHOR = datetime(*LUNAR_ANCHOR)


def get_local_tide_display_offset(lat, lon):
    """
    Return local display datum offset for known calibrated fishing spots.

    Open-Meteo sea_level_height_msl is relative to mean sea level and can be
    negative. For known fishing locations, we apply a local display offset so
    frontend tide values resemble common angler-facing tide charts.

    The Leap / Kurnell calibration was compared against WillyWeather samples:
    - 2026-06-30
    - 2026-07-01
    """
    calibrated_locations = [
        {
            "name": "The Leap, Kurnell",
            "lat": -34.0049,
            "lon": 151.2288,
            "offset_m": 1.02,
            "radius_deg": 0.02,
        }
    ]

    for location in calibrated_locations:
        if (
            abs(lat - location["lat"]) <= location["radius_deg"]
            and abs(lon - location["lon"]) <= location["radius_deg"]
        ):
            return {
                "method": "local_calibrated_offset",
                "offset_m": location["offset_m"],
                "calibrated_location": location["name"],
                "confidence": "medium_high",
            }

    return None

def normalize_estimated_tide_heights(raw_heights, lat, lon):
    """
    Add display_height to Open-Meteo sea_level_height_msl values.

    For known locations, use a calibrated local offset.
    For unknown locations, fallback to a 7-day minimum-window pseudo datum.
    """
    calibrated_offset = get_local_tide_display_offset(lat, lon)

    if calibrated_offset:
        datum_offset = calibrated_offset["offset_m"]
        datum_method = calibrated_offset["method"]
        calibrated_location = calibrated_offset["calibrated_location"]
        confidence = calibrated_offset["confidence"]
    else:
        valid_heights = [
            item["height_msl"]
            for item in raw_heights
            if item.get("height_msl") is not None
        ]

        min_height = min(valid_heights) if valid_heights else 0.0
        datum_offset = abs(min_height) if min_height < 0 else 0.0
        datum_offset = round(datum_offset, 2)

        datum_method = "minimum_7_day_forecast_window"
        calibrated_location = None
        confidence = "medium_low"

    normalized = []

    for item in raw_heights:
        height_msl = item.get("height_msl")

        if height_msl is None:
            display_height = None
        else:
            display_height = round(height_msl + datum_offset, 2)

        normalized.append(
            {
                "time": item["time"],
                "height_msl": height_msl,
                "display_height": display_height,
            }
        )

    metadata = {
        "display_datum_method": datum_method,
        "display_datum_offset_m": datum_offset,
        "calibrated_location": calibrated_location,
        "confidence": confidence,
    }

    return normalized, metadata

def detect_estimated_tide_events(heights):
    """
    Detect simple local high/low tide events from hourly sea level estimates.

    Detection uses raw height_msl to preserve the actual Open-Meteo curve.
    display_height is carried for frontend display.
    """
    events = []

    if len(heights) < 3:
        return events

    for index in range(1, len(heights) - 1):
        previous_height = heights[index - 1].get("height_msl")
        current_height = heights[index].get("height_msl")
        next_height = heights[index + 1].get("height_msl")

        if previous_height is None or current_height is None or next_height is None:
            continue

        if current_height >= previous_height and current_height > next_height:
            events.append(
                {
                    "time": heights[index]["time"],
                    "height_msl": current_height,
                    "display_height": heights[index].get("display_height"),
                    "type": "High",
                    "is_estimated": True,
                }
            )

        elif current_height <= previous_height and current_height < next_height:
            events.append(
                {
                    "time": heights[index]["time"],
                    "height_msl": current_height,
                    "display_height": heights[index].get("display_height"),
                    "type": "Low",
                    "is_estimated": True,
                }
            )

    return events

def build_estimated_tide_data(res_m, lat, lon):
    """
    Build estimated tide data from Open-Meteo sea_level_height_msl.

    This is not an official tide table. It is a calibrated display layer over
    Open-Meteo sea level model data for fishing guidance.
    """
    hourly = res_m.get("hourly", {})
    hourly_units = res_m.get("hourly_units", {})

    times = hourly.get("time", [])
    sea_levels = hourly.get("sea_level_height_msl", [])

    raw_heights = []

    for timestamp, height in zip(times, sea_levels):
        raw_heights.append(
            {
                "time": timestamp,
                "height_msl": height,
            }
        )

    normalized_heights, metadata = normalize_estimated_tide_heights(
        raw_heights,
        lat,
        lon,
    )

    events = detect_estimated_tide_events(normalized_heights)

    return {
        "source": "open-meteo",
        "provider": "open_meteo_estimated",
        "type": "estimated_sea_level_height_msl",
        "is_official": False,
        "confidence": metadata["confidence"],
        "unit": hourly_units.get("sea_level_height_msl", "m"),
        "display_unit": "m",
        "display_reference": "estimated_relative_tide_level",
        "display_datum_method": metadata["display_datum_method"],
        "display_datum_offset_m": metadata["display_datum_offset_m"],
        "calibrated_location": metadata["calibrated_location"],
        "accuracy_note": (
            "Estimated tide trend derived from Open-Meteo sea level model. "
            "Useful for fishing guidance, not an official tide table, "
            "and not suitable for navigation."
        ),
        "display_note": (
            "display_height is calibrated or normalized for angler-facing tide display. "
            "height_msl preserves the raw Open-Meteo sea level value."
        ),
        "heights": normalized_heights,
        "events": events,
        # Temporary backward-compatible alias while frontend/activity code migrates.
        "extremes": events,
        "warnings": [
            "Estimated tide trend only; not official tide prediction.",
        ],
    }

def filter_tide_for_date(tide_data, date_str):
    """
    Extract estimated tide data for one local calendar date.
    """
    if not tide_data:
        return {
            "source": "open-meteo",
            "provider": "open_meteo_estimated",
            "type": "estimated_sea_level_height_msl",
            "is_official": False,
            "confidence": "low",
            "status": "unavailable",
            "heights": [],
            "events": [],
            "extremes": [],
            "warnings": [
                "Estimated tide data unavailable.",
            ],
        }

    heights = [
        item
        for item in tide_data.get("heights", [])
        if (item.get("time") or "").startswith(date_str)
    ]

    events = [
        item
        for item in tide_data.get("events", [])
        if (item.get("time") or "").startswith(date_str)
    ]

    return {
        "source": tide_data.get("source", "open-meteo"),
        "provider": tide_data.get("provider", "open_meteo_estimated"),
        "type": tide_data.get("type", "estimated_sea_level_height_msl"),
        "is_official": tide_data.get("is_official", False),
        "confidence": tide_data.get("confidence", "medium_low"),
        "unit": tide_data.get("unit", "m"),
        "display_unit": tide_data.get("display_unit", "m"),
        "display_reference": tide_data.get("display_reference"),
        "display_datum_method": tide_data.get("display_datum_method"),
        "display_datum_offset_m": tide_data.get("display_datum_offset_m"),
        "calibrated_location": tide_data.get("calibrated_location"),
        "accuracy_note": tide_data.get("accuracy_note"),
        "display_note": tide_data.get("display_note"),
        "heights": heights,
        "events": events,
        # Temporary alias for compatibility.
        "extremes": events,
        "warnings": tide_data.get("warnings", []),
    }

def detect_estimated_tide_extremes(heights):
    """
    Detect simple local high/low tide points from hourly sea level estimates.

    This is not an official tide-table algorithm. It is only used to provide
    fishing guidance such as rising/falling tide and approximate high/low windows.
    """
    extremes = []

    if len(heights) < 3:
        return extremes

    for index in range(1, len(heights) - 1):
        previous_height = heights[index - 1]["height"]
        current_height = heights[index]["height"]
        next_height = heights[index + 1]["height"]

        if previous_height is None or current_height is None or next_height is None:
            continue

        if current_height >= previous_height and current_height > next_height:
            extremes.append(
                {
                    "time": heights[index]["time"],
                    "height": current_height,
                    "type": "High",
                }
            )

        elif current_height <= previous_height and current_height < next_height:
            extremes.append(
                {
                    "time": heights[index]["time"],
                    "height": current_height,
                    "type": "Low",
                }
            )

    return extremes

def build_estimated_tide_data(res_m):
    """
    Build estimated tide data from Open-Meteo sea_level_height_msl.

    Important:
    - This is not an official tide table.
    - It is useful for fishing guidance and tide trend estimation.
    - It must not be used for navigation.
    """
    hourly = res_m.get("hourly", {})
    hourly_units = res_m.get("hourly_units", {})

    times = hourly.get("time", [])
    sea_levels = hourly.get("sea_level_height_msl", [])

    heights = []

    for timestamp, height in zip(times, sea_levels):
        heights.append(
            {
                "time": timestamp,
                "height": height,
            }
        )

    return {
        "source": "open-meteo",
        "type": "estimated_sea_level_height_msl",
        "unit": hourly_units.get("sea_level_height_msl", "m"),
        "accuracy_note": (
            "Estimated sea level trend from Open-Meteo marine model. "
            "Useful for fishing guidance, not an official tide table, "
            "and not suitable for navigation."
        ),
        "heights": heights,
        "extremes": detect_estimated_tide_extremes(heights),
    }

def filter_tide_for_date(tide_data, date_str):

    """
    Extract estimated tide data for one local calendar date.
    """
    if not tide_data:
        return {
            "source": "open-meteo",
            "type": "estimated_sea_level_height_msl",
            "status": "unavailable",
            "heights": [],
            "extremes": [],
        }

    heights = [
        item
        for item in tide_data.get("heights", [])
        if (item.get("time") or "").startswith(date_str)
    ]

    extremes = [
        item
        for item in tide_data.get("extremes", [])
        if (item.get("time") or "").startswith(date_str)
    ]

    return {
        "source": tide_data.get("source", "open-meteo"),
        "type": tide_data.get("type", "estimated_sea_level_height_msl"),
        "unit": tide_data.get("unit", "m"),
        "accuracy_note": tide_data.get("accuracy_note"),
        "heights": heights,
        "extremes": extremes,
    }

def get_astronomy_data(target_dt, lat, lon):
    # 1. Base Time & Moon Phase (Global)
    dt_utc = target_dt.replace(hour=12, minute=0) - timedelta(hours=10)
    diff = dt_utc - LUNAR_ANCHOR
    days_since_new_moon = diff.total_seconds() / 86400
    phase = (days_since_new_moon / LUNATION_CYCLE) % 1

    # 2. Moon Transit (Longitude Dependent)
    location_correction = (lon / 15.0)
    days_in_cycle = days_since_new_moon % LUNATION_CYCLE
    transit_base = (days_in_cycle / LUNATION_CYCLE) * 24

    major_1_center = (12 + transit_base - location_correction + 10) % 24
    major_2_center = (major_1_center + 12) % 24
    minor_1_center = (major_1_center - 6) % 24
    minor_2_center = (major_1_center + 6) % 24

    # 3. SUNRISE/SUNSET (LATITUDE & SEASON DEPENDENT)
    # Menghitung hari ke-berapa dalam setahun (1-365)
    day_of_year = target_dt.timetuple().tm_yday

    # Menghitung deklinasi matahari (kemiringan bumi terhadap matahari)
    # Rumus: -23.44 * cos(360/365 * (N + 10))
    declination = -23.44 * math.cos(math.radians(360 / 365 * (day_of_year + 10)))

    # Menghitung Hour Angle (kapan matahari menyentuh cakrawala)
    # Ini melibatkan Latitude (lat) Suhu!
    lat_rad = math.radians(lat)
    dec_rad = math.radians(declination)

    # Rumus durasi siang (Hour Angle)
    # cos(h) = -tan(lat) * tan(dec)
    try:
        cos_h = -math.tan(lat_rad) * math.tan(dec_rad)
        # Batasi nilai agar tidak error (di kutub saat polar night/day)
        cos_h = max(min(cos_h, 1.0), -1.0)
        h_angle = math.degrees(math.acos(cos_h)) / 15.0  # Konversi ke jam
    except Exception:
        h_angle = 6.0  # Default jika kalkulasi gagal

    # Sunrise/Sunset Dasar (Solar Noon adalah ~12:00)
    # Dikoreksi dengan Longitude dan durasi siang (h_angle)
    sr_base = 12.0 - h_angle - (location_correction - 10)
    ss_base = 12.0 + h_angle - (location_correction - 10)

    # 4. Helper Formatting
    def fmt_time(h):
        h = h % 24
        return f"{int(h):02d}:{int((h % 1) * 60):02d}"

    def fmt_range(center):
        return f"{fmt_time(center - 1)} - {fmt_time(center + 1)}"

    is_good_phase = phase < 0.1 or 0.4 < phase < 0.6 or phase > 0.9
    major_emoji = "🐟🐟🔥" if is_good_phase else "🐟🐟"

    return {
        "sr": fmt_time(sr_base),
        "ss": fmt_time(ss_base),
        "major": f"{major_emoji} {fmt_range(major_2_center)} & {fmt_range(major_1_center)}",
        "minor": f"🐟 {fmt_range(minor_2_center)} & {fmt_range(minor_1_center)}",
        "low": "💤 Outside the Major and Minor periods",
    }

def find_nearest_sea_cell_data(lat, lon):
    # Pola Radar: Cek titik asli dulu, baru melingkar menjauh kalau gagal
    # 0.025 derajat ~ 2.75km
    # 0.075 derajat ~ 8km
    search_pattern = [
        (0, 0),  # Titik asli — kasus paling umum kalau pin sudah valid di laut

        # Langkah 1: Cek radius menengah (~2.75km) ke 4 arah utama
        (0, 0.025), (0, -0.025), (0.025, 0), (-0.025, 0),

        # Langkah 2: Cek Diagonal (Penting untuk garis pantai yang miring)
        (0.025, 0.025), (0.025, -0.025), (-0.025, 0.025), (-0.025, -0.025),

        # Langkah 3: Cek radius jauh (~8km) jika lokasi di dalam teluk dalam
        (0, 0.075), (0, -0.075), (0.075, 0), (-0.075, 0),
    ]
    for d_lat, d_lon in search_pattern:
        t_lat, t_lon = round(lat + d_lat, 4), round(lon + d_lon, 4)

        url_check = (
            f"https://marine-api.open-meteo.com/v1/marine"
            f"?latitude={t_lat}&longitude={t_lon}&hourly=wave_height&forecast_days=1"
        )

        try:
            r = requests.get(url_check, timeout=2).json()
            # Kuncinya: Cari titik pertama yang koordinatnya dianggap 'Sea' oleh Open-Meteo
            if r.get("hourly", {}).get("wave_height") and r["hourly"]["wave_height"][0] is not None:
                print(f"✅ Found the location ({t_lat}, {t_lon}) for input ({lat}, {lon})")
                return t_lat, t_lon
        except requests.RequestException:
            continue

    return lat, lon

def get_weather_data(lat, lon):
    # Langkah 1: Cari koordinat laut terdekat (Spiral Search)
    sea_lat, sea_lon = find_nearest_sea_cell_data(lat, lon)

    res_m = {"hourly": {}}
    res_w = {"hourly": {}}
    res_t = None

    try:
        # 2. Ambil Cuaca Daratan (Lokasi asli user)
        url_w = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,apparent_temperature,precipitation,precipitation_probability,pressure_msl"
            f"&timezone=auto&forecast_days=7"
        )
        res_w = requests.get(url_w, timeout=5).json()

        # 3. Ambil Data Marine (Wave, Swell, Period, Estimated Tide)
        url_m = (
            f"https://marine-api.open-meteo.com/v1/marine?latitude={sea_lat}&longitude={sea_lon}"
            f"&hourly=wave_height,swell_wave_height,swell_wave_period,wave_period,sea_level_height_msl"
            f"&timezone=auto&forecast_days=7"
        )
        res_m = requests.get(url_m, timeout=5).json()

        # 4. Build estimated tide data from Open-Meteo sea level model.
        # Use original lat/lon so known fishing spot calibration can be applied.
        res_t = build_estimated_tide_data(
            res_m,
            lat=lat,
            lon=lon,
        )

    except Exception as e:
        print(f"🔥 Error Fetching Data: {e}")

    return res_m, res_w, res_t, sea_lat, sea_lon
