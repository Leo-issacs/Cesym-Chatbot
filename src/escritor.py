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


_CAMPO_A_COLUMNA_IDX = {
    "mes":          0,
    "tecnico":      1,
    "cliente":      2,
    "domicilio":    4,
    "telefono":     5,
    "tipo_trabajo": 6,
    "pagado":       8,
    "recibe":       9,
}

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


def _subir_a_drive(path: Path) -> str | None:
    """Sube el archivo a Drive. Retorna mensaje de error o None si todo bien."""
    import os
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if not folder_id:
        return None
    try:
        from src.drive import subir_excel
        subir_excel(path, folder_id)
        return None
    except Exception as e:
        return (
            f"Guardado localmente, pero no se pudo subir a Drive: {e}\n"
            "Usa 'actualizar' para sincronizar manualmente."
        )


def borrar_trabajo(indice: int) -> str:
    """
    Elimina un trabajo del Excel por su índice en el DataFrame limpio.
    Hace backup antes de modificar y sube a Drive.
    """
    path = _obtener_o_crear_archivo_trabajos()
    _hacer_backup(path)

    df = pd.read_excel(path, header=0, dtype=str)
    cliente_col = df.columns[2]
    tipo_col = df.columns[6]
    df_limpio = df[df[cliente_col].notna() & df[tipo_col].notna()].reset_index(drop=True)

    if indice < 0 or indice >= len(df_limpio):
        return "Error: trabajo no encontrado."

    cliente = df_limpio.at[indice, cliente_col]
    df_limpio = df_limpio.drop(index=indice).reset_index(drop=True)
    df_limpio.to_excel(path, index=False)

    error_drive = _subir_a_drive(path)
    if error_drive:
        return error_drive

    return f"Trabajo de '{cliente}' eliminado correctamente."


def editar_trabajo(indice: int, campo: str, valor: str) -> str:
    """
    Modifica un campo de un trabajo existente en el Excel.

    indice: posición 0-based en el DataFrame limpio (mismo orden que muestra el bot)
    campo:  nombre del campo (mes, tecnico, cliente, domicilio, telefono,
                              tipo_trabajo, pagado, recibe)
    valor:  nuevo valor como string (vacío string = borrar el campo)

    Retorna mensaje de resultado.
    """
    col_idx = _CAMPO_A_COLUMNA_IDX.get(campo)
    if col_idx is None:
        return f"Campo '{campo}' no reconocido."

    path = _obtener_o_crear_archivo_trabajos()
    _hacer_backup(path)

    df = pd.read_excel(path, header=0, dtype=str)
    cliente_col = df.columns[2]
    tipo_col = df.columns[6]
    df_limpio = df[df[cliente_col].notna() & df[tipo_col].notna()].reset_index(drop=True)

    if indice < 0 or indice >= len(df_limpio):
        return "Error: trabajo no encontrado."

    col_name = df_limpio.columns[col_idx]
    df_limpio.at[indice, col_name] = valor if valor else None
    df_limpio.to_excel(path, index=False)

    error_drive = _subir_a_drive(path)
    if error_drive:
        return error_drive

    return f"Trabajo actualizado correctamente."
