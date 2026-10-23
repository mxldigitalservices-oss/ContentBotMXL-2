# ContentBotMXL

Motor backend aislado que genera los videos verticales del canal
**mxl Aprende** (robot MXL, contenido educativo infantil). Diseñado para
correr como el **Servidor 2** de una arquitectura de dos servidores
independientes:

- **Servidor 1 — n8n (externo):** orquestador principal. Dispara los
  flujos, decide cuándo generar un video, y llama al webhook de este
  servicio.
- **Servidor 2 — este repo (Railway):** motor aislado. No orquesta nada,
  no llama a n8n, **no usa base de datos**. Todo lo que necesita
  (imágenes del robot MXL y `prompt_maestro.txt`) vive versionado en este
  mismo repositorio de GitHub, del cual Railway despliega directamente.

## Flujo

```
n8n  --POST /webhook/generar {"tema": "..."}-->  ContentBotMXL (Railway)
                                                       |
                                                       v
                                          Gemini genera el guion
                                          (usa prompt_maestro.txt)
                                                       |
                                                       v
                                    edge-tts sintetiza la voz
                                          de cada escena
                                                       |
                                                       v
                                  Se arma el video con las imagenes
                                  de assets/mxl_robot/<emocion>/,
                                  musica de assets/musica/ y efectos
                                  de assets/efectos_sonido/ (Ken Burns,
                                  crossfade, fades in/out)
                                                       |
                                                       v
n8n  <---------- estructura final del video (JSON) ----------
                                                       |
                                                       v (opcional)
n8n  --POST /webhook/publicar {"nombre_archivo": "...", "titulo": "..."}-->
                                                       |
                                                       v
                                          Se sube el mp4 a YouTube
                                                       |
                                                       v
n8n  <---------- {"video_id": "...", "url": "https://youtu.be/..."} ----------
```

`/webhook/generar` y `/webhook/publicar` son dos pasos separados a
proposito: n8n puede encadenarlos en el mismo flujo para publicar 100%
automatico, o dejar un paso intermedio de revision humana antes de subir a
YouTube (por ejemplo, un nodo de aprobacion o notificacion de Slack entre
ambos).

## Variables de entorno

| Variable | Uso | Obligatoria |
|---|---|---|
| `GEMINI_API_KEY` | Generacion del guion con Gemini | Si |
| `N8N_WEBHOOK_SECRET` | Autenticacion del webhook (header `X-Webhook-Secret`) | Si |
| `TTS_VOZ` | Voz neuronal de edge-tts (por defecto `es-MX-DaliaNeural`) | No |
| `YOUTUBE_CLIENT_ID` | Credencial OAuth2 para subir a YouTube | Solo si se usa `/webhook/publicar` |
| `YOUTUBE_CLIENT_SECRET` | Credencial OAuth2 para subir a YouTube | Solo si se usa `/webhook/publicar` |
| `YOUTUBE_REFRESH_TOKEN` | Token de larga duracion (ver mas abajo) | Solo si se usa `/webhook/publicar` |
| `YOUTUBE_PRIVACY_STATUS` | `private` \| `unlisted` \| `public` (por defecto `private`) | No |
| `YOUTUBE_MADE_FOR_KIDS` | `true`/`false` (por defecto `true`) | No |

edge-tts es gratuito y no requiere API key ni cuenta de servicio. Las
variables de YouTube son opcionales: si no estan configuradas, el motor
sigue generando videos con normalidad; solo `/webhook/publicar` falla con
un mensaje claro indicando que falta configurar.

No hay base de datos en ningun punto del flujo.

## Endpoints

- `GET /health` — healthcheck de Railway.
- `POST /webhook/generar` — endpoint que llama n8n.
  Header: `X-Webhook-Secret: <N8N_WEBHOOK_SECRET>`
  Body: `{"tema": "Los colores primarios", "num_escenas": 4}`
  Responde de forma **síncrona** con la estructura final:
  ```json
  {
    "titulo": "Los colores primarios",
    "run_id": "20260719_120500",
    "archivo": "los_colores_primarios_20260719_120500.mp4",
    "ruta_relativa": "output/los_colores_primarios_20260719_120500.mp4",
    "duracion_total_seg": 24.8,
    "musica": "assets/musica/fondo_alegre_01.mp3",
    "efectos_transicion_usados": 3,
    "escenas": [
      {"orden": 1, "emocion": "feliz", "texto": "...", "imagen": "assets/mxl_robot/feliz/01.png", "duracion_seg": 4.2}
    ]
  }
  ```
  Configura un timeout de 2-3 minutos en el nodo HTTP Request de n8n:
  Gemini + TTS + render de video no son instantáneos.

  Efectos aplicados automáticamente al render (ver `productor_mxl.py`):
  Ken Burns por escena (zoom in/out aleatorio), disolvencia cruzada
  (crossfade) entre escenas, fade in/out a negro al inicio/final del
  video, suavizado de cada línea de voz, música de fondo en loop con
  fade in/out (si hay pistas en `assets/musica/`), y un efecto de
  transición tipo "whoosh" sincronizado con cada corte (si hay pistas en
  `assets/efectos_sonido/`). Música y sfx son 100% opcionales: si esas
  carpetas están vacías, el video sale igual, solo sin ese extra.

- `GET /output/{nombre_archivo}` — descarga el mp4 generado (mismo header
  de autenticación). Usa el valor de `archivo` de la respuesta anterior.

- `POST /webhook/publicar` — sube a YouTube un mp4 que ya está en `output/`.
  Header: `X-Webhook-Secret: <N8N_WEBHOOK_SECRET>`
  Body:
  ```json
  {
    "nombre_archivo": "los_colores_primarios_20260719_120500.mp4",
    "titulo": "Los colores primarios | mxl Aprende",
    "descripcion": "Un video para aprender los colores primarios con MXL.",
    "tags": ["niños", "educativo", "colores"],
    "privacy_status": "private"
  }
  ```
  Responde:
  ```json
  {"video_id": "abc123XYZ", "url": "https://youtu.be/abc123XYZ", "privacy_status": "private"}
  ```
  Requiere `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` y
  `YOUTUBE_REFRESH_TOKEN` configurados en Railway (ver sección siguiente).

### Cómo conectar YouTube (una sola vez)

La YouTube Data API v3 no permite subir videos a un canal usando una
cuenta de servicio: hace falta autorizar explícitamente la cuenta dueña
del canal. Por eso se usa un **refresh token** de larga duración, que se
consigue una única vez desde tu máquina local (nunca desde Railway):

1. En [Google Cloud Console](https://console.cloud.google.com/), habilita
   **YouTube Data API v3** y crea credenciales OAuth2 tipo **Desktop App**.
2. Descarga ese JSON y guárdalo como `client_secret_youtube.json` en la
   raíz del repo (ya está en `.gitignore`, nunca se sube a GitHub).
3. Corre localmente:
   ```bash
   pip install google-auth-oauthlib
   python3 scripts/obtener_refresh_token_youtube.py
   ```
4. Se abre el navegador; inicia sesión con la cuenta **dueña del canal**
   de YouTube y autoriza. El script imprime `YOUTUBE_CLIENT_ID`,
   `YOUTUBE_CLIENT_SECRET` y `YOUTUBE_REFRESH_TOKEN`.
5. Copia esos 3 valores como Environment Variables en Railway.

El refresh token no expira mientras no revoques el acceso manualmente
desde la cuenta de Google. Por defecto los videos se suben como
`private` y declarados "hecho para niños" (`YOUTUBE_MADE_FOR_KIDS=true`,
requisito legal de YouTube/COPPA para contenido infantil); cambia
`YOUTUBE_PRIVACY_STATUS` cuando quieras publicarlos como `public`.

## Estructura del repo

```
assets/mxl_robot/<emocion>/   -> imágenes del robot MXL por emoción
                                  (feliz, pensativo, sorprendido, con_amigos, hablando)
assets/musica/                -> pistas de fondo opcionales (.mp3/.wav/.ogg)
assets/efectos_sonido/        -> efectos de transición opcionales (.mp3/.wav/.ogg)
prompt_maestro.txt            -> instrucción base que Gemini usa para escribir el guion
core/gemini_client.py         -> llama a Gemini y genera el guion (titulo + escenas)
core/tts_client.py            -> sintetiza la voz con edge-tts
core/asset_manager.py         -> indexa y elige imágenes por emoción
core/youtube_client.py        -> sube el mp4 final a YouTube (OAuth2 + refresh token)
scripts/obtener_refresh_token_youtube.py -> herramienta local de un solo uso (ver arriba)
productor_mxl.py              -> ensambla el video final (moviepy) + efectos
main.py                       -> API FastAPI / webhooks para n8n
```

## Uso manual (sin pasar por n8n)

También se puede procesar un lote de guiones JSON locales, sin Gemini,
colocándolos en `data/guiones/pendientes/`:

```bash
python3 productor_mxl.py                    # procesa todos los pendientes
python3 productor_mxl.py ruta/al/guion.json  # procesa uno especifico
```

Cada JSON debe tener la forma:
```json
{"titulo": "...", "escenas": [{"emocion": "feliz", "texto": "..."}]}
```
