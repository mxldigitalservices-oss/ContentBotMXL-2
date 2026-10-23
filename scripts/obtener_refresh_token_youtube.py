#!/usr/bin/env python3
"""
scripts/obtener_refresh_token_youtube.py
Herramienta de UN SOLO USO para conseguir el refresh token de YouTube.

Se corre UNICAMENTE en tu maquina local (nunca en Railway), porque
necesita abrir un navegador para que autorices la cuenta del canal.

Requisitos previos:
  1. En Google Cloud Console: crea un proyecto (o usa el mismo de Gemini),
     habilita "YouTube Data API v3", y crea credenciales OAuth2 tipo
     "Desktop App" (APIs & Services > Credentials > Create credentials).
  2. Descarga el JSON de esas credenciales y guardalo como
     client_secret_youtube.json en la raiz del proyecto. Ese archivo esta
     en .gitignore: nunca se sube al repo.

Uso:
    pip install google-auth-oauthlib
    python3 scripts/obtener_refresh_token_youtube.py

Se abre el navegador, inicias sesion con la cuenta DUEÑA del canal de
YouTube (no la de desarrollador si son distintas), autorizas el scope de
subida, y el script imprime las 3 variables listas para copiar a Railway.

El refresh token no expira mientras no revoques el acceso manualmente
desde https://myaccount.google.com/permissions ni cambies la contraseña
de la cuenta de Google.
"""

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = Path(__file__).resolve().parent.parent / "client_secret_youtube.json"


def main():
    if not CLIENT_SECRETS_FILE.exists():
        print(
            f"No se encontro {CLIENT_SECRETS_FILE}.\n"
            "Descarga el JSON de credenciales OAuth2 (tipo 'Desktop App') desde "
            "Google Cloud Console y guardalo con ese nombre exacto en la raiz del repo.",
            file=sys.stderr,
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
    credenciales = flow.run_local_server(port=0)

    if not credenciales.refresh_token:
        print(
            "\nGoogle no devolvio un refresh_token. Esto pasa si ya habias "
            "autorizado esta app antes con la misma cuenta. Revoca el acceso en "
            "https://myaccount.google.com/permissions y corre este script de nuevo.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n=== Copia estas 3 variables en las Environment Variables de Railway ===\n")
    print(f"YOUTUBE_CLIENT_ID={credenciales.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={credenciales.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={credenciales.refresh_token}")
    print(
        "\nGuardalas ahora: por seguridad este refresh token no se vuelve a "
        "mostrar (si lo pierdes, corre este script de nuevo)."
    )


if __name__ == "__main__":
    main()
