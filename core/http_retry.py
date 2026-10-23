"""
core/http_retry.py
Utilidad compartida: reintenta una peticion HTTP con espera progresiva
cuando Google devuelve 429 (limite de peticiones) o 503 (servicio
temporalmente ocupado). La usan gemini_client.py y tts_client.py.

IMPORTANTE sobre el 429 de Google: la API de Generative Language NO manda
el tiempo de espera en el header HTTP "Retry-After". Lo manda DENTRO del
body JSON, en error.details[], como un objeto RetryInfo con un campo
"retryDelay" (ej. "31s"). Si solo miramos el header (como hacia la version
anterior de este archivo), esa condicion nunca se cumple y siempre se cae
al backoff generico, sin relacion con lo que Google realmente pide.

Ademas, el body trae (en un objeto QuotaFailure) el "quotaId" exacto que se
toco. Si ese id contiene "PerDay", ningun backoff de segundos va a servir:
hay que esperar horas (el cupo diario resetea a medianoche Pacific Time).
En ese caso no tiene sentido gastar los reintentos: se corta al toque con
un mensaje claro.
"""

import json
import logging
import re
import time

import requests

logger = logging.getLogger("contentbotmxl.http_retry")

CODIGOS_REINTENTABLES = (429, 503)


class GoogleAPIError(RuntimeError):
    """
    Error de la API de Google con el detalle real (no el texto generico de
    requests.raise_for_status()). Su str() ya trae todo lo que necesitas
    ver en logs / respuesta HTTP: status code, mensaje de Google, quotaId
    tocado y si es un limite diario.
    """

    def __init__(self, resp: requests.Response, detalle: dict):
        self.status_code = resp.status_code
        self.mensaje_google = detalle.get("mensaje", resp.text[:500])
        self.quota_id = detalle.get("quota_id")
        self.es_limite_diario = detalle.get("es_limite_diario", False)
        self.retry_delay_seg = detalle.get("retry_delay_seg")

        partes = [f"Google devolvio {self.status_code}: {self.mensaje_google}"]
        if self.quota_id:
            partes.append(f"cuota tocada: {self.quota_id}")
        if self.es_limite_diario:
            partes.append(
                "es un limite DIARIO (RPD) - no se soluciona esperando segundos, "
                "hay que esperar al reset (medianoche Pacific Time) o subir de tier/plan"
            )
        elif self.retry_delay_seg is not None:
            partes.append(f"Google pidio esperar {self.retry_delay_seg}s")
        super().__init__(" | ".join(partes))


def _parsear_error_google(resp: requests.Response) -> dict:
    """
    Extrae mensaje, quotaId y retryDelay del body de error de Google.
    Devuelve {} si el body no trae la forma esperada (no es fatal, se
    usa lo que haya disponible).
    """
    detalle = {}
    try:
        cuerpo = resp.json()
    except (json.JSONDecodeError, ValueError):
        return detalle

    error = cuerpo.get("error", {})
    detalle["mensaje"] = error.get("message")

    for item in error.get("details", []):
        tipo = item.get("@type", "")

        if tipo.endswith("QuotaFailure"):
            violaciones = item.get("violations", [])
            if violaciones:
                quota_id = violaciones[0].get("quotaId", "")
                detalle["quota_id"] = quota_id
                detalle["es_limite_diario"] = "PerDay" in quota_id or "Day" in quota_id

        elif tipo.endswith("RetryInfo"):
            retry_delay = item.get("retryDelay", "")
            match = re.match(r"([\d.]+)s?", retry_delay)
            if match:
                detalle["retry_delay_seg"] = float(match.group(1))

    return detalle


def post_con_reintentos(
    url: str,
    max_intentos: int = 4,
    espera_base_seg: float = 5.0,
    **kwargs,
) -> requests.Response:
    """
    Hace requests.post(url, **kwargs) y reintenta automaticamente si Google
    devuelve 429/503. Lee el body de error de Google (no solo el header) para
    saber cuanto esperar de verdad, y si el limite tocado es diario corta de
    inmediato en vez de agotar los reintentos en vano.

    Lanza GoogleAPIError (con el detalle real de Google) si se agotan los
    intentos o si detecta un limite diario. Para errores que no sean 429/503
    devuelve la respuesta tal cual (quien llama decide que hacer con ella).
    """
    ultimo_error = None

    for intento in range(1, max_intentos + 1):
        resp = requests.post(url, **kwargs)

        if resp.status_code not in CODIGOS_REINTENTABLES:
            return resp

        ultimo_error = resp
        detalle = _parsear_error_google(resp)

        if detalle.get("es_limite_diario"):
            logger.error(
                "Google devolvio %s por limite DIARIO (quotaId=%s). No se reintenta: %s",
                resp.status_code, detalle.get("quota_id"), detalle.get("mensaje"),
            )
            raise GoogleAPIError(resp, detalle)

        if intento == max_intentos:
            break

        espera = detalle.get("retry_delay_seg")
        if espera is None:
            espera = espera_base_seg * (2 ** (intento - 1))
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    espera = max(espera, float(retry_after))
                except ValueError:
                    pass

        logger.warning(
            "Google devolvio %s (intento %s/%s, quotaId=%s). Esperando %.0fs antes de reintentar...",
            resp.status_code, intento, max_intentos, detalle.get("quota_id"), espera,
        )
        time.sleep(espera)

    raise GoogleAPIError(ultimo_error, _parsear_error_google(ultimo_error))
