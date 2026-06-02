"""
sync_drive.py — Descarga los Excel de Google Drive para el chatbot.

La persona responsable solo necesita subir los archivos actualizados a la
carpeta de Drive compartida. Este script los descarga a data/raw/.

CONFIGURACIÓN (solo la primera vez):
  - Asegurate de que .credentials/service_account.json exista.
  - Verificá que DRIVE_FOLDER_ID esté definido en .env.

USO:
  python -X utf8 scripts/sync_drive.py              # descarga archivos
  python -X utf8 scripts/sync_drive.py --dry-run    # muestra qué descargaría sin tocar nada
"""

import argparse
import io
import logging
import os
import pathlib
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "sync_drive.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Variables de entorno ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
RAW_DIR   = ROOT / "data" / "raw"

# ── Archivos esperados en Drive ───────────────────────────────────────────────
# Clave = nombre local en data/raw/ que el chatbot espera.
# Valor = palabras clave para encontrarlo en Drive aunque el nombre cambie de fecha.
ARCHIVOS = {
    "CARTERA AL 11032026.xlsx":             ["cartera"],
    "CONTROL DE INST. MINISPLIT 2026.xlsx": ["minisplit", "control inst"],
    "reporteMensual_FACTURAS.xlsx":         ["facturas"],
}


# ── Validación ────────────────────────────────────────────────────────────────

def validar_config() -> None:
    errores = []
    if not FOLDER_ID:
        errores.append("DRIVE_FOLDER_ID no definido en .env")
    sa_path = ROOT / ".credentials" / "service_account.json"
    oauth_path = ROOT / ".credentials" / "credentials.json"
    if not sa_path.exists() and not oauth_path.exists():
        errores.append(
            "No se encontraron credenciales de Google Drive.\n"
            "  → Copiá service_account.json a .credentials/service_account.json"
        )
    if errores:
        for e in errores:
            log.error(e)
        sys.exit(1)


# ── Drive ─────────────────────────────────────────────────────────────────────

def listar_xlsx_en_carpeta(servicio) -> list[dict]:
    mime  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    query = f"'{FOLDER_ID}' in parents and mimeType='{mime}' and trashed=false"
    res   = servicio.files().list(
        q=query, fields="files(id, name, modifiedTime, size)"
    ).execute()
    return res.get("files", [])


def encontrar_coincidencia(nombre_local: str, keywords: list[str], en_drive: list[dict]) -> dict | None:
    nombre_lower = nombre_local.lower()
    for f in en_drive:
        if f["name"].lower() == nombre_lower:
            return f
    for f in en_drive:
        if any(kw in f["name"].lower() for kw in keywords):
            return f
    return None


def descargar_archivo(servicio, file_id: str, destino: pathlib.Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload
    request = servicio.files().get_media(fileId=file_id)
    buffer  = io.BytesIO()
    dl      = MediaIoBaseDownload(buffer, request, chunksize=10 * 1024 * 1024)
    done    = False
    while not done:
        _, done = dl.next_chunk()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(buffer.getvalue())


# ── Sincronización ────────────────────────────────────────────────────────────

def sync(dry_run: bool = False) -> int:
    log.info("=" * 58)
    log.info(f"SYNC DRIVE (Chatbot)  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Carpeta Drive ID: {FOLDER_ID}")

    validar_config()

    from src.drive import autenticar
    try:
        servicio = autenticar()
        en_drive = listar_xlsx_en_carpeta(servicio)
    except Exception as e:
        log.error(f"Error conectando con Google Drive: {e}")
        sys.exit(1)

    if not en_drive:
        log.warning("No se encontraron archivos xlsx en la carpeta.")
        return 0

    log.info(f"Archivos en Drive ({len(en_drive)}): {[f['name'] for f in en_drive]}")
    log.info("-" * 58)

    descargados = 0
    for nombre_local, keywords in ARCHIVOS.items():
        match = encontrar_coincidencia(nombre_local, keywords, en_drive)
        if not match:
            log.warning(f"  ⚠  No encontrado en Drive: '{nombre_local}' (keywords: {keywords})")
            continue

        destino = RAW_DIR / nombre_local
        tam_kb  = int(match.get("size", 0)) // 1024
        mod     = match["modifiedTime"][:10]

        if dry_run:
            log.info(f"  [DRY-RUN] '{match['name']}' → {nombre_local}  ({tam_kb} KB, mod. {mod})")
            continue

        log.info(f"  ↓  '{match['name']}'  ({tam_kb} KB, mod. {mod})")
        descargar_archivo(servicio, match["id"], destino)
        log.info(f"     Guardado: data/raw/{nombre_local}")
        descargados += 1

    if not dry_run:
        log.info(f"Descarga: {descargados}/{len(ARCHIVOS)} archivos OK")

    return descargados


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simula sin descargar nada")
    args = parser.parse_args()

    sync(dry_run=args.dry_run)
    log.info("=" * 58)
