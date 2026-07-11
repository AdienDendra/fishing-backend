import os

from google import genai
from google.genai import types

from config import (
    MODEL_LIST,
    SPECIES_AI_INSTRUCTIONS,
    WEATHER_AI_INSTRUCTIONS,
)

# The prompt limits the response to 250 words.
# This value is measured in tokens, not words, so extra headroom is required
# for Markdown headings and punctuation.
WEATHER_MAX_OUTPUT_TOKENS = 500


def generate_weather_analysis(
    client,
    location: str,
    date_str: str,
    data_points: str,
) -> tuple[str, str]:
    """
    Generate a concise fishing conditions explanation.

    The deterministic backend remains the source of truth for:
    - Strike Chance
    - Major and Minor periods
    - sunrise and sunset
    - tide timing

    Gemini only converts those results into an angler-facing narrative.
    """
    prompt_text = (
        f"LOCATION: {location}\n"
        f"DATE: {date_str}\n"
        "TIMEZONE: Australia/Sydney\n"
        "HOURLY ARRAY MAPPING: index 0 represents 00:00 local time, "
        "index 1 represents 01:00, and index 23 represents 23:00.\n"
        f"SUPPLIED DATA:\n{data_points}"
    )

    last_error: Exception | None = None

    print(f"🧠 Starting AI analysis for {location}...")

    for model_name in MODEL_LIST:
        try:
            print(f"📡 Trying model: {model_name}...")

            response = client.models.generate_content(
                model=model_name,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=WEATHER_AI_INSTRUCTIONS,
                    temperature=0.2,
                    max_output_tokens=WEATHER_MAX_OUTPUT_TOKENS,
                ),
            )

            response_text = (response.text or "").strip()

            if not response_text:
                raise RuntimeError(
                    f"{model_name} returned an empty response."
                )

            print(f"✅ Successfully used: {model_name}")

            return response_text, model_name

        except Exception as exc:
            last_error = exc
            print(
                f"❌ {model_name} failed: "
                f"{type(exc).__name__}: {str(exc)[:200]}"
            )

    if last_error is None:
        raise RuntimeError("MODEL_LIST is empty.")

    raise RuntimeError(
        f"All configured Gemini models failed. "
        f"Last error: {type(last_error).__name__}: {last_error}"
    ) from last_error


def generate_species_analysis(
    image_path: str,
    mime_type: str = "image/jpeg",
) -> str:
    """
    Identify a fish or marine creature from an uploaded image.
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return "❌ GEMINI_API_KEY is not configured."

    client = genai.Client(api_key=api_key)
    last_error: Exception | None = None

    for model_name in MODEL_LIST:
        try:
            print(
                f"🔄 Trying species identification with: "
                f"{model_name}..."
            )

            with open(image_path, "rb") as image_file:
                image_bytes = image_file.read()

            response = client.models.generate_content(
                model=model_name,
                contents=[
                    SPECIES_AI_INSTRUCTIONS,
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type,
                    ),
                ],
            )

            response_text = (response.text or "").strip()

            if not response_text:
                raise RuntimeError(
                    f"{model_name} returned an empty response."
                )

            return (
                f"{response_text}\n\n"
                f"_(Analysis by: {model_name})_"
            )

        except Exception as exc:
            last_error = exc
            print(
                f"⚠️ Model {model_name} failed: "
                f"{type(exc).__name__}: {exc}"
            )

    return (
        "❌ All expert models are currently unavailable. "
        f"Last error: {last_error}"
    )