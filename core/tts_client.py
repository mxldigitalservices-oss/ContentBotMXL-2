"""
core/tts_client.py
Motor de voz: sintetiza audio con edge-tts (las voces neuronales de
Microsoft Edge, las mismas que usa la funcion "Leer en voz alta" del
navegador).

Es un servicio gratuito: no requiere API key, cuenta, ni tarjeta, y no
depende de ninguna credencial de Google Cloud. La voz se elige con la
variable de entorno opcional TTS_VOZ (ver config/settings.py).
"""

import asyncio
import logging
from pathlib import Path

import edge_tts

from config.settings import settings

logger = logging.getLogger("contentbotmxl.tts")


async def _sintetizar_async(texto: str, destino: Path, voz: str) -> None:
    comunicador = edge_tts.Communicate(texto, voz)
    await comunicador.save(str(destino))


def sintetizar_audio(texto: str, destino: Path) -> Path:
    """
    Sintetiza `texto` a voz en espanol y guarda el mp3 resultante en `destino`.
    Usa edge-tts (motor de Microsoft Edge); no requiere ninguna credencial.
    """
    voz = settings.TTS_VOZ
    destino.parent.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(_sintetizar_async(texto, destino, voz))
    except Exception as e:
        raise RuntimeError(
            f"edge-tts fallo al sintetizar el audio (voz={voz}): {e}"
        ) from e

    if not destino.exists() or destino.stat().st_size == 0:
        raise RuntimeError("edge-tts no genero ningun archivo de audio (resultado vacio).")

    return destino
