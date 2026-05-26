"""
autenticar_drive.py
-------------------
Script de un solo uso para autenticarse con Google Drive.
Abre el navegador, pedis permiso una vez, y guarda el token localmente.
Despues de correrlo exitosamente podes borrarlo.

Uso:
    python autenticar_drive.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.cli import _cargar_dotenv
_cargar_dotenv()

import os
from src.drive import autenticar, listar_excels

print()
print("=== Autenticacion con Google Drive ===")
print()
print("Se va a abrir el navegador para pedirte permiso.")
print("Inicia sesion con tu cuenta de Google y acepta el acceso.")
print()

try:
    servicio = autenticar()
    print("Autenticacion exitosa. Token guardado en .credentials/token.json")
    print()

    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id:
        print("Verificando acceso a la carpeta de Drive...")
        archivos = listar_excels(folder_id)
        if archivos:
            print(f"Archivos Excel encontrados ({len(archivos)}):")
            for a in archivos:
                print(f"  - {a['name']}")
        else:
            print("La carpeta esta vacia o no contiene archivos .xlsx")
            print("Tip: asegurate de haber subido el Excel a la carpeta correcta en Drive.")
    else:
        print("AVISO: DRIVE_FOLDER_ID no esta configurado en .env")

except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print()
print("Listo. Ya podes usar el comando 'actualizar' dentro del chatbot.")
