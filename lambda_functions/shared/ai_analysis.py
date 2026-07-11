import os

from google import genai
from google.genai import types

# Adjusted to match the translated config variables
from config import MODEL_LIST, WEATHER_AI_INSTRUCTIONS, SPECIES_AI_INSTRUCTIONS

res = client.models.generate_content(
    model=md,
    contents=prompt_text,
    config=types.GenerateContentConfig(
        system_instruction=WEATHER_AI_INSTRUCTIONS,
        temperature=0.2,
        max_output_tokens=300,
    ),
)

def generate_weather_analysis(client, location, date_str, data_points):
    """
    Function using the latest model list, including 2.0 and 2.5
    """
    # Model list: fetched from config.py (MODEL_LIST)
    model_list = MODEL_LIST
    
    ai_response = "⚠️ *AI Analysis is currently busy, mate.*"
    model_used = "None"

    # Define the prompt OUTSIDE the try loop for safety
    prompt_text = (
        f"Instructions: {WEATHER_AI_INSTRUCTIONS}\n"
        f"LOCATION: {location}\n"
        f"DATE: {date_str}\n"
        f"WEATHER DATA:\n{data_points}"
    )

    print(f"\n🧠 Starting AI Analysis for {location}...")

    for md in model_list:
        try:
            print(f"📡 Trying model: {md}...") 
            
            # Call Gemini - We try without the 'models/' prefix first
            # If it returns a 404, we will automatically add the prefix
            res = client.models.generate_content(
                model=md, 
                contents=prompt_text
            )
            
            if res and res.text:
                ai_response = res.text
                model_used = md
                print(f"✅ Successfully used: {md}")
                break 
                
        except Exception as e:
            # If it fails due to a 404, automatically retry using the models/ prefix
            if "not found" in str(e).lower():
                try:
                    print(f"🔄 Retrying {md} with 'models/' prefix...")
                    res = client.models.generate_content(
                        model=f"models/{md}", 
                        contents=prompt_text
                    )
                    if res and res.text:
                        ai_response = res.text
                        model_used = md
                        print(f"✅ Successfully used: models/{md}")
                        break
                except:
                    pass
            
            print(f"❌ {md} Failed: {str(e)[:100]}")
            continue

    return ai_response, model_used


def generate_species_analysis(image_path, mime_type='image/jpeg'):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    last_error = ""
    
    # Loop through and try each model in the list
    for model_name in MODEL_LIST:
        try:
            print(f"🔄 Trying identification with: {model_name}...")
            
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            res = client.models.generate_content(
                model=model_name,
                contents=[
                    SPECIES_AI_INSTRUCTIONS,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                ]
            )
            
            # If successful, return the result immediately and stop the loop
            return f"{res.text}\n\n_(Analysis by: {model_name})_"

        except Exception as e:
            print(f"⚠️ Model {model_name} failed: {str(e)}")
            last_error = str(e)
            continue # Proceed to the next model in the list

    # If all models in the list fail
    return f"❌ All expert models are currently down, mate. Last error: {last_error}"