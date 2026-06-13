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
    df["oc"] = df["oc"].fillna("").astype(str).str.strip()
    df["prioridad"] = df["prioridad"].fillna("").astype(str).str.strip()
    df["estado"] = df["estado"].fillna("").astype(str).str.strip()

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
    df["concepto"] = df["concepto"].fillna("").astype(str).str.strip()

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


def _parsear_fecha_mensual(serie: pd.Series) -> pd.Series:
    """
    Parsea fechas del reporte mensual que pueden venir en dos formatos:

    - 'DD/MM/YYYY'           : Excel no pudo convertir (DD > 12). Se parsea directo.
    - 'YYYY-MM-DD HH:MM:SS'  : Excel convirtió asumiendo MM/DD. Se invierte mes/día
                               para recuperar la fecha original DD/MM.

    Esta inversión es necesaria cuando el archivo viene de un XLSX generado desde
    un CSV con fechas en formato DD/MM/YYYY — Excel las lee al revés.
    """
    resultados = []
    for val in serie.astype(str).str.strip():
        if val in ("", "nan", "NaT", "None", "NaN"):
            resultados.append(pd.NaT)
            continue
        # Intento 1: DD/MM/YYYY (texto que Excel no convirtió)
        try:
            resultados.append(pd.to_datetime(val, format="%d/%m/%Y"))
            continue
        except (ValueError, TypeError):
            pass
        # Intento 2: YYYY-MM-DD (Excel invirtió DD/MM → recuperar intercambiando mes y día)
        try:
            dt = pd.to_datetime(val, format="%Y-%m-%d %H:%M:%S")
            resultados.append(dt.replace(month=dt.day, day=dt.month))
            continue
        except (ValueError, TypeError):
            pass
        try:
            dt = pd.to_datetime(val, format="%Y-%m-%d")
            resultados.append(dt.replace(month=dt.day, day=dt.month))
            continue
        except (ValueError, TypeError):
            pass
        resultados.append(pd.NaT)

    return pd.Series(resultados, index=serie.index, dtype="datetime64[us]")


def clean_facturas_mensual(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Limpia el reporte mensual de facturas (CSV o XLSX).

    Columnas originales: Folio, Cliente, Fecha, Concepto, Total, FECHA DE PAGO
    - Descarta filas canceladas
    - Limpia montos: " $1,234.00 " o "1234.0" → 1234.0
    - Parsea fechas DD/MM/YYYY con corrección automática si vienen de XLSX
    - Normaliza nombres de cliente (strip, uppercase)

    Retorna:
        (DataFrame limpio, lista de advertencias)
    """
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    df.columns = ["folio", "cliente", "fecha", "concepto", "total", "fecha_pago"]

    # Eliminar filas canceladas (concepto contiene CANCELADO sin espacios)
    mask_canceladas = (
        df["concepto"]
        .astype(str)
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
        .str.contains("CANCELADO", na=False)
    )
    n_canceladas = int(mask_canceladas.sum())
    df = df[~mask_canceladas].copy()

    # Eliminar filas donde folio no es numérico (filas de resumen/total)
    df = df[pd.to_numeric(df["folio"], errors="coerce").notna()].copy()

    # --- Conversión de tipos ---
    df["folio"] = pd.to_numeric(df["folio"], errors="coerce").astype("Int64")
    df["cliente"] = df["cliente"].fillna("").astype(str).str.strip().str.upper()
    df["concepto"] = df["concepto"].fillna("").astype(str).str.strip()

    # Limpiar monto: " $1,234.00 " o "1234.0" → 1234.0
    df["total"] = (
        df["total"]
        .astype(str)
        .str.strip()
        .str.replace(r"[\$,\s]", "", regex=True)
        .pipe(lambda s: pd.to_numeric(s, errors="coerce"))
    )

    df["fecha"] = _parsear_fecha_mensual(df["fecha"])
    df["fecha_pago"] = _parsear_fecha_mensual(df["fecha_pago"])

    df = df.reset_index(drop=True)

    # --- Detección de inconsistencias ---
    advertencias = []

    if n_canceladas > 0:
        advertencias.append(f"{n_canceladas} factura(s) cancelada(s) excluidas del reporte mensual")

    sin_pago = df[df["fecha_pago"].isna()]
    if not sin_pago.empty:
        advertencias.append(
            f"{len(sin_pago)} factura(s) del reporte mensual sin fecha de pago registrada"
        )

    montos_invalidos = df[df["total"].isna() | (df["total"] <= 0)]
    if not montos_invalidos.empty:
        advertencias.append(
            f"{len(montos_invalidos)} factura(s) del reporte mensual con monto inválido: "
            f"{montos_invalidos['folio'].tolist()}"
        )

    return df, advertencias


def clean_trabajos(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Limpia el control de trabajos a clientes casuales.

    Columnas originales del Excel (por posición):
      0: MES            → mes del trabajo (ENERO, FEBRERO, etc.)
      1: TECNICO        → técnico que realizó el trabajo
      2: CLIENTE        → nombre del cliente
      3: REP #          → número de reporte/trabajo
      4: DOMICILIO      → dirección del cliente
      5: TELEFONO       → teléfono del cliente
      6: TIPO DE TRABAJO → descripción del servicio realizado
      7: (vacía)        → se descarta
      8: PAGADO         → monto cobrado (vacío = no cobrado aún)
      9: RECIBE         → quién recibe/firma el trabajo

    Retorna:
        (DataFrame limpio, lista de advertencias)
    """
    # Descartar la columna vacía (posición 7)
    df = df.iloc[:, [0, 1, 2, 3, 4, 5, 6, 8, 9]].copy()
    df.columns = ["mes", "tecnico", "cliente", "rep_num", "domicilio", "telefono", "tipo_trabajo", "pagado", "recibe"]

    # Conservar solo filas con cliente Y tipo de trabajo (filtra celdas sueltas y filas vacías)
    df = df[df["cliente"].notna() & df["tipo_trabajo"].notna()].copy()

    # --- Conversión de tipos ---
    df["mes"] = df["mes"].astype(str).str.strip().str.upper().replace("NAN", "")
    df["tecnico"] = df["tecnico"].fillna("").astype(str).str.strip()
    df["cliente"] = df["cliente"].fillna("").astype(str).str.strip()
    df["rep_num"] = df["rep_num"].fillna("").astype(str).str.strip()
    df["domicilio"] = df["domicilio"].fillna("").astype(str).str.strip()
    df["telefono"] = df["telefono"].fillna("").astype(str).str.strip()
    df["tipo_trabajo"] = df["tipo_trabajo"].fillna("").astype(str).str.strip()
    df["recibe"] = df["recibe"].fillna("").astype(str).str.strip()

    # PAGADO: intenta parsear como monto numérico; si es "SI"/"NO"/vacío queda NaN
    df["pagado"] = (
        df["pagado"]
        .astype(str)
        .str.strip()
        .str.replace(r"[\$,\s]", "", regex=True)
        .pipe(lambda s: pd.to_numeric(s, errors="coerce"))
    )

    df = df.reset_index(drop=True)

    # --- Detección de inconsistencias ---
    advertencias = []

    sin_cliente = df[df["cliente"].isin(["", "nan", "NaN"])]
    if not sin_cliente.empty:
        advertencias.append(f"{len(sin_cliente)} trabajo(s) sin cliente registrado")

    sin_tipo = df[df["tipo_trabajo"].isin(["", "nan", "NaN"])]
    if not sin_tipo.empty:
        advertencias.append(f"{len(sin_tipo)} trabajo(s) sin tipo de trabajo especificado")

    return df, advertencias
