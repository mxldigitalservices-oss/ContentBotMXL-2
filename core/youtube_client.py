"""
core/youtube_client.py
Cliente de YouTube Data API v3 para ContentBotMXL.

Usa las credenciales OAuth2 de larga duracion (refresh token) generadas UNA
vez con scripts/obtener_refresh_token_youtube.py y guardadas como variables
de entorno en Railway (ver config/settings.py):

    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN
    YOUTUBE_PRIVACY_STATUS   (opcional, default "private")
    YOUTUBE_MADE_FOR_KIDS    (opcional, default "true")
"""

import os
import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.settings import settings

logger = logging.getLogger("contentbotmxl.youtube_client")

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _build_service():
    """Reconstruye el servicio de YouTube a partir del refresh token guardado."""
    settings.validate_youtube()

    credenciales = Credentials(
        token=None,  # se obtiene automaticamente con el refresh_token al primer uso
        refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
        token_uri=TOKEN_URI,
        client_id=settings.YOUTUBE_CLIENT_ID,
        client_secret=settings.YOUTUBE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=credenciales, cache_discovery=False)


def subir_video(
    ruta_video,
    titulo: str,
    descripcion: str = "",
    tags: list | None = None,
    privacy_status: str | None = None,
    ruta_miniatura: str | None = None,
    publicar_en: str | None = None,
) -> dict:
    """
    Sube un video (mp4) a YouTube usando las credenciales configuradas.

    Args:
        ruta_video: ruta local al archivo .mp4 (Path o str).
        titulo: titulo del video en YouTube.
        descripcion: descripcion del video.
        tags: lista de etiquetas/tags.
        privacy_status: "private" | "unlisted" | "public". Si es None, usa
            settings.YOUTUBE_PRIVACY_STATUS. Se ignora si se pasa `publicar_en`
            (YouTube exige que el video quede "private" hasta la fecha programada).
        ruta_miniatura: opcional, ruta a una imagen para usar como portada.
        publicar_en: opcional, fecha/hora ISO 8601 con zona horaria
            (ej. "2026-07-25T15:00:00Z" o "2026-07-25T11:00:00-04:00") en la
            que YouTube debe publicar el video automaticamente. Mientras
            tanto el video queda oculto (privado), visible solo para ti.

    Devuelve un dict con video_id, url, privacy_status/madeForKids usados y,
    si se programo, publicar_en.
            settings.YOUTUBE_PRIVACY_STATUS.
        ruta_miniatura: opcional, ruta a una imagen para usar como portada.

    Devuelve un dict con video_id, url y el privacy_status/madeForKids usados.
    """
    ruta_video = str(ruta_video)
    if not os.path.exists(ruta_video):
        raise FileNotFoundError(f"No se encontro el video a subir: {ruta_video}")

    youtube = _build_service()

    status_final = privacy_status or settings.YOUTUBE_PRIVACY_STATUS

    status_body = {
        "privacyStatus": status_final,
        # Requisito legal (COPPA/US, y equivalentes en otros paises) para
        # contenido dirigido a ninos: hay que declararlo explicitamente.
        "selfDeclaredMadeForKids": settings.YOUTUBE_MADE_FOR_KIDS,
    }

    if publicar_en:
        # YouTube exige que el video este en "private" mientras espera la
        # fecha programada; el publishAt es lo que dispara la publicacion
        # automatica en ese momento exacto.
        status_body["privacyStatus"] = "private"
        status_body["publishAt"] = publicar_en
        status_final = "private"

    body = {
        "snippet": {
            "title": titulo,
            "description": descripcion,
            "tags": tags or [],
            "categoryId": "27",  # "Education"; ajustar si prefieren otra categoria
        },
        "status": status_body,
    }

    media = MediaFileUpload(ruta_video, chunksize=-1, resumable=True, mimetype="video/mp4")

    logger.info(
        "Subiendo a YouTube: %s (privacy=%s, madeForKids=%s, publicar_en=%s)",
        titulo, status_final, settings.YOUTUBE_MADE_FOR_KIDS, publicar_en,
    )
    logger.info("Subiendo a YouTube: %s (privacy=%s, madeForKids=%s)",
                titulo, status_final, settings.YOUTUBE_MADE_FOR_KIDS)

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status_progreso, response = request.next_chunk()
        if status_progreso:
            logger.info("Progreso de subida: %d%%", int(status_progreso.progress() * 100))

    video_id = response["id"]
    logger.info("Video subido a YouTube con id=%s", video_id)

    if ruta_miniatura and os.path.exists(ruta_miniatura):
        subir_miniatura_video(youtube, video_id, ruta_miniatura)

    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy_status": status_final,
        "made_for_kids": settings.YOUTUBE_MADE_FOR_KIDS,
        "publicar_en": publicar_en,
    }


def subir_miniatura_video(youtube_service, video_id, ruta_imagen):
    """
    Sube y asigna una imagen de portada (miniatura) a un video de YouTube ya subido.
    """
    if not ruta_imagen or not os.path.exists(ruta_imagen):
        print(f"No se encontró la imagen de portada en la ruta: {ruta_imagen}")
        return None

    try:
        request = youtube_service.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(ruta_imagen)
        )
        response = request.execute()
        print(f"¡Portada/miniatura asignada correctamente al video {video_id}!")
        return response
    except Exception as e:
        print(f"Error al subir la miniatura a YouTube: {e}")
        return None
