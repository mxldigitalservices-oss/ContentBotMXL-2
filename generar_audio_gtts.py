from gtts import gTTS
import os

def generar_audio_gtts(texto: str, output_path: str = "audio_temp.mp3", lang: str = "es"):
    """
    Sintesis de voz gratuita con gTTS sin API Keys ni bloqueos de IP.
    """
    try:
        print(f"Generando audio gTTS para: {texto[:40]}...")
        tts = gTTS(text=texto, lang=lang, slow=False)
        tts.save(output_path)
        print(f"Audio generado exitosamente en: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error generando audio con gTTS: {e}")
        raise e

if __name__ == "__main__":
    generar_audio_gtts("Prueba de audio limpia con gTTS")
