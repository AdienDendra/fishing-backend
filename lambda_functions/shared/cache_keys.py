def make_cache_key(lat: float, lon: float, date_str: str) -> str:
    """
    Build one cache file per location per date.

    Example:
    weather-cache/-34.0049_151.2288/2026-06-30.json
    """
    return f"weather-cache/{round(lat, 4)}_{round(lon, 4)}/{date_str}.json"
