#!/usr/bin/env python3
"""
productor_mxl.py
Motor de ensamblaje de video vertical (1080x1920) para el canal "mxl Aprende".

Flujo autonomo (disparado por el webhook de n8n, ver main.py):
    tema -> gemini_client.generar_guion()  -> guion (titulo + escenas)
    cada escena -> tts_client.sintetizar_audio() -> mp3
    cada escena -> asset_manager.get_random_asset(emocion) -> imagen del robot MXL
    -> video final (moviepy) + estructura JSON de retorno

Tambien conserva el flujo por lote basado en archivos JSON locales en
data/guiones/pendientes/, util para pruebas manuales sin pasar por n8n:
    python3 productor_mxl.py                    -> procesa TODOS los guiones pendientes
    python3 productor_mxl.py ruta/al/guion.json  -> procesa un guion especifico

En ambos casos no se usa ninguna base de datos: todo el estado vive en el
sistema de archivos del contenedor mientras el servicio esta activo.
"""

import sys
import json
import time
import random
import logging
import traceback
from pathlib import Path
from datetime import datetime

# --- Parche de compatibilidad: moviepy 1.0.3 llama a PIL.Image.ANTIALIAS,
# atributo que Pillow elimino desde la version 10 (reemplazado por LANCZOS).
# Sin este parche, cualquier resize() de moviepy revienta con
# "module 'PIL.Image' has no attribute 'ANTIALIAS'".
from PIL import Image as _PILImage
if not hasattr(_PILImage, "ANTIALIAS"):
    _PILImage.ANTIALIAS = _PILImage.LANCZOS

from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeAudioClip,
    concatenate_videoclips, afx
)

from config.settings import settings
from core.asset_manager import asset_manager
from core.tts_client import sintetizar_audio
from core import gemini_client

PAUSA_ENTRE_VIDEOS_SEG = 5

# ---------- Configuracion ----------
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 30
ZOOM_FACTOR = 1.15
AUDIO_PADDING = 0.4
MUSIC_VOLUME = 0.12

# --- Efectos de video ---
FADE_IN_SEG = 0.4          # entrada suave desde negro al inicio del video
FADE_OUT_SEG = 0.6         # salida suave a negro al final del video
CROSSFADE_SEG = 0.3        # disolvencia cruzada entre escenas (corta a proposito
                            # para no encimar audiblemente las voces de dos escenas)

# --- Efectos de audio ---
VOZ_FADE_SEG = 0.12        # suaviza el ataque/cierre de cada linea de voz (evita "clicks")
MUSIC_FADE_IN_SEG = 1.5
MUSIC_FADE_OUT_SEG = 2.0
SFX_VOLUME = 0.35          # volumen del efecto de transicion (whoosh) entre escenas

BASE_DIR = settings.BASE_DIR
GUIONES_DIR = BASE_DIR / "data" / "guiones"
PENDIENTES_DIR = GUIONES_DIR / "pendientes"
COMPLETADOS_DIR = GUIONES_DIR / "completados"
FALLIDOS_DIR = GUIONES_DIR / "fallidos"
OUTPUT_DIR = BASE_DIR / "output"
MUSICA_DIR = BASE_DIR / "assets" / "musica"
SFX_DIR = BASE_DIR / "assets" / "efectos_sonido"
TMP_AUDIO_DIR = BASE_DIR / "data" / "tmp_audio"

for d in (PENDIENTES_DIR, COMPLETADOS_DIR, FALLIDOS_DIR, OUTPUT_DIR, TMP_AUDIO_DIR):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(settings.LOGS_DIR / "productor_mxl.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("productor_mxl")

if CROSSFADE_SEG >= AUDIO_PADDING:
    # El crossfade de video solapa el final de una escena con el inicio de
    # la siguiente. Mientras CROSSFADE_SEG sea menor que AUDIO_PADDING, ese
    # solape cae dentro del "silencio" que queda despues de que termina la
    # voz de cada escena (la voz nunca llena toda la duracion_escena, solo
    # audio_clip.duration; el resto es padding sin audio). Si se invierte
    # esta relacion, las voces de dos escenas consecutivas se van a
    # escuchar encimadas durante el crossfade.
    logger.warning(
        "CROSSFADE_SEG (%.2fs) >= AUDIO_PADDING (%.2fs): las voces de escenas "
        "consecutivas pueden encimarse durante la transicion.",
        CROSSFADE_SEG, AUDIO_PADDING,
    )


# ---------- Utilidades ----------

def efecto_ken_burns(clip: ImageClip, duracion: float, zoom_in: bool = True):
    def zoom_func(t):
        progreso = t / duracion
        if zoom_in:
            return 1 + (ZOOM_FACTOR - 1) * progreso
        return ZOOM_FACTOR - (ZOOM_FACTOR - 1) * progreso
    return clip.resize(zoom_func)


def imagen_a_clip_vertical(ruta_imagen: Path, duracion: float) -> ImageClip:
    clip = ImageClip(str(ruta_imagen)).set_duration(duracion)
    w, h = clip.size
    escala = max(VIDEO_W / w, VIDEO_H / h)
    clip = clip.resize(escala)
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=VIDEO_W, height=VIDEO_H)
    clip = efecto_ken_burns(clip, duracion, zoom_in=random.choice([True, False]))
    return clip.set_position("center")


def elegir_musica_fondo():
    """Elige una pista aleatoria de assets/musica/, si existe. Es opcional."""
    if not MUSICA_DIR.exists():
        return None
    pistas = [p for p in MUSICA_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".ogg")]
    return random.choice(pistas) if pistas else None


def elegir_efecto_transicion():
    """
    Elige un efecto de sonido corto (tipo 'whoosh') de assets/efectos_sonido/,
    si existe, para reforzar cada corte entre escenas. Totalmente opcional:
    si la carpeta no existe o esta vacia, las transiciones quedan sin sfx.
    """
    if not SFX_DIR.exists():
        return None
    pistas = [p for p in SFX_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".ogg")]
    return random.choice(pistas) if pistas else None


# ---------- Nucleo del ensamblaje ----------

def construir_video(guion: dict, run_id: str) -> dict:
    """
    Arma el video a partir de un guion ya generado (por Gemini o por un
    archivo JSON local) y devuelve la estructura final: titulo, archivo,
    duracion, musica y el detalle de cada escena.

    Efectos aplicados (todos opcionales/seguros: si falta algun asset el
    video se arma igual, simplemente sin ese efecto puntual):
      - Video: Ken Burns por escena, disolvencia cruzada (crossfade) entre
        escenas consecutivas, entrada/salida a negro al inicio y al final.
      - Audio: suavizado de ataque/cierre en cada linea de voz, musica de
        fondo con fade in/out y en loop, efecto de transicion (whoosh)
        sincronizado con cada corte de escena si hay pistas en
        assets/efectos_sonido/.
    """
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("El guion no contiene 'escenas'.")

    titulo = guion.get("titulo", f"video_{run_id}")
    clips_video = []
    duraciones = []
    audios_temporales = []
    escenas_resultado = []

    for idx, escena in enumerate(escenas, start=1):
        texto = (escena.get("texto") or "").strip()
        emocion = escena.get("emocion", "feliz")

        if not texto:
            logger.warning("Escena %s sin texto, se omite.", idx)
            continue

        audio_path = TMP_AUDIO_DIR / f"{run_id}_escena_{idx:02d}.mp3"
        sintetizar_audio(texto, audio_path)
        audios_temporales.append(audio_path)

        audio_clip = AudioFileClip(str(audio_path))
        audio_clip = audio_clip.fx(afx.audio_fadein, VOZ_FADE_SEG).fx(afx.audio_fadeout, VOZ_FADE_SEG)
        duracion_escena = audio_clip.duration + AUDIO_PADDING

        try:
            ruta_imagen = asset_manager.get_random_asset(category=emocion)
        except ValueError:
            logger.warning("Emocion '%s' sin imagenes; se usa una imagen aleatoria.", emocion)
            ruta_imagen = asset_manager.get_random_asset()

        clip_img = imagen_a_clip_vertical(ruta_imagen, duracion_escena)
        clip_img = clip_img.set_audio(audio_clip)

        # Disolvencia cruzada con la escena anterior (la primera entra sola,
        # ya que el fade-in general del video se encarga de su inicio).
        if idx > 1:
            clip_img = clip_img.crossfadein(CROSSFADE_SEG)

        clips_video.append(clip_img)
        duraciones.append(duracion_escena)

        escenas_resultado.append({
            "orden": idx,
            "emocion": emocion,
            "texto": texto,
            "imagen": str(ruta_imagen.relative_to(BASE_DIR)),
            "duracion_seg": round(duracion_escena, 2),
        })

    if not clips_video:
        raise ValueError("Ninguna escena pudo procesarse; el guion quedo vacio.")

    # Con padding negativo, cada escena (salvo la primera) arranca a solaparse
    # CROSSFADE_SEG segundos antes de que termine la anterior.
    video_final = concatenate_videoclips(clips_video, method="compose", padding=-CROSSFADE_SEG)
    video_final = video_final.fadein(FADE_IN_SEG).fadeout(FADE_OUT_SEG)
    duracion_total = round(video_final.duration, 2)

    # Instante (en la linea de tiempo final) donde arranca cada escena,
    # tomando en cuenta el solape del crossfade. Se usa para sincronizar
    # el efecto de transicion (sfx) exactamente con cada corte.
    tiempos_inicio = [0.0]
    for d in duraciones[:-1]:
        tiempos_inicio.append(tiempos_inicio[-1] + d - CROSSFADE_SEG)

    pistas_audio = [video_final.audio]

    pista_musica = elegir_musica_fondo()
    if pista_musica:
        musica = AudioFileClip(str(pista_musica)).fx(afx.audio_loop, duration=video_final.duration)
        musica = musica.fx(afx.volumex, MUSIC_VOLUME)
        musica = musica.fx(afx.audio_fadein, MUSIC_FADE_IN_SEG).fx(afx.audio_fadeout, MUSIC_FADE_OUT_SEG)
        pistas_audio.append(musica)
    else:
        logger.info("No se encontro musica de fondo en %s; el video sale solo con voz.", MUSICA_DIR)

    efectos_transicion_usados = 0
    if len(tiempos_inicio) > 1 and elegir_efecto_transicion() is not None:
        for t_inicio in tiempos_inicio[1:]:
            pista_sfx = elegir_efecto_transicion()
            if pista_sfx is None:
                continue
            inicio_sfx = max(t_inicio - 0.05, 0.0)
            efecto = AudioFileClip(str(pista_sfx)).fx(afx.volumex, SFX_VOLUME).set_start(inicio_sfx)
            pistas_audio.append(efecto)
            efectos_transicion_usados += 1

    if len(pistas_audio) > 1:
        video_final = video_final.set_audio(CompositeAudioClip(pistas_audio))

    nombre_archivo = f"{titulo.replace(' ', '_').lower()}_{run_id}.mp4"
    salida = OUTPUT_DIR / nombre_archivo

    video_final.write_videofile(
        str(salida), fps=FPS, codec="libx264", audio_codec="aac",
        threads=1, preset="ultrafast", ffmpeg_params=["-pix_fmt", "yuv420p"],
        logger=None,
    )

    for clip in clips_video:
        clip.close()
    video_final.close()
    for audio_path in audios_temporales:
        audio_path.unlink(missing_ok=True)

    return {
        "titulo": titulo,
        "run_id": run_id,
        "archivo": nombre_archivo,
        "ruta_relativa": str(salida.relative_to(BASE_DIR)),
        "duracion_total_seg": duracion_total,
        "musica": str(pista_musica.relative_to(BASE_DIR)) if pista_musica else None,
        "efectos_transicion_usados": efectos_transicion_usados,
        "escenas": escenas_resultado,
    }


# ---------- Flujo dinamico disparado por n8n (Gemini) ----------

def generar_video_desde_tema(tema: str, num_escenas: int = 4) -> dict:
    """
    Flujo completo y autonomo: Gemini genera el guion sobre `tema`,
    se sintetiza la voz de cada escena y se arma el video. No toca
    data/guiones/ ni ninguna base de datos.
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=== Generando video para tema '%s' (run_id=%s) ===", tema, run_id)

    guion = gemini_client.generar_guion(tema, num_escenas)
    resultado = construir_video(guion, run_id)

    logger.info("VIDEO OK: %s", resultado["archivo"])
    return resultado


# ---------- Flujo por lote (archivos JSON locales, uso manual/pruebas) ----------

def procesar_guion_individual(ruta_guion: Path) -> bool:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=== Procesando guion: %s (run_id=%s) ===", ruta_guion.name, run_id)

    try:
        with open(ruta_guion, "r", encoding="utf-8") as f:
            guion = json.load(f)

        resultado = construir_video(guion, run_id)
        logger.info("VIDEO OK: %s", resultado["archivo"])

        ruta_guion.rename(COMPLETADOS_DIR / ruta_guion.name)
        return True

    except Exception as e:
        logger.error("FALLO en guion '%s': %s", ruta_guion.name, e)
        logger.debug(traceback.format_exc())
        try:
            ruta_guion.rename(FALLIDOS_DIR / ruta_guion.name)
        except Exception:
            pass
        return False


def procesar_lote():
    guiones = sorted(PENDIENTES_DIR.glob("*.json"))
    if not guiones:
        logger.info("No hay guiones pendientes en %s", PENDIENTES_DIR)
        return

    exitosos = fallidos = 0
    for i, ruta_guion in enumerate(guiones):
        if procesar_guion_individual(ruta_guion):
            exitosos += 1
        else:
            fallidos += 1

        if i < len(guiones) - 1:
            logger.info("Pausa de %ss antes del siguiente video...", PAUSA_ENTRE_VIDEOS_SEG)
            time.sleep(PAUSA_ENTRE_VIDEOS_SEG)

    logger.info("=== Lote terminado: %s OK, %s fallidos ===", exitosos, fallidos)


if __name__ == "__main__":
    settings.ensure_directories()
    settings.validate()

    if len(sys.argv) > 1:
        ruta = Path(sys.argv[1])
        if not ruta.exists():
            logger.error("El guion no existe: %s", ruta)
            sys.exit(1)
        procesar_guion_individual(ruta)
    else:
        procesar_lote()
