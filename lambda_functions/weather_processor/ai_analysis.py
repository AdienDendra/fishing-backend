import os

from google import genai
from google.genai import types

from config import MODEL_LIST, INSTRUKSI_CUACA_AI, INSTRUKSI_SPESIES_AI


def generate_analisis_cuaca(client, lokasi, tgl_str, data_points):
    """
    Fungsi dengan list model terbaru termasuk 2.0 dan 2.5
    """
    # List model: diambil dari config.py (MODEL_LIST)
    model_list = MODEL_LIST
    
    ai_response = "⚠️ *Analisa AI sedang sibuk, Om.*"
    model_used = "None"

    # Definisikan prompt di LUAR loop try agar aman
    prompt_text = (
        f"Instruksi: {INSTRUKSI_CUACA_AI}\n"
        f"LOKASI: {lokasi}\n"
        f"TANGGAL: {tgl_str}\n"
        f"DATA CUACA:\n{data_points}"
    )

    print(f"\n🧠 Memulai Analisa AI untuk {lokasi}...")

    for md in model_list:
        try:
            print(f"📡 Mencoba model: {md}...") 
            
            # Panggil Gemini - Kita coba tanpa prefix 'models/' dulu
            # Jika masih 404, baru kita tambahkan prefixnya
            res = client.models.generate_content(
                model=md, 
                contents=prompt_text
            )
            
            if res and res.text:
                ai_response = res.text
                model_used = md
                print(f"✅ Berhasil pakai: {md}")
                break 
                
        except Exception as e:
            # Jika gagal karena 404, coba pakai prefix models/ secara otomatis
            if "not found" in str(e).lower():
                try:
                    print(f"🔄 Mencoba ulang {md} dengan prefix models/...")
                    res = client.models.generate_content(
                        model=f"models/{md}", 
                        contents=prompt_text
                    )
                    if res and res.text:
                        ai_response = res.text
                        model_used = md
                        print(f"✅ Berhasil pakai: models/{md}")
                        break
                except:
                    pass
            
            print(f"❌ {md} Gagal: {str(e)[:100]}")
            continue

    return ai_response, model_used

def generate_analisis_spesies(image_path, mime_type='image/jpeg'):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    last_error = ""
    
    # Looping mencoba setiap model dalam list
    for model_name in MODEL_LIST:
        try:
            print(f"🔄 Mencoba identifikasi dengan: {model_name}...")
            
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            res = client.models.generate_content(
                model=model_name,
                contents=[
                    INSTRUKSI_SPESIES_AI,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                ]
            )
            
            # Jika berhasil, langsung return hasilnya dan hentikan loop
            return f"{res.text}\n\n_(Analisa oleh: {model_name})_"

        except Exception as e:
            print(f"⚠️ Model {model_name} gagal: {str(e)}")
            last_error = str(e)
            continue # Lanjut ke model berikutnya di list

    # Jika semua model di list gagal
    return f"❌ Semua model jagoan lagi mogok, Om. Error terakhir: {last_error}"