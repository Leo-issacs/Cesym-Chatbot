"""
drive.py
--------
Responsabilidad única: toda la comunicación con Google Drive.

Qué hace:
  - Autenticarse con Service Account (preferido, sin navegador) o con OAuth 2.0 como fallback.
  - Listar archivos Excel dentro de una carpeta de Drive.
  - Descargar archivos a data/raw/.
  - Subir archivos (logs, reportes, backups) de vuelta a Drive.

Autenticación (en orden de prioridad):
  1. Service Account vía variable de entorno: GOOGLE_SERVICE_ACCOUNT_JSON
     ← preferido en cloud (Railway): el JSON completo va en una variable, sin archivos.
  2. Service Account vía archivo: .credentials/service_account.json
     ← para ejecución local headless.
  3. OAuth 2.0: .credentials/credentials.json
     ← último recurso; requiere navegador la primera vez y su refresh token expira.

Configuración necesaria (en archivo .env):
  DRIVE_FOLDER_ID   → ID de la carpeta de Drive donde están los Excels.
  GOOGLE_SERVICE_ACCOUNT_JSON → (Recomendado en cloud) JSON completo de la
                                Service Account. Ver .env.example.
  GOOGLE_CREDENTIALS_PATH → (Opcional) ruta al OAuth credentials.json.
"""

import os
import io
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# El bot ESCRIBE a Drive (sube backups, logs y reportes), por eso pedimos el
# scope completo 'drive' y NO 'drive.readonly'.
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Nombre EXACTO de la variable de entorno con el JSON completo de la Service Account.
# En Railway se configura con el contenido íntegro del archivo .json de la cuenta
# cesym-sync@cesym-hvac.iam.gserviceaccount.com.
SERVICE_ACCOUNT_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"

BASE_DIR = Path(__file__).parent.parent
CREDENTIALS_DIR = BASE_DIR / ".credentials"
TOKEN_PATH = CREDENTIALS_DIR / "token.json"
DEFAULT_CREDENTIALS_PATH = CREDENTIALS_DIR / "credentials.json"
SERVICE_ACCOUNT_PATH = CREDENTIALS_DIR / "service_account.json"
DATA_RAW_DIR = BASE_DIR / "data" / "raw"


def init_credenciales_desde_env():
    """
    En despliegues cloud (Railway/Render) no hay archivos locales.
    Lee las credenciales de Google desde variables de entorno (base64),
    las decodifica y las escribe en disco para que autenticar() las encuentre.

    Variables esperadas:
      GOOGLE_CREDENTIALS_JSON → contenido de credentials.json en base64
      GOOGLE_TOKEN_JSON       → contenido de token.json en base64
    """
    import base64

    CREDENTIALS_DIR.mkdir(exist_ok=True)

    raw_creds = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if raw_creds and not DEFAULT_CREDENTIALS_PATH.exists():
        DEFAULT_CREDENTIALS_PATH.write_text(
            base64.b64decode(raw_creds).decode("utf-8")
        )

    raw_token = os.getenv("GOOGLE_TOKEN_JSON")
    if raw_token and not TOKEN_PATH.exists():
        TOKEN_PATH.write_text(
            base64.b64decode(raw_token).decode("utf-8")
        )


def _get_credentials_path() -> Path:
    env_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if not env_path:
        return DEFAULT_CREDENTIALS_PATH
    p = Path(env_path)
    # Si es relativa, la resuelve desde la raíz del proyecto (no desde el cwd)
    return p if p.is_absolute() else BASE_DIR / p


def _service_account_info_desde_env() -> dict | None:
    """
    Lee el JSON de la Service Account desde la variable de entorno
    GOOGLE_SERVICE_ACCOUNT_JSON y lo parsea a dict.

    Acepta dos formatos para tolerar cómo se pegue en Railway:
      - JSON crudo (lo normal): se parsea con json.loads directamente.
      - JSON en base64 (fallback): si json.loads falla, intenta decodificar base64
        y luego parsear. Útil si el panel reescapa saltos de línea.

    Retorna el dict de credenciales, o None si la variable no está definida.
    Lanza ValueError si la variable existe pero no contiene un JSON válido.
    """
    import json

    raw = os.getenv(SERVICE_ACCOUNT_ENV)
    if not raw or not raw.strip():
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import base64
        try:
            decodificado = base64.b64decode(raw).decode("utf-8")
            return json.loads(decodificado)
        except Exception as e:
            raise ValueError(
                f"{SERVICE_ACCOUNT_ENV} está definida pero no es un JSON válido "
                f"(ni crudo ni base64): {e}"
            ) from e


def _autenticar_service_account_desde_env(info: dict):
    """Autentica con Service Account usando el dict de credenciales (sin archivo)."""
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _autenticar_service_account():
    """Autentica con Service Account desde archivo. No requiere navegador ni interacción humana."""
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_PATH),
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _autenticar_oauth():
    """
    Autentica con OAuth 2.0.
    - Usa el token guardado si es válido o lo refresca.
    - Si no hay token, abre el navegador (solo la primera vez).
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


def autenticar():
    """
    Autentica con Google Drive.

    Prioridad:
      1. Service Account desde variable de entorno (GOOGLE_SERVICE_ACCOUNT_JSON)
         → preferido en cloud, no requiere archivos ni navegador, no expira.
      2. Service Account desde archivo (.credentials/service_account.json)
         → para ejecución local headless.
      3. OAuth 2.0 → último recurso (refresh token que puede expirar).
    """
    info = _service_account_info_desde_env()
    if info is not None:
        return _autenticar_service_account_desde_env(info)
    if SERVICE_ACCOUNT_PATH.exists():
        return _autenticar_service_account()
    return _autenticar_oauth()


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


def listar_csvs(folder_id: str) -> list[dict]:
    """
    Lista todos los archivos CSV dentro de la carpeta indicada.

    Retorna una lista de dicts con 'id', 'name' y 'modifiedTime'.
    """
    servicio = autenticar()
    query = (
        f"'{folder_id}' in parents"
        " and (mimeType='text/csv' or mimeType='text/plain')"
        " and trashed=false"
    )
    resultado = (
        servicio.files()
        .list(q=query, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc")
        .execute()
    )
    # Filtrar solo los que terminan en .csv por si hay otros .txt
    return [a for a in resultado.get("files", []) if a["name"].endswith(".csv")]


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
    Descarga todos los Excels (.xlsx) y reportes (.csv) de la carpeta de Drive a data/raw/.

    Retorna una lista con los nombres de los archivos descargados.
    """
    excels = listar_excels(folder_id)
    csvs = listar_csvs(folder_id)
    archivos = excels + csvs

    if not archivos:
        raise ValueError(
            f"No se encontraron archivos en la carpeta de Drive (ID: {folder_id}).\n"
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


def subir_archivo(ruta_local: Path, folder_id: str, mime_type: str = "text/plain") -> str:
    """
    Sube cualquier archivo (no solo Excel) a Drive.
    Si ya existe con el mismo nombre, lo reemplaza.
    Retorna el ID del archivo en Drive.
    """
    from googleapiclient.http import MediaFileUpload
    servicio = autenticar()
    nombre = ruta_local.name

    query = f"'{folder_id}' in parents and name='{nombre}' and trashed=false"
    existentes = servicio.files().list(q=query, fields="files(id)").execute().get("files", [])

    media = MediaFileUpload(str(ruta_local), mimetype=mime_type, resumable=False)

    if existentes:
        archivo = servicio.files().update(fileId=existentes[0]["id"], media_body=media).execute()
    else:
        metadata = {"name": nombre, "parents": [folder_id]}
        archivo = servicio.files().create(body=metadata, media_body=media, fields="id").execute()

    return archivo["id"]


def descargar_archivo_por_nombre(nombre: str, folder_id: str, destino: Path) -> bool:
    """
    Busca un archivo por nombre en la carpeta de Drive y lo descarga.
    Retorna True si lo encontró y descargó, False si no existe.
    """
    servicio = autenticar()
    query = f"'{folder_id}' in parents and name='{nombre}' and trashed=false"
    archivos = servicio.files().list(q=query, fields="files(id)").execute().get("files", [])

    if not archivos:
        return False

    request = servicio.files().get_media(fileId=archivos[0]["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    listo = False
    while not listo:
        _, listo = downloader.next_chunk()

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(buffer.getvalue())
    return True
