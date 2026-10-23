"""
core/db.py
Registro persistente de videos en PostgreSQL (Railway).

Objetivo puntual: si la subida a YouTube falla (por ejemplo, un token
vencido) pero el video YA se genero, este registro permite reintentar
SOLO la subida (con /webhook/reintentar_publicar) sin volver a gastar
tiempo/costo regenerando guion + voz + render con Gemini/edge-tts/moviepy.

No reemplaza nada de la arquitectura existente: sigue sin haber estado
compartido entre n8n y el backend mas alla de esto. Es solo una tabla de
seguimiento ("cola de trabajos"), no un sistema de contenido.

Requiere la variable de entorno DATABASE_URL (Railway la arma sola si
conectas el servicio de Postgres a ContentBotMXL con una referencia de
variable, ej. DATABASE_URL=${{Postgres.DATABASE_URL}}).
"""

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logger = logging.getLogger("contentbotmxl.db")

DATABASE_URL = os.getenv("DATABASE_URL", "")

_TABLA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    run_id TEXT UNIQUE NOT NULL,
    tema TEXT NOT NULL,
    titulo TEXT,
    archivo TEXT,
    estado TEXT NOT NULL DEFAULT 'generando',
    youtube_id TEXT,
    youtube_url TEXT,
    error_mensaje TEXT,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def habilitada() -> bool:
    """El resto del codigo debe llamar a esto antes de usar la DB: si no
    hay DATABASE_URL, todas las funciones de este modulo se saltan solas
    (no rompen el flujo si todavia no conectaste la base de datos)."""
    return bool(DATABASE_URL)


@contextmanager
def _conexion():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inicializar():
    """Crea la tabla si no existe. Llamar una vez al arrancar el servicio."""
    if not habilitada():
        logger.info("DATABASE_URL no configurada; el registro en base de datos esta desactivado.")
        return
    with _conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(_TABLA_SQL)
    logger.info("Base de datos lista (tabla 'videos').")


def registrar_generando(run_id: str, tema: str) -> None:
    if not habilitada():
        return
    with _conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO videos (run_id, tema, estado)
                   VALUES (%s, %s, 'generando')
                   ON CONFLICT (run_id) DO NOTHING""",
                (run_id, tema),
            )


def registrar_generado(run_id: str, titulo: str, archivo: str) -> None:
    if not habilitada():
        return
    _actualizar(run_id, estado="generado", titulo=titulo, archivo=archivo)


def registrar_subido(run_id: str, youtube_id: str, youtube_url: str) -> None:
    if not habilitada():
        return
    _actualizar(run_id, estado="subido", youtube_id=youtube_id, youtube_url=youtube_url)


def registrar_error(run_id: str, mensaje: str) -> None:
    if not habilitada():
        return
    _actualizar(run_id, estado="error", error_mensaje=mensaje[:2000])


def _actualizar(run_id: str, **campos) -> None:
    campos["actualizado_en"] = datetime.now(timezone.utc)
    columnas = ", ".join(f"{k} = %s" for k in campos)
    valores = list(campos.values()) + [run_id]
    with _conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE videos SET {columnas} WHERE run_id = %s", valores)


def obtener_por_run_id(run_id: str) -> dict | None:
    if not habilitada():
        return None
    with _conexion() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM videos WHERE run_id = %s", (run_id,))
            fila = cur.fetchone()
            return dict(fila) if fila else None


def listar_pendientes_de_subir(limite: int = 20) -> list[dict]:
    """Videos generados pero que nunca llegaron a subirse a YouTube."""
    if not habilitada():
        return []
    with _conexion() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM videos WHERE estado IN ('generado', 'error')
                   ORDER BY creado_en DESC LIMIT %s""",
                (limite,),
            )
            return [dict(f) for f in cur.fetchall()]


def listar_recientes(limite: int = 20) -> list[dict]:
    if not habilitada():
        return []
    with _conexion() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM videos ORDER BY creado_en DESC LIMIT %s", (limite,))
            return [dict(f) for f in cur.fetchall()]
