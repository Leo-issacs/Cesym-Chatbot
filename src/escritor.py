"""
escritor.py
-----------
Responsabilidad unica: escribir datos en los archivos Excel.

Reglas:
- Nunca modifica el Excel original (en Drive, carpeta 01_Excels_Originales).
- Siempre crea un backup en data/backups/ antes de escribir.
- Sube el archivo modificado de vuelta a Drive.
- No toca los DataFrames en memoria — eso es responsabilidad del caller.
"""

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.loader import _resolver_ruta_trabajos

DATA_BACKUPS_DIR = Path(__file__).parent.parent / "data" / "backups"


def _hacer_backup(ruta_original: Path) -> Path:
    """Copia el archivo a data/backups/ con timestamp antes de modificarlo."""
    DATA_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DATA_BACKUPS_DIR / f"{ruta_original.stem}_{timestamp}{ruta_original.suffix}"
    shutil.copy2(ruta_original, destino)
    return destino


_COLUMNAS_TRABAJOS = [
    "ENERO", "TECNICO", "CLIENTE", "REP #",
    "DOMICILIO", "TELEFONO", "TIPO DE TRABAJO",
    "Unnamed: 7", "PAGADO", "RECIBE",
]


def _obtener_o_crear_archivo_trabajos() -> Path:
    """
    Retorna la ruta del archivo de trabajos.
    Si no existe, lo crea con los headers correctos en data/raw/.
    """
    try:
        return _resolver_ruta_trabajos()
    except FileNotFoundError:
        from src.loader import DATA_RAW_DIR
        DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_RAW_DIR / "CONTROL DE INST. MINISPLIT 2026.xlsx"
        pd.DataFrame(columns=_COLUMNAS_TRABAJOS).to_excel(path, index=False)
        return path


def agregar_trabajo(datos: dict) -> str:
    """
    Agrega una fila al Excel de control de trabajos, hace backup y sube a Drive.

    datos: dict con claves mes, tecnico, cliente, domicilio, telefono,
                              tipo_trabajo, pagado, recibe

    Retorna mensaje de resultado (exito o error).
    """
    path = _obtener_o_crear_archivo_trabajos()

    # Backup antes de escribir
    _hacer_backup(path)

    # Leer Excel existente y limpiar filas sin cliente ni tipo de trabajo
    # (evita que filas vacías o celdas sueltas desplacen los registros nuevos)
    df = pd.read_excel(path, header=0, dtype=str)
    cliente_col = df.columns[2]
    tipo_col = df.columns[6]
    df = df[df[cliente_col].notna() & df[tipo_col].notna()].reset_index(drop=True)

    # Construir nueva fila usando los nombres de columna originales del Excel
    nueva_fila = {
        df.columns[0]: datos.get("mes", ""),        # ENERO (columna de mes)
        df.columns[1]: datos.get("tecnico", ""),     # TECNICO
        df.columns[2]: datos.get("cliente", ""),     # CLIENTE
        df.columns[3]: "",                            # REP # (auto-vacio, se llena manual)
        df.columns[4]: datos.get("domicilio", ""),   # DOMICILIO
        df.columns[5]: datos.get("telefono", ""),    # TELEFONO
        df.columns[6]: datos.get("tipo_trabajo", ""),# TIPO DE TRABAJO
        df.columns[7]: "",                            # columna vacía
        df.columns[8]: datos.get("pagado", ""),      # PAGADO
        df.columns[9]: datos.get("recibe", ""),      # RECIBE
    }

    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    df.to_excel(path, index=False)

    # Subir a Drive si está configurado
    import os
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id:
        try:
            from src.drive import subir_excel
            subir_excel(path, folder_id)
        except Exception as e:
            return (
                f"Trabajo guardado localmente, pero no se pudo subir a Drive: {e}\n"
                "Usa 'actualizar' para sincronizar manualmente."
            )

    pago_str = f"${float(datos['pagado']):,.2f}" if datos.get("pagado") else "sin cobrar"
    return (
        f"Trabajo registrado correctamente.\n"
        f"{datos['cliente']} | {datos['tipo_trabajo']} | {pago_str}"
    )
