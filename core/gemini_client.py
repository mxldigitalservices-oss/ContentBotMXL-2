"""
core/gemini_client.py
Cliente minimo (solo `requests`, sin SDK pesado) para la Generative Language
API de Gemini. Genera el guion (titulo + escenas) de un video de "mxl Aprende"
a partir de un tema, usando prompt_maestro.txt -que vive versionado en este
mismo repo- como instruccion base. Usa exclusivamente GEMINI_API_KEY.
"""

import json
import logging
import re

from config.settings import settings
from core.http_retry import post_con_reintentos

logger = logging.getLogger("contentbotmxl.gemini")

GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

EMOCIONES_VALIDAS = ("feliz", "pensativo", "sorprendido", "con_amigos", "hablando")


def _cargar_prompt_maestro() -> str:
    """Lee prompt_maestro.txt del repo. Falla si no esta versionado ahi."""
    if not settings.PROMPT_MAESTRO_PATH.exists():
        raise FileNotFoundError(
            f"No se encontro prompt_maestro.txt en {settings.PROMPT_MAESTRO_PATH}. "
            "Debe subirse al repo de GitHub para que Railway lo lea."
        )
    return settings.PROMPT_MAESTRO_PATH.read_text(encoding="utf-8")


def _extraer_json(texto: str) -> dict:
    """Gemini a veces envuelve el JSON en ```json ... ```; se limpia antes de parsear."""
    limpio = texto.strip()
    limpio = re.sub(r"^```json\s*|^```\s*|```$", "", limpio, flags=re.MULTILINE).strip()
    return json.loads(limpio)


def generar_guion(tema: str, num_escenas: int = 4) -> dict:
    """
    Llama a Gemini para generar el guion del video sobre `tema`.
    Devuelve {"titulo": str, "escenas": [{"emocion": str, "texto": str}, ...]}.
    """
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("Falta GEMINI_API_KEY en las variables de entorno.")

    prompt_base = _cargar_prompt_maestro()
    instruccion = (
        f"{prompt_base}\n\n"
        f"TEMA DEL VIDEO: {tema}\n"
        f"NUMERO DE ESCENAS: {num_escenas}\n"
        f"Emociones permitidas por escena (elige la mas adecuada para cada una): "
        f"{', '.join(EMOCIONES_VALIDAS)}.\n\n"
        "Responde EXCLUSIVAMENTE con un JSON valido, sin texto adicional ni markdown, "
        'con esta forma exacta: {"titulo": "...", "escenas": '
        '[{"emocion": "feliz", "texto": "..."}]}'
    )

    body = {
        "contents": [{"parts": [{"text": instruccion}]}],
        "generationConfig": {
            "temperature": 0.8,
            "responseMimeType": "application/json",
        },
    }

    resp = post_con_reintentos(
        GEMINI_URL,
        params={"key": settings.GEMINI_API_KEY},
        json=body,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Gemini devolvio un error ({resp.status_code}): {resp.text}")
    data = resp.json()

    try:
        texto_generado = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Respuesta inesperada de Gemini: {data}") from e

    guion = _extraer_json(texto_generado)

    if "escenas" not in guion or not guion["escenas"]:
        raise ValueError("Gemini no devolvio escenas validas para este tema.")

    for escena in guion["escenas"]:
        if escena.get("emocion") not in EMOCIONES_VALIDAS:
            logger.warning(
                "Emocion invalida '%s' en escena, se usa 'feliz' por defecto.",
                escena.get("emocion"),
            )
            escena["emocion"] = "feliz"

    guion.setdefault("titulo", tema)
    logger.info(
        "Guion generado por Gemini: '%s' (%s escenas)", guion["titulo"], len(guion["escenas"])
    )
    return guion
