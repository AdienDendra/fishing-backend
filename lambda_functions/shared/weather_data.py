import math
import requests

from datetime import datetime, timedelta
from config import LUNAR_ANCHOR, LUNATION_CYCLE

LUNAR_ANCHOR = datetime(*LUNAR_ANCHOR)


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


    """
    A specific function to fetch tidal data from Open-Meteo.
    This data is based on a harmonic model (mathematical prediction).
    """
    url_t = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=tide_height&timezone=auto"
    try:
        r = requests.get(url_t, timeout=5).json()
        if "hourly" in r and "tide_height" in r["hourly"]:
            return r["hourly"]["tide_height"]
    except Exception as e:
        print(f"⚠️ Error Tide Fetch: {e}")
    return None

def get_weather_data(lat, lon):
    # Langkah 1: Cari koordinat laut terdekat (Spiral Search)
    sea_lat, sea_lon = find_nearest_sea_cell_data(lat, lon)

    res_m = {"hourly": {}}
    res_w = {"hourly": {}}
    res_t = None  # Untuk data tide

    try:
        # 2. Ambil Cuaca Daratan (Lokasi asli user)
        url_w = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,apparent_temperature,precipitation,precipitation_probability,pressure_msl"
            f"&timezone=auto&forecast_days=7"
        )
        res_w = requests.get(url_w, timeout=5).json()

        # 3. Ambil Data Marine (Wave, Swell, Period) di sea_lat/lon
        url_m = (
            f"https://marine-api.open-meteo.com/v1/marine?latitude={sea_lat}&longitude={sea_lon}"
            f"&hourly=wave_height,swell_wave_height,swell_wave_period,wave_period,sea_level_height_msl"
            f"&timezone=auto&forecast_days=7"
        )
        res_m = requests.get(url_m, timeout=5).json()

        # 4. Build estimated tide data from Open-Meteo sea level model
        res_t = build_estimated_tide_data(res_m)

    except Exception as e:
        print(f"🔥 Error Fetching Data: {e}")

    # Return ditambah res_t
    return res_m, res_w, res_t, sea_lat, sea_lon

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