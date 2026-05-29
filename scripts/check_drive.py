import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cli import _cargar_dotenv
_cargar_dotenv()

import os
from src.drive import sincronizar_desde_drive

folder_id = os.getenv("DRIVE_FOLDER_ID")
print(f"Carpeta: {folder_id}")
print("Sincronizando...")
descargados = sincronizar_desde_drive(folder_id)
print(f"Descargados ({len(descargados)}):")
for f in descargados:
    print(f"  - {f}")
