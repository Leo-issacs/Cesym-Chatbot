"""
tests/fixtures/datos.py
-----------------------
Generadores de datos sintéticos. Cada función devuelve un DataFrame con la MISMA
forma que produce el loader correspondiente (datos RAW, pre-limpieza), o escribe
un mini-Excel temporal con la estructura real (encabezado dinámico tras filas de
preámbulo).

Los datos cubren a propósito los casos difíciles documentados en
docs/DATA_FLOW.md, para que la lógica de cleaner.py/loader.py se pruebe contra
ellos de forma determinista:

  - fechas mixtas dd/mm/yyyy (texto que Excel no convirtió) e ISO invertida
    (yyyy-mm-dd que Excel leyó al revés y hay que des-invertir);
  - clientes con espacios extra y mayúsculas inconsistentes ("  toyoda  ");
  - filas parciales (solo cliente / solo tipo);
  - folios / cotizaciones duplicados;
  - montos con NaN;
  - columnas con espacios en el encabezado (" Total ").
"""

from datetime import datetime
from pathlib import Path

import pandas as pd


# ─── OC FACTURADO (hoja "OC FACTURADO") ──────────────────────────────────────
# clean_facturado toma df.iloc[:, :6] y renombra a:
#   factura, oc, monto_actual, prioridad, fecha, estado
def df_facturado_raw() -> pd.DataFrame:
    """RAW como lo devuelve load_facturado(): encabezado real + filas de totales."""
    columnas = ["FACTURA", "OC", "CURTRXAM", "ORCTRXAM1", "FECHA_CALCULO", "ESTADO", "SUBTOTAL"]
    filas = [
        [8001, "O01-100", 1500.50, "",          datetime(2026, 1, 15), "ACEPTADA",      ""],
        [8002, "O01-101", 2300.00, "PRIORIDAD", datetime(2026, 2, 20), "PREV ACEPTADO", ""],
        [8003, "",        900.00,  "",          datetime(2026, 3, 1),  "",              ""],  # sin OC
        [8004, "O01-103", None,    "",          datetime(2026, 3, 5),  "ACEPTADA",      ""],  # monto NaN
        [8005, "O01-104", 1200.00, "",          None,                  "ACEPTADA",      ""],  # sin fecha
        [8002, "O01-101", 2300.00, "PRIORIDAD", datetime(2026, 2, 20), "",              ""],  # factura duplicada
        # Filas de totales/resumen al final (factura no numérica → se descartan):
        ["TOTAL",        "", 8200.50, "", None, "", ""],
        ["OC FACTURADO", "", None,    "", None, "", ""],
    ]
    return pd.DataFrame(filas, columns=columnas)


# ─── PTE OC (hoja "PTE OC 25-26") ────────────────────────────────────────────
# clean_pendiente toma df.iloc[:, 1:5] y renombra a: cot, suc, importe, concepto
def df_pendiente_raw() -> pd.DataFrame:
    """RAW como lo devuelve load_pendiente(): col 0 vacía + encabezado + totales."""
    columnas = ["VACIA", "COT", "SUC", "IMPORTE", "CONCEPTO", "SUBTOTAL"]
    filas = [
        ["", 74, 1, 5000.00, "Instalación minisplit", ""],
        ["", 75, 2, 3200.50, "Mantenimiento",         ""],
        ["", 86, 3, None,    "Cotización sin importe", ""],  # importe NaN
        ["", 74, 1, 5000.00, "Duplicada 74",          ""],  # cot duplicada
        ["", 86, 3, 1000.00, "Duplicada 86",          ""],  # cot duplicada
        ["", "TOTAL", "", 14200.50, "", ""],                 # cot no numérica → se descarta
    ]
    return pd.DataFrame(filas, columns=columnas)


# ─── Reporte mensual de facturas ─────────────────────────────────────────────
# load_facturas_mensual lee con dtype=str; clean_facturas_mensual hace strip de
# los nombres de columna y renombra por posición a:
#   folio, cliente, fecha, concepto, total, fecha_pago
def df_facturas_mensual_raw() -> pd.DataFrame:
    """RAW como lo devuelve load_facturas_mensual(): todo string, encabezados con espacios."""
    # Nota los espacios en " Cliente " y " Total " (caso real del XLSX exportado).
    columnas = ["Folio", " Cliente ", "Fecha", "Concepto", " Total ", "FECHA DE PAGO"]
    filas = [
        # folio, cliente,        fecha,                  concepto,                 total,         fecha_pago
        ["100", "  toyoda  ",    "25/12/2025",           "Servicio",               " $1,234.00 ", "30/12/2025"],
        ["101", "TEC Y DISEÑO",  "2026-05-03 00:00:00",  "Mantenimiento",          "2000",        ""],
        ["102", "Cliente C",     "15/03/2026",           "venta CANCELADO refac",  "500",         "20/03/2026"],
        ["100", "Toyoda",        "10/01/2026",           "Duplicado folio",        "999",         "11/01/2026"],
        ["103", "Cliente D",     "01/02/2026",           "Servicio",               None,          "05/02/2026"],
        ["TOTAL", "",            "",                     "",                       "3733",        ""],
    ]
    return pd.DataFrame(filas, columns=columnas)


# ─── Control de trabajos (instalaciones/servicios) ───────────────────────────
# load_trabajos lee con dtype=str (10 columnas). clean_trabajos toma las columnas
# [0,1,2,3,4,5,6,8,9] y conserva solo filas con cliente Y tipo_trabajo no nulos.
def df_trabajos_raw() -> pd.DataFrame:
    """RAW como lo devuelve load_trabajos(): incluye filas parciales que se filtran."""
    columnas = [
        "MES", "TECNICO", "CLIENTE", "REP #", "DOMICILIO", "TELEFONO",
        "TIPO DE TRABAJO", "Unnamed: 7", "PAGADO", "RECIBE",
    ]
    filas = [
        ["enero",   "Tec1", "  Toyoda  ",         "R1", "Dom A", "111", "Instalacion",   "", "1500", "Juan"],
        ["FEBRERO", "Tec2", "Cliente B",          "R2", "Dom B", "222", "Mantenimiento", "", "SI",   "Ana"],
        ["marzo",   "Tec3", "Cliente C",          "R3", "Dom C", "333", "Reparacion",    "", "",     "Luis"],
        ["abril",   "Tec4", "Cliente D parcial",  "",   "",      "",    None,            "", "",     ""],  # solo cliente
        [None,      None,   None,                 None, None,    None,  "Solo tipo",     "", None,   None],  # solo tipo
    ]
    return pd.DataFrame(filas, columns=columnas)


# ─── Mini-Excel de cartera (para los tests de loader.py) ─────────────────────
def escribir_excel_cartera(path: Path) -> Path:
    """
    Escribe un .xlsx con la estructura REAL de la cartera, para ejercitar la
    detección dinámica de encabezado de loader.py:

      - Hoja "OC FACTURADO": fila de título + encabezado (FACTURA en col 0) + datos.
      - Hoja "PTE OC 25-26": fila de título + encabezado (COT en col 1) + datos.
      - Hoja "Hoja1": vacía.

    Devuelve el Path escrito.
    """
    oc_facturado = [
        ["CARTERA AL 11032026", None, None, None, None, None],            # preámbulo
        ["FACTURA", "OC", "CURTRXAM", "ORCTRXAM1", "FECHA_CALCULO", "ESTADO"],  # encabezado real
        [8001, "O01-100", 1500.50, "",          datetime(2026, 1, 15), "ACEPTADA"],
        [8002, "O01-101", 2300.00, "PRIORIDAD", datetime(2026, 2, 20), ""],
        ["TOTAL", None, 3800.50, None, None, None],
    ]
    pte_oc = [
        ["PENDIENTES DE OC", None, None, None, None],                     # preámbulo
        [None, "COT", "SUC", "IMPORTE", "CONCEPTO"],                      # encabezado real (COT en col 1)
        [None, 74, 1, 5000.00, "Instalación"],
        [None, 75, 2, 3200.50, "Mantenimiento"],
        [None, "TOTAL", None, 8200.50, None],
    ]

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(oc_facturado).to_excel(writer, sheet_name="OC FACTURADO", header=False, index=False)
        pd.DataFrame(pte_oc).to_excel(writer, sheet_name="PTE OC 25-26", header=False, index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Hoja1", header=False, index=False)
    return path
