"""
drive.py
--------
Responsabilidad única: toda la comunicación con Google Drive.

Qué hace:
  - Autenticarse con OAuth 2.0 (abre el navegador la primera vez,
    luego guarda el token en .credentials/token.json y no vuelve a pedir login).
  - Listar archivos Excel dentro de una carpeta de Drive.
  - Descargar archivos a data/raw/.
  - (Futuro) Subir archivos modificados de vuelta a Drive.

Configuración necesaria (en archivo .env):
  DRIVE_FOLDER_ID   → ID de la carpeta de Drive donde están los Excels.
                       Se obtiene de la URL: drive.google.com/drive/folders/<ID>
  GOOGLE_CREDENTIALS_PATH → Ruta al archivo credentials.json descargado de
                             Google Cloud Console (por defecto: .credentials/credentials.json)
"""

import os
import io
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Solo se pide permiso de lectura/escritura de Drive (archivos creados por la app).
# Si en el futuro se necesita acceso completo, cambiar a "drive".
SCOPES = ["https://www.googleapis.com/auth/drive"]

BASE_DIR = Path(__file__).parent.parent
CREDENTIALS_DIR = BASE_DIR / ".credentials"
TOKEN_PATH = CREDENTIALS_DIR / "token.json"
DEFAULT_CREDENTIALS_PATH = CREDENTIALS_DIR / "credentials.json"
DATA_RAW_DIR = BASE_DIR / "data" / "raw"


def _get_credentials_path() -> Path:
    env_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if not env_path:
        return DEFAULT_CREDENTIALS_PATH
    p = Path(env_path)
    # Si es relativa, la resuelve desde la raíz del proyecto (no desde el cwd)
    return p if p.is_absolute() else BASE_DIR / p


def autenticar():
    """
    Autentica con Google Drive usando OAuth 2.0.

    - Si ya existe un token guardado y es válido, lo usa directamente.
    - Si el token venció, lo refresca automáticamente.
    - Si no hay token, abre el navegador para pedir permiso (solo la primera vez).

    Retorna el servicio de Drive listo para usar.
    """
    CREDENTIALS_DIR.mkdir(exist_ok=True)
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = _get_credentials_path()
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"No se encontró el archivo de credenciales en: {credentials_path}\n"
                    "Descargalo desde Google Cloud Console → APIs y servicios → Credenciales\n"
                    "y guardalo en: .credentials/credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def listar_excels(folder_id: str) -> list[dict]:
    """
    Lista todos los archivos Excel (.xlsx) dentro de la carpeta indicada.

    Retorna una lista de dicts con 'id', 'name' y 'modifiedTime'.
    """
    servicio = autenticar()
    query = (
        f"'{folder_id}' in parents"
        " and mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
        " and trashed=false"
    )
    resultado = (
        servicio.files()
        .list(q=query, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc")
        .execute()
    )
    return resultado.get("files", [])


def descargar_excel(file_id: str, nombre_destino: str) -> Path:
    """
    Descarga un archivo de Drive a data/raw/<nombre_destino>.

    Retorna el Path del archivo descargado.
    """
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    destino = DATA_RAW_DIR / nombre_destino

    servicio = autenticar()
    request = servicio.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    listo = False
    while not listo:
        _, listo = downloader.next_chunk()

    destino.write_bytes(buffer.getvalue())
    return destino


def sincronizar_desde_drive(folder_id: str) -> list[str]:
    """
    Descarga todos los Excels de la carpeta de Drive a data/raw/.

    Retorna una lista con los nombres de los archivos descargados.
    """
    archivos = listar_excels(folder_id)

    if not archivos:
        raise ValueError(
            f"No se encontraron archivos Excel en la carpeta de Drive (ID: {folder_id}).\n"
            "Verificá que el ID de carpeta sea correcto y que hayas compartido la carpeta con tu cuenta."
        )

    descargados = []
    for archivo in archivos:
        descargar_excel(archivo["id"], archivo["name"])
        descargados.append(archivo["name"])

    return descargados


def subir_excel(ruta_local: Path, folder_id: str) -> str:
    """
    Sube o actualiza un archivo Excel en la carpeta de Drive.

    Si ya existe un archivo con el mismo nombre en la carpeta, lo reemplaza.
    Si no existe, lo crea.

    Retorna el ID del archivo en Drive.
    """
    from googleapiclient.http import MediaFileUpload

    servicio = autenticar()
    nombre = ruta_local.name

    # Buscar si ya existe el archivo en Drive
    archivos_existentes = listar_excels(folder_id)
    archivo_existente = next((a for a in archivos_existentes if a["name"] == nombre), None)

    media = MediaFileUpload(
        str(ruta_local),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=True,
    )

    if archivo_existente:
        # Actualizar el archivo existente
        archivo = (
            servicio.files()
            .update(fileId=archivo_existente["id"], media_body=media)
            .execute()
        )
    else:
        # Crear archivo nuevo en la carpeta
        metadata = {"name": nombre, "parents": [folder_id]}
        archivo = (
            servicio.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )

    return archivo["id"]
