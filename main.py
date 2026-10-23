"""
main.py
API FastAPI de ContentBotMXL (Servidor 2 - Motor Backend, Railway).

Variables de entorno usadas (ver config/settings.py para el detalle):
  - GEMINI_API_KEY     -> generacion de guion (Gemini)
  - TTS_VOZ            -> (opcional) voz de edge-tts; por defecto es-MX-DaliaNeural
  - N8N_WEBHOOK_SECRET -> autenticacion del webhook desde n8n (header X-Webhook-Secret)
  - YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN
    -> (opcionales) solo necesarias para /webhook/publicar
  - DATABASE_URL       -> (opcional) si Railway tiene un Postgres conectado,
    se usa solo como registro/cola de reintentos (ver core/db.py); nunca es
    requisito para generar ni publicar videos.

Endpoints:
  - GET  /health                          -> healthcheck de Railway
  - POST /webhook/generar                 -> genera un video (sincrono o async+callback)
  - POST /webhook/publicar                -> sube a YouTube un mp4 ya generado
  - POST /webhook/reintentar_publicar     -> reintenta subir un video que quedo en 'error' (requiere DB)
  - GET  /videos                          -> panel HTML simple, lista los mp4 reales en output/
  - GET  /videos/download/{nombre_archivo} -> descarga un mp4 de output/
"""

import logging
import os
import time
import traceback
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
import requests

from config.settings import settings
import productor_mxl
from core import db, youtube_client

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("contentbotmxl")

app = FastAPI(title=settings.APP_NAME)

OUTPUT_DIR = productor_mxl.OUTPUT_DIR  # la carpeta REAL donde caen los mp4


def verificar_origen(x_webhook_secret: str | None):
    """Autenticacion compartida de todos los webhooks: exige que el header
    X-Webhook-Secret coincida exactamente con N8N_WEBHOOK_SECRET."""
    if not settings.N8N_WEBHOOK_SECRET or x_webhook_secret != settings.N8N_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="X-Webhook-Secret invalido o ausente")


@app.on_event("startup")
def _startup():
    settings.validate()
    db.inicializar()  # no-op si no hay DATABASE_URL configurada


class GenerarRequest(BaseModel):
    tema: str = Field(..., min_length=3, description="Tema del video que n8n quiere generar")
    num_escenas: int = Field(default=4, ge=2, le=8)

    # --- Modo asincrono (opcional) ---
    callback_url: str | None = Field(
        default=None,
        description="Si se manda, /webhook/generar responde al instante y avisa aqui al terminar",
    )

    # --- Publicacion automatica en YouTube (solo aplica en modo asincrono) ---
    auto_publicar: bool = Field(default=False)
    titulo_youtube: str | None = None
    descripcion_youtube: str = ""
    tags_youtube: list[str] = Field(default_factory=list)
    privacy_status: str | None = None
    publicar_en: str | None = None


class PublicarRequest(BaseModel):
    nombre_archivo: str = Field(..., min_length=3, description="Nombre del mp4 en output/")
    titulo: str = Field(..., min_length=3)
    descripcion: str = ""
    tags: list[str] = Field(default_factory=list)
    privacy_status: str | None = None
    publicar_en: str | None = None


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}


def _procesar_en_segundo_plano(payload: GenerarRequest, run_id_hint: str | None = None):
    """Corre en background cuando viene callback_url: genera el video y,
    si corresponde, lo publica; al final siempre avisa a callback_url."""
    resultado = None
    error_mensaje = None

    try:
        resultado = productor_mxl.generar_video_desde_tema(payload.tema, payload.num_escenas)
        db.registrar_generado(resultado["run_id"], resultado["titulo"], resultado["archivo"])

        if payload.auto_publicar:
            ruta_video = OUTPUT_DIR / resultado["archivo"]
            info_youtube = youtube_client.subir_video(
                ruta_video=ruta_video,
                titulo=payload.titulo_youtube or resultado["titulo"],
                descripcion=payload.descripcion_youtube,
                tags=payload.tags_youtube,
                privacy_status=payload.privacy_status,
                publicar_en=payload.publicar_en,
            )
            resultado["youtube"] = info_youtube
            db.registrar_subido(resultado["run_id"], info_youtube["video_id"], info_youtube["url"])

    except Exception as e:
        error_mensaje = str(e)
        logger.error("Fallo procesando tema '%s': %s", payload.tema, error_mensaje)
        logger.debug(traceback.format_exc())
        if run_id_hint:
            db.registrar_error(run_id_hint, error_mensaje)

    if payload.callback_url:
        cuerpo = resultado if resultado is not None else {"status": "error", "detail": error_mensaje}
        try:
            requests.post(
                payload.callback_url,
                json=cuerpo,
                headers={"X-Webhook-Secret": settings.N8N_WEBHOOK_SECRET},
                timeout=30,
            )
        except Exception:
            logger.exception("No se pudo notificar a callback_url=%s", payload.callback_url)


@app.post("/webhook/generar")
def generar(
    payload: GenerarRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str | None = Header(default=None),
):
    """
    n8n -> POST /webhook/generar
    Header: X-Webhook-Secret: <N8N_WEBHOOK_SECRET>

    - Sin callback_url: modo SINCRONO. Genera y responde en la misma
      llamada (puede tardar 1-3 min). NUNCA publica en YouTube en este
      modo, aunque se mande auto_publicar:true, para evitar timeouts largos
      sumando ademas el tiempo de subida.
    - Con callback_url: modo ASINCRONO. Responde al instante
      {"status":"aceptado"} y procesa en segundo plano; al terminar hace
      POST a callback_url con el resultado (incluye X-Webhook-Secret).
      Si ademas auto_publicar:true, sube a YouTube antes de avisar.
    """
    verificar_origen(x_webhook_secret)
    logger.info("n8n solicito generar video para tema: %s", payload.tema)

    if payload.callback_url:
        run_id_hint = time.strftime("%Y%m%d_%H%M%S")
        db.registrar_generando(run_id_hint, payload.tema)
        background_tasks.add_task(_procesar_en_segundo_plano, payload, run_id_hint)
        return {"status": "aceptado", "tema": payload.tema}

    try:
        resultado = productor_mxl.generar_video_desde_tema(payload.tema, payload.num_escenas)
        db.registrar_generado(resultado["run_id"], resultado["titulo"], resultado["archivo"])
        return resultado
    except Exception as e:
        logger.exception("Fallo generando video para tema '%s'", payload.tema)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/publicar")
def publicar(payload: PublicarRequest, x_webhook_secret: str | None = Header(default=None)):
    """
    n8n -> POST /webhook/publicar
    Sube a YouTube un mp4 que ya existe en output/ (por ejemplo, generado
    antes en modo sincrono). Paso separado a proposito de /webhook/generar
    para permitir revision humana entre generar y publicar.
    """
    verificar_origen(x_webhook_secret)

    ruta = (OUTPUT_DIR / payload.nombre_archivo).resolve()
    if OUTPUT_DIR.resolve() not in ruta.parents or not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado en output/")

    try:
        resultado = youtube_client.subir_video(
            ruta_video=ruta,
            titulo=payload.titulo,
            descripcion=payload.descripcion,
            tags=payload.tags,
            privacy_status=payload.privacy_status,
            publicar_en=payload.publicar_en,
        )
    except Exception as e:
        logger.exception("Fallo publicando '%s' en YouTube", payload.nombre_archivo)
        raise HTTPException(status_code=500, detail=str(e))

    return resultado


@app.post("/webhook/reintentar_publicar")
def reintentar_publicar(run_id: str, x_webhook_secret: str | None = Header(default=None)):
    """
    Reintenta SOLO la subida a YouTube de un video que ya se genero pero
    quedo en estado 'error' o 'generado' sin subir (ver core/db.py).
    Requiere DATABASE_URL configurada; si no, devuelve 400.
    """
    verificar_origen(x_webhook_secret)

    if not db.habilitada():
        raise HTTPException(status_code=400, detail="DATABASE_URL no esta configurada; no hay registro que reintentar")

    registro = db.obtener_por_run_id(run_id)
    if not registro or not registro.get("archivo"):
        raise HTTPException(status_code=404, detail=f"No hay un video generado registrado con run_id={run_id}")

    ruta = OUTPUT_DIR / registro["archivo"]
    if not ruta.exists():
        raise HTTPException(status_code=404, detail=f"El archivo {registro['archivo']} ya no existe en output/")

    try:
        resultado = youtube_client.subir_video(ruta_video=ruta, titulo=registro.get("titulo") or registro["tema"])
        db.registrar_subido(run_id, resultado["video_id"], resultado["url"])
        return resultado
    except Exception as e:
        db.registrar_error(run_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/videos", response_class=HTMLResponse)
def listar_videos():
    """Panel simple de solo lectura: lista los mp4 REALES de output/."""
    archivos = sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)

    html = "<html><body style='font-family:Arial;background:#0f172a;color:#f8fafc;padding:40px;'>"
    html += "<h1 style='color:#38bdf8;'>Panel de Videos - ContentBotMXL</h1>"
    if not archivos:
        html += "<p>No hay videos generados todavia.</p>"
    else:
        for ruta in archivos:
            html += (
                "<div style='background:#1e293b;padding:15px;margin-bottom:10px;border-radius:8px;"
                "display:flex;justify-content:space-between;align-items:center;'>"
                f"<span>{ruta.name}</span>"
                f"<a style='background:#0284c7;color:white;padding:10px 18px;text-decoration:none;"
                f"border-radius:5px;font-weight:bold;' href='/videos/download/{ruta.name}' target='_blank'>"
                "Descargar</a></div>"
            )
    html += "</body></html>"
    return HTMLResponse(content=html)


@app.get("/videos/download/{nombre_archivo}")
def descargar_video(nombre_archivo: str):
    ruta = (OUTPUT_DIR / nombre_archivo).resolve()
    if OUTPUT_DIR.resolve() not in ruta.parents or not ruta.exists():
        raise HTTPException(status_code=404, detail="Video no encontrado")
    return FileResponse(str(ruta), media_type="video/mp4", filename=nombre_archivo)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
