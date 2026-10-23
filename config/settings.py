"""
config/settings.py
Configuracion central de ContentBotMXL (Servidor 2 - Motor Backend en Railway).

Este servicio corre aislado: no usa base de datos externa ni de ningun tipo.
Todo lo que necesita (assets, prompt_maestro.txt) vive versionado en este
mismo repositorio de GitHub, y las unicas variables de entorno que usa son:

  - GEMINI_API_KEY     -> generacion de guion con Gemini
  - TTS_VOZ            -> (opcional) voz de edge-tts a usar; por defecto es-MX-DaliaNeural
  - N8N_WEBHOOK_SECRET -> autenticacion del webhook llamado por n8n

La voz (TTS) ya no usa Google Cloud: corre con edge-tts, que es gratuito y
no requiere ninguna API key ni cuenta de servicio.

Ademas, este archivo expone las variables OPCIONALES de publicacion en
YouTube (ver core/youtube_client.py). Son opcionales porque el motor de
generacion de video debe seguir funcionando aunque no esten configuradas:
solo se validan cuando efectivamente se llama al endpoint /webhook/publicar.

  - YOUTUBE_CLIENT_ID       -> credencial OAuth2 (tipo Desktop App)
  - YOUTUBE_CLIENT_SECRET   -> credencial OAuth2
  - YOUTUBE_REFRESH_TOKEN   -> token de larga duracion (ver scripts/obtener_refresh_token_youtube.py)
  - YOUTUBE_PRIVACY_STATUS  -> (opcional) private | unlisted | public; por defecto "private"
  - YOUTUBE_MADE_FOR_KIDS   -> (opcional) "true"/"false"; por defecto "true" (contenido infantil)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# --- Rutas base del proyecto ---
BASE_DIR = Path(__file__).resolve().parent.parent  # raiz de ContentBotMXL

ASSETS_DIR = BASE_DIR / "assets"
CORE_DIR = BASE_DIR / "core"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
PROMPT_MAESTRO_PATH = BASE_DIR / "prompt_maestro.txt"

# --- Carga de variables de entorno (.env local; en Railway se inyectan directo) ---
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


class Settings:
    """Configuracion central de la aplicacion."""

    BASE_DIR = BASE_DIR
    ASSETS_DIR = ASSETS_DIR
    DATA_DIR = DATA_DIR
    LOGS_DIR = LOGS_DIR
    PROMPT_MAESTRO_PATH = PROMPT_MAESTRO_PATH

    # --- Unicas variables de IA/voz que este servicio tiene permitido usar ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    TTS_VOZ = os.getenv("TTS_VOZ", "es-MX-DaliaNeural")

    # --- Autenticacion del webhook (Servidor 1 -> Servidor 2) ---
    N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "")

    # --- Publicacion en YouTube (opcional, ver core/youtube_client.py) ---
    YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
    YOUTUBE_PRIVACY_STATUS = os.getenv("YOUTUBE_PRIVACY_STATUS", "private")
    YOUTUBE_MADE_FOR_KIDS = os.getenv("YOUTUBE_MADE_FOR_KIDS", "true").strip().lower() == "true"

    APP_NAME = "ContentBotMXL"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def ensure_directories(cls):
        """Crea las carpetas necesarias si no existen (data/, logs/). No crea ninguna DB."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate(cls):
        """
        Verifica que el motor tenga TODO lo que necesita para operar de forma
        autonoma: assets del repo, prompt_maestro.txt versionado, y las
        credenciales de IA/voz. Se corre al arrancar el servicio en Railway.
        """
        if not cls.ASSETS_DIR.exists():
            raise FileNotFoundError(f"No se encontro la carpeta assets/ en {cls.ASSETS_DIR}")

        image_count = len(list(cls.ASSETS_DIR.rglob("*.*")))
        if image_count == 0:
            raise FileNotFoundError("La carpeta assets/ existe pero esta vacia.")

        if not cls.PROMPT_MAESTRO_PATH.exists():
            raise FileNotFoundError(
                f"No se encontro prompt_maestro.txt en {cls.PROMPT_MAESTRO_PATH}. "
                "Debe estar versionado en el repo de GitHub (no se lee de ningun otro lado)."
            )

        if not cls.GEMINI_API_KEY:
            raise RuntimeError("Falta GEMINI_API_KEY en las variables de entorno de Railway.")

        if not cls.N8N_WEBHOOK_SECRET:
            raise RuntimeError("Falta N8N_WEBHOOK_SECRET: el webhook no puede quedar sin proteger.")

        return image_count

    @classmethod
    def validate_youtube(cls):
        """
        Verifica las credenciales de YouTube. A diferencia de validate(), esto
        NO se corre al arrancar el servicio -- se llama solo cuando llega una
        peticion a /webhook/publicar, para que la generacion de video siga
        funcionando aunque YouTube todavia no este configurado.
        """
        faltantes = [
            nombre for nombre, valor in (
                ("YOUTUBE_CLIENT_ID", cls.YOUTUBE_CLIENT_ID),
                ("YOUTUBE_CLIENT_SECRET", cls.YOUTUBE_CLIENT_SECRET),
                ("YOUTUBE_REFRESH_TOKEN", cls.YOUTUBE_REFRESH_TOKEN),
            )
            if not valor
        ]
        if faltantes:
            raise RuntimeError(
                "Faltan variables de entorno para publicar en YouTube: "
                + ", ".join(faltantes)
                + ". Corre scripts/obtener_refresh_token_youtube.py para conseguirlas."
            )


settings = Settings()
