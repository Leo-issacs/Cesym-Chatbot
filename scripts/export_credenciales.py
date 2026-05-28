"""
export_credenciales.py
----------------------
Genera los valores base64 que hay que pegar en las variables de entorno
de Railway (o cualquier plataforma cloud) para que el servidor pueda
autenticarse con Google Drive sin necesitar el navegador.

Cómo usarlo:
    python scripts/export_credenciales.py

Luego copiá cada valor y pegalo en Railway → Variables:
    GOOGLE_CREDENTIALS_JSON = <el valor que muestra este script>
    GOOGLE_TOKEN_JSON       = <el valor que muestra este script>
"""

import sys
import base64
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CREDENTIALS_DIR = BASE_DIR / ".credentials"


def exportar(nombre_archivo: str, nombre_variable: str):
    ruta = CREDENTIALS_DIR / nombre_archivo
    if not ruta.exists():
        print(f"  ✗ No se encontró: {ruta}")
        return
    contenido = ruta.read_bytes()
    b64 = base64.b64encode(contenido).decode("utf-8")
    print(f"\n{nombre_variable}=")
    print(b64)


print("=" * 60)
print("  Valores para las variables de entorno en Railway")
print("=" * 60)
exportar("credentials.json", "GOOGLE_CREDENTIALS_JSON")
exportar("token.json", "GOOGLE_TOKEN_JSON")
print()
print("Copiá cada valor y pegalo en Railway → tu proyecto → Variables.")
