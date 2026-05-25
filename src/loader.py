"""
loader.py
---------
Responsabilidad única: abrir el archivo Excel y devolver los datos RAW
tal como están, sin limpiar ni transformar nada.

Nunca modifica el archivo original. Solo lectura.
"""

import pandas as pd
from pathlib import Path

EXCEL_PATH = Path(__file__).parent.parent / "data" / "raw" / "CARTERA AL 11032026.xlsx"


def _extract_sheet(sheet_name: str, keyword: str, keyword_col: int = 0) -> pd.DataFrame:
    """
    Lee una hoja del Excel sin asumir en qué fila está el encabezado.

    El Excel tiene filas vacías o títulos antes del encabezado real,
    así que buscamos la primera fila donde la columna `keyword_col`
    contiene exactamente `keyword`. Esa fila se usa como nombres de columnas
    y todo lo que viene después es datos.

    Parámetros:
        sheet_name  : nombre de la hoja en el Excel
        keyword     : texto que identifica la fila de encabezado
        keyword_col : índice de la columna donde buscar ese texto
    """
    raw = pd.read_excel(EXCEL_PATH, sheet_name=sheet_name, header=None)

    col_vals = raw.iloc[:, keyword_col].astype(str).str.strip().str.upper()
    matches = raw.index[col_vals == keyword.upper()]

    if len(matches) == 0:
        raise ValueError(
            f"No se encontró el encabezado '{keyword}' en la hoja '{sheet_name}'. "
            f"¿Cambió la estructura del Excel?"
        )

    header_row = matches[0]
    df = raw.iloc[header_row + 1 :].copy()
    df.columns = raw.iloc[header_row].tolist()
    return df.reset_index(drop=True)


def load_facturado() -> pd.DataFrame:
    """
    Carga la hoja 'OC FACTURADO'.

    Contiene las facturas emitidas con su OC asociada, monto, fecha y estado.
    El encabezado real está precedido por una fila vacía en el Excel,
    por eso usamos detección dinámica buscando 'FACTURA' en la primera columna.
    """
    return _extract_sheet("OC FACTURADO", "FACTURA", keyword_col=0)


def load_pendiente() -> pd.DataFrame:
    """
    Carga la hoja 'PTE OC 25-26'.

    Contiene cotizaciones que todavía no tienen orden de compra asignada.
    El encabezado real está en la tercera fila del Excel, precedido por un título.
    Buscamos 'COT' en la segunda columna para detectarlo.
    """
    return _extract_sheet("PTE OC 25-26", "COT", keyword_col=1)
