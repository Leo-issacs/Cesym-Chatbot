"""
loader.py
---------
Responsabilidad única: abrir el archivo Excel y devolver los datos RAW
tal como están, sin limpiar ni transformar nada.

Nunca modifica el archivo original. Solo lectura.

Resolución del archivo:
  1. Si se pasa una ruta explícita, la usa.
  2. Si existe CARTERA_PATH en el entorno, la usa.
  3. Si no, busca automáticamente el archivo más reciente que empiece
     con "CARTERA" en data/raw/ (útil cuando el nombre cambia cada mes).
"""

import os
import pandas as pd
from pathlib import Path

DATA_RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def _resolver_ruta_cartera(ruta_explicita: Path | None = None) -> Path:
    """Determina qué archivo Excel de cartera usar."""
    if ruta_explicita:
        return ruta_explicita

    env_path = os.getenv("CARTERA_PATH")
    if env_path:
        return Path(env_path)

    candidatos = sorted(
        DATA_RAW_DIR.glob("CARTERA*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidatos:
        raise FileNotFoundError(
            "No se encontró ningún archivo Excel de cartera en data/raw/.\n"
            "Descargá el archivo desde Drive con el comando 'actualizar', "
            "o copialo manualmente a data/raw/."
        )
    return candidatos[0]


def _extract_sheet(sheet_name: str, keyword: str, keyword_col: int = 0, excel_path: Path | None = None) -> pd.DataFrame:
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
        excel_path  : ruta al archivo Excel (opcional, usa _resolver_ruta_cartera si no se pasa)
    """
    path = excel_path or _resolver_ruta_cartera()
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)

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


def load_facturado(excel_path: Path | None = None) -> pd.DataFrame:
    """
    Carga la hoja 'OC FACTURADO'.

    Contiene las facturas emitidas con su OC asociada, monto, fecha y estado.
    El encabezado real está precedido por una fila vacía en el Excel,
    por eso usamos detección dinámica buscando 'FACTURA' en la primera columna.
    """
    path = excel_path or _resolver_ruta_cartera()
    return _extract_sheet("OC FACTURADO", "FACTURA", keyword_col=0, excel_path=path)


def load_pendiente(excel_path: Path | None = None) -> pd.DataFrame:
    """
    Carga la hoja 'PTE OC 25-26'.

    Contiene cotizaciones que todavía no tienen orden de compra asignada.
    El encabezado real está en la tercera fila del Excel, precedido por un título.
    Buscamos 'COT' en la segunda columna para detectarlo.
    """
    path = excel_path or _resolver_ruta_cartera()
    return _extract_sheet("PTE OC 25-26", "COT", keyword_col=1, excel_path=path)


def _resolver_ruta_facturas_mensual(ruta_explicita: Path | None = None) -> Path:
    """
    Determina qué archivo de reporte mensual usar.
    Acepta .xlsx o .csv. Si existen ambos, prefiere el más reciente.
    """
    if ruta_explicita:
        return ruta_explicita

    env_path = os.getenv("FACTURAS_PATH")
    if env_path:
        return Path(env_path)

    candidatos = sorted(
        list(DATA_RAW_DIR.glob("reporteMensual*.xlsx")) +
        list(DATA_RAW_DIR.glob("reporteMensual*.csv")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # Ignorar archivos temporales de Excel (~$...)
    candidatos = [p for p in candidatos if not p.name.startswith("~$")]

    if not candidatos:
        raise FileNotFoundError(
            "No se encontró ningún archivo de reporte mensual en data/raw/.\n"
            "Coloca el archivo en data/raw/ o descárgalo desde Drive con 'actualizar'."
        )
    return candidatos[0]


def load_facturas_mensual(ruta_explicita: Path | None = None) -> pd.DataFrame:
    """
    Carga el reporte mensual de facturas desde un archivo CSV o XLSX.

    Columnas esperadas: Folio, Cliente, Fecha, Concepto, Total, FECHA DE PAGO
    Devuelve los datos RAW sin limpiar. Las fechas se leen siempre como texto
    para evitar que Excel las reinterprete en formato MM/DD/YYYY.
    """
    path = _resolver_ruta_facturas_mensual(ruta_explicita)

    if path.suffix.lower() == ".xlsx":
        # dtype=str evita que pandas/openpyxl auto-convierta fechas
        return pd.read_excel(path, dtype=str, header=0)

    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding="latin-1")


def _resolver_ruta_trabajos(ruta_explicita: Path | None = None) -> Path:
    """
    Determina qué archivo de control de trabajos usar.
    Busca archivos que empiecen con 'CONTROL' en data/raw/.
    """
    if ruta_explicita:
        return ruta_explicita

    env_path = os.getenv("TRABAJOS_PATH")
    if env_path:
        return Path(env_path)

    candidatos = sorted(
        DATA_RAW_DIR.glob("CONTROL*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    candidatos = [p for p in candidatos if not p.name.startswith("~$")]

    if not candidatos:
        raise FileNotFoundError(
            "No se encontró ningún archivo de control de trabajos en data/raw/.\n"
            "El archivo debe empezar con 'CONTROL' y tener extensión .xlsx."
        )
    return candidatos[0]


def load_trabajos(ruta_explicita: Path | None = None) -> pd.DataFrame:
    """
    Carga el control de trabajos a clientes casuales (instalaciones, servicios, etc.).

    Columnas esperadas: MES, TECNICO, CLIENTE, REP #, DOMICILIO, TELEFONO,
                        TIPO DE TRABAJO, (vacía), PAGADO, RECIBE
    Devuelve los datos RAW sin limpiar.
    """
    path = _resolver_ruta_trabajos(ruta_explicita)
    return pd.read_excel(path, header=0, dtype=str)
