def get_astronomy_data(
    date_str: str,
    lat: float,
    lon: float,
    timezone_name: str = "Australia/Sydney",
) -> dict:
    """
    Temporary astronomy placeholder.

    Purpose:
    - Keep the weather_activity Lambda pipeline working.
    - Replace later with accurate Skyfield-based sun/moon calculation.

    This function intentionally returns stable keys so frontend and downstream
    Lambdas can rely on the response contract.
    """
    return {
        "sunrise": "06:59",
        "sunset": "16:56",
        "moonrise": None,
        "moonset": None,
        "moon_transit": None,
        "moon_antitransit": None,
        "moon_phase": "Unknown",
        "moon_illumination": None,
        "timezone": timezone_name,
        "calculation_method": "placeholder",
    }
