"""
core/tts_client.py
Motor de voz de ContentBotMXL con DOS motores y reintentos:

  1. gTTS      -> motor principal (voz de Google Translate, sin API key).
  2. edge-tts  -> respaldo (voces neuronales de Microsoft Edge, sin API key).

Para cada motor se hacen hasta MAX_REINTENTOS intentos con espera creciente.
Si un motor se agota, se pasa al siguiente. Solo si TODOS fallan se lanza
RuntimeError, con el detalle de que paso en cada motor (asi el log de
Railway dice exactamente que fallo, en vez de un error generico).

La firma publica NO cambia: sintetizar_audio(texto, destino) -> Path, que es
lo unico que importa productor_mxl.py.

Variables de entorno opcionales (ver config/settings.py):
  TTS_MOTORES   -> orden de motores, por defecto "gtts,edge"
  TTS_IDIOMA    -> idioma de gTTS, por defecto "es"
  TTS_GTTS_TLD  -> dominio de Google que fija el acento de gTTS,
                   por defecto "com.mx" (espanol de Mexico)
  TTS_VOZ       -> voz de edge-tts, por defecto "es-MX-DaliaNeural"

Prueba rapida desde la raiz del repo (no necesita GEMINI_API_KEY):
  python -m core.tts_client "Hola, soy MXL"
"""

import asyncio
import logging
import time
from pathlib import Path

from config.settings import settings

logger = logging.getLogger("contentbotmxl.tts")

MAX_REINTENTOS = 3
ESPERA_BASE_SEG = 2.0          # 2s, 4s entre intentos de un mismo motor
TAMANO_MINIMO_BYTES = 1024     # un mp3 real de una frase pesa varios KB; menos = vacio/corrupto


class MotorTTSError(RuntimeError):
    """Un motor de voz agoto sus reintentos."""


# ---------- Motores ----------

def _sintetizar_gtts(texto: str, destino: Path) -> None:
    from gtts import gTTS  # import perezoso: si falta la libreria, solo falla este motor

    gTTS(
        text=texto,
        lang=settings.TTS_IDIOMA,
        tld=settings.TTS_GTTS_TLD,
        slow=False,
    ).save(str(destino))


def _sintetizar_edge(texto: str, destino: Path) -> None:
    import edge_tts  # import perezoso, igual que arriba

    async def _guardar():
        await edge_tts.Communicate(texto, settings.TTS_VOZ).save(str(destino))

    # Los endpoints de main.py son sincronos (FastAPI los corre en un hilo sin
    # event loop), asi que asyncio.run es seguro aqui.
    asyncio.run(_guardar())


MOTORES = {
    "gtts": _sintetizar_gtts,
    "edge": _sintetizar_edge,
}


# ---------- Logica comun ----------

def _archivo_valido(destino: Path) -> bool:
    return destino.exists() and destino.stat().st_size >= TAMANO_MINIMO_BYTES


def _intentar_motor(nombre: str, texto: str, destino: Path) -> None:
    """Reintenta un motor hasta MAX_REINTENTOS veces. Lanza MotorTTSError si se agota."""
    funcion = MOTORES[nombre]
    ultimo_error = "sin detalle"

    for intento in range(1, MAX_REINTENTOS + 1):
        destino.unlink(missing_ok=True)  # nunca dejar un archivo a medias de un intento previo
        try:
            funcion(texto, destino)
            if _archivo_valido(destino):
                return
            tamano = destino.stat().st_size if destino.exists() else 0
            ultimo_error = f"archivo invalido o vacio ({tamano} bytes)"
        except Exception as e:  # noqa: BLE001 - cada motor lanza excepciones distintas
            ultimo_error = f"{type(e).__name__}: {e}"

        logger.warning(
            "TTS motor '%s' intento %s/%s fallo: %s", nombre, intento, MAX_REINTENTOS, ultimo_error
        )
        if intento < MAX_REINTENTOS:
            time.sleep(ESPERA_BASE_SEG * (2 ** (intento - 1)))

    destino.unlink(missing_ok=True)
    raise MotorTTSError(ultimo_error)


def sintetizar_audio(texto: str, destino: Path) -> Path:
    """
    Sintetiza `texto` a voz en espanol y guarda el mp3 en `destino`.
    Prueba los motores de settings.TTS_MOTORES en orden, con reintentos.
    Devuelve `destino` si hubo exito; lanza RuntimeError si todos fallan.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("sintetizar_audio recibio un texto vacio.")

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    motores = [m for m in settings.TTS_MOTORES if m in MOTORES]
    desconocidos = [m for m in settings.TTS_MOTORES if m not in MOTORES]
    if desconocidos:
        logger.warning("TTS_MOTORES incluye motores desconocidos (se ignoran): %s", desconocidos)
    if not motores:
        raise RuntimeError(
            f"TTS_MOTORES no tiene ningun motor valido. Opciones: {sorted(MOTORES)}"
        )

    errores = []
    for nombre in motores:
        try:
            _intentar_motor(nombre, texto, destino)
            logger.info("TTS OK con '%s' (%s bytes): %s", nombre, destino.stat().st_size, destino.name)
            return destino
        except MotorTTSError as e:
            errores.append(f"{nombre}: {e}")
            logger.error("TTS motor '%s' agoto sus reintentos, se prueba el siguiente.", nombre)

    raise RuntimeError("Fallaron todos los motores de voz -> " + " | ".join(errores))


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    frase = " ".join(sys.argv[1:]) or "Hola, soy MXL. Esta es una prueba de voz."
    salida = settings.BASE_DIR / "output" / "audio" / "prueba_voz.mp3"
    resultado = sintetizar_audio(frase, salida)
    print(f"\nOK -> {resultado} ({resultado.stat().st_size} bytes)")

