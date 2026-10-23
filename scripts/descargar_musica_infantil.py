#!/usr/bin/env python3
"""
scripts/descargar_musica_infantil.py
Herramienta de UN SOLO USO, para correr LOCAL (nunca en Railway).

Descarga pistas instrumentales, alegres y aptas para contenido infantil
desde Freesound.org (licencia Creative Commons 0 - CC0: uso comercial
libre, sin necesidad de atribucion) y las guarda directamente en
assets/musica/, listas para comitear al repo.

Requisitos previos:
  1. Cuenta gratuita en https://freesound.org
  2. API key gratuita en https://freesound.org/apiv2/apply/ (aprobacion
     casi inmediata)
  3. pip install requests

Uso:
    export FREESOUND_API_KEY="tu_api_key_aqui"
    python3 scripts/descargar_musica_infantil.py
    python3 scripts/descargar_musica_infantil.py --cantidad 3
    python3 scripts/descargar_musica_infantil.py --termino "cheerful ukulele"

Despues de correrlo:
    git add assets/musica/
    git commit -m "Agregar musica de fondo instrumental para videos infantiles"
    git push origin main
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
MUSICA_DIR = BASE_DIR / "assets" / "musica"

# Terminos de busqueda orientados a musica infantil/ludica e instrumental
# (sin voces, para no chocar con la narracion del video).
TERMINOS_DEFAULT = [
    "kids happy ukulele",
    "children playful instrumental",
    "cartoon fun background",
    "cheerful marimba",
    "playground upbeat instrumental",
    "kids background music",
]

# Duracion minima/maxima aceptada (segundos). El motor hace loop si la
# pista es mas corta que el video, asi que no hace falta que sea larga.
DURACION_MIN = 15
DURACION_MAX = 240


def slugify(texto: str) -> str:
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", texto.lower()).strip("_")
    return texto[:40]


def buscar_freesound(api_key: str, termino: str, cantidad: int) -> list[dict]:
    url = "https://freesound.org/apiv2/search/text/"
    params = {
        "query": termino,
        "token": api_key,
        # Solo CC0: uso comercial libre, sin atribucion obligatoria.
        "filter": f'duration:[{DURACION_MIN} TO {DURACION_MAX}] license:"Creative Commons 0"',
        "fields": "id,name,previews,duration,license,username",
        "page_size": cantidad,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("results", [])


def descargar(url: str, destino: Path) -> None:
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(destino, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def main():
    parser = argparse.ArgumentParser(description="Descarga musica de fondo infantil (CC0) a assets/musica/")
    parser.add_argument("--termino", type=str, default=None, help="Buscar un solo termino especifico")
    parser.add_argument("--cantidad", type=int, default=2, help="Pistas a descargar por termino")
    args = parser.parse_args()

    api_key = os.environ.get("FREESOUND_API_KEY", "")
    if not api_key:
        print("ERROR: falta la variable de entorno FREESOUND_API_KEY.")
        print("Consiguela gratis en https://freesound.org/apiv2/apply/ y corre:")
        print('  export FREESOUND_API_KEY="tu_api_key"')
        sys.exit(1)

    MUSICA_DIR.mkdir(parents=True, exist_ok=True)
    terminos = [args.termino] if args.termino else TERMINOS_DEFAULT

    existentes = {p.name for p in MUSICA_DIR.glob("*.mp3")}
    total_nuevas = 0

    for termino in terminos:
        print(f"\n== Buscando: '{termino}' ==")
        try:
            resultados = buscar_freesound(api_key, termino, args.cantidad)
        except requests.RequestException as e:
            print(f"  Error buscando '{termino}': {e}")
            continue

        if not resultados:
            print("  Sin resultados con licencia CC0 para este termino.")
            continue

        for item in resultados:
            preview_url = item.get("previews", {}).get("preview-hq-mp3")
            if not preview_url:
                continue

            nombre_archivo = f"{slugify(item['name'])}_{item['id']}.mp3"
            if nombre_archivo in existentes:
                print(f"  Ya existe: {nombre_archivo}, se omite.")
                continue

            destino = MUSICA_DIR / nombre_archivo
            duracion = item.get("duration", 0)
            print(f"  Descargando: {item['name']} ({duracion:.1f}s) -> {nombre_archivo}")

            try:
                descargar(preview_url, destino)
            except requests.RequestException as e:
                print(f"    Error al descargar: {e}")
                continue

            existentes.add(nombre_archivo)
            total_nuevas += 1
            time.sleep(1)  # respetar rate limit de la API

    print(f"\n=== Listo: {total_nuevas} pistas nuevas en {MUSICA_DIR} ===")
    if total_nuevas > 0:
        print("\nSiguiente paso:")
        print("  git add assets/musica/")
        print('  git commit -m "Agregar musica de fondo instrumental para videos infantiles"')
        print("  git push origin main")


if __name__ == "__main__":
    main()
