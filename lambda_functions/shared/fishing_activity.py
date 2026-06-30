def build_fish_activity(
    astronomy: dict,
    tide: list,
    weather: dict,
    marine: dict,
) -> dict:
    """
    Temporary fish activity placeholder.

    Purpose:
    - Prove the async pipeline works:
      partial -> activity_ready -> complete
    - Replace later with deterministic scoring based on:
      major/minor solunar windows, moon phase, sunrise/sunset overlap,
      and tide movement.
    """
    return {
        "major": "🐟🐟 07:00 - 09:00 & 19:00 - 21:00",
        "minor": "🐟 01:00 - 03:00 & 13:00 - 15:00",
        "score": 50,
        "label": "Fair",
        "best_window": "07:00 - 09:00",
        "score_basis": {
            "solunar_period": 20,
            "moon_phase": 10,
            "sunrise_sunset_overlap": 10,
            "tide_alignment": 10,
        },
        "reasons": [
            "Temporary placeholder activity score.",
            "Accurate Skyfield-based solunar calculation will be added next.",
        ],
    }
