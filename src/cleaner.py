"""
cleaner.py
----------
Responsabilidad única: recibir los datos RAW del loader y devolverlos
limpios, normalizados y con tipos correctos.

Reglas:
- No modifica el Excel original.
- No toca el DataFrame que recibe; trabaja sobre copias.
- Elimina filas de totales/resumen que el Excel incluye al final.
- Convierte tipos (fechas, números, texto).
- Detecta inconsistencias y las reporta como advertencias (sin borrar datos).
"""

import pandas as pd


def clean_facturado(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Limpia la hoja OC FACTURADO.

    Columnas originales del Excel (por posición):
      0: FACTURA       → número de factura
      1: OC            → número de orden de compra (ej: O01-507749)
      2: CURTRXAM      → monto actual pendiente de cobro
      3: ORCTRXAM1     → indica si es PRIORIDAD o el monto original de la OC
      4: FECHA_CALCULO → fecha de la factura
      5: (sin nombre)  → estado: ACEPTADA, PREV ACEPTADO, etc.
      6 y 7: columnas de subtotales — se descartan

    Retorna:
        (DataFrame limpio, lista de advertencias)
    """
    # Tomar solo las 6 columnas útiles (descartar columnas de subtotales al final)
    df = df.iloc[:, :6].copy()
    df.columns = ["factura", "oc", "monto_actual", "prioridad", "fecha", "estado"]

    # Eliminar las filas de resumen al final (donde 'factura' no es un número)
    # El Excel termina con filas como "OC FACTURADO", "COTIZADO", "TOTAL"
    df = df[pd.to_numeric(df["factura"], errors="coerce").notna()].copy()

    # --- Conversión de tipos ---
    df["factura"] = pd.to_numeric(df["factura"], errors="coerce").astype("Int64")
    df["monto_actual"] = pd.to_numeric(df["monto_actual"], errors="coerce")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["oc"] = df["oc"].astype(str).str.strip()
    df["prioridad"] = df["prioridad"].astype(str).str.strip().replace("nan", "")
    df["estado"] = df["estado"].astype(str).str.strip().replace("nan", "")

    df = df.reset_index(drop=True)

    # --- Detección de inconsistencias ---
    advertencias = []

    montos_invalidos = df[df["monto_actual"].isna() | (df["monto_actual"] <= 0)]
    if not montos_invalidos.empty:
        advertencias.append(
            f"{len(montos_invalidos)} factura(s) con monto inválido (cero o vacío): "
            f"{montos_invalidos['factura'].tolist()}"
        )

    sin_fecha = df[df["fecha"].isna()]
    if not sin_fecha.empty:
        advertencias.append(
            f"{len(sin_fecha)} factura(s) sin fecha: {sin_fecha['factura'].tolist()}"
        )

    sin_oc = df[df["oc"].isin(["nan", "", "NaN"])]
    if not sin_oc.empty:
        advertencias.append(
            f"{len(sin_oc)} factura(s) sin OC asignada"
        )

    return df, advertencias


def clean_pendiente(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Limpia la hoja PTE OC 25-26.

    Columnas originales del Excel (por posición):
      0: (vacía)   → se descarta
      1: COT       → número de cotización
      2: SUC       → número de sucursal
      3: IMPORTE   → monto de la cotización
      4: CONCEPTO  → descripción del servicio cotizado
      5: (vacía)   → se descarta (a veces tiene subtotales parciales)

    Retorna:
        (DataFrame limpio, lista de advertencias)
    """
    # Tomar columnas 1 a 4 (descartar la primera y la última vacías)
    df = df.iloc[:, 1:5].copy()
    df.columns = ["cot", "suc", "importe", "concepto"]

    # Eliminar filas de total al final (donde 'cot' no es un número)
    df = df[pd.to_numeric(df["cot"], errors="coerce").notna()].copy()

    # --- Conversión de tipos ---
    df["cot"] = pd.to_numeric(df["cot"], errors="coerce").astype("Int64")
    df["suc"] = pd.to_numeric(df["suc"], errors="coerce").astype("Int64")
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    df["concepto"] = df["concepto"].astype(str).str.strip().replace("nan", "")

    df = df.reset_index(drop=True)

    # --- Detección de inconsistencias ---
    advertencias = []

    importes_invalidos = df[df["importe"].isna() | (df["importe"] <= 0)]
    if not importes_invalidos.empty:
        advertencias.append(
            f"{len(importes_invalidos)} cotización(es) con importe inválido: "
            f"{importes_invalidos['cot'].tolist()}"
        )

    duplicadas = df[df.duplicated("cot", keep=False)]
    if not duplicadas.empty:
        advertencias.append(
            f"Cotizaciones con número duplicado: {duplicadas['cot'].unique().tolist()}"
        )

    return df, advertencias
