"""
datos_postgres.py
-----------------
Carga los cuatro DataFrames que el bot necesita para responder consultas,
leyendo desde las tablas de PostgreSQL (schema 'chatbot') en lugar de los
archivos Excel.

POR QUÉ EXISTE ESTE MÓDULO:
  El bot actual lee los datos desde archivos Excel descargados de Drive y los
  limpia en memoria. Al migrar a Postgres la FUENTE DE VERDAD ya son las tablas
  (alimentadas por el ETL), así que las consultas del bot deben venir de ahí.

COLUMNAS DE SALIDA:
  Los DataFrames devueltos tienen EXACTAMENTE las mismas columnas que produce
  cleaner.py (lo que espera query_engine.py), para que el switch sea transparente:

  facturado      → factura, oc, monto_actual, prioridad, fecha, estado
  pendiente      → cot, suc, importe, concepto
  facturas_mensual → folio, cliente, fecha, concepto, total, fecha_pago
  trabajos       → mes, tecnico, cliente, rep_num, domicilio, telefono,
                   tipo_trabajo, pagado, recibe

ACTIVACIÓN:
  Este módulo se usa cuando USE_POSTGRES_READS=1, que es el DEFAULT desde PR-14.
  Con USE_POSTGRES_READS=0 se fuerza la lectura desde Excel. Si la lectura de
  Postgres falla, cli._cargar_datos cae a Excel automáticamente.
"""

import pandas as pd
from sqlalchemy import text

from src.db_postgres import SCHEMA, get_engine


# ─── Queries SQL → DataFrames con columnas exactas del query engine ─────────────

_SQL_FACTURADO = f"""
SELECT
    folio_factura            AS factura,
    COALESCE(numero_oc, '')  AS oc,
    monto                    AS monto_actual,
    COALESCE(prioridad, '')  AS prioridad,
    fecha,
    COALESCE(estado, '')     AS estado
FROM {SCHEMA}.ordenes_compra
WHERE tipo = 'OC_EMITIDA'
ORDER BY id;
"""
# COALESCE(..., '') replica lo que clean_facturado hace con .astype(str).replace('nan',''):
# los NULL de Postgres (None en Python / NaN en pandas) se convierten a string vacío,
# que es lo que el query engine espera para filtrar y agrupar correctamente.

_SQL_PENDIENTE = f"""
SELECT
    num_cotizacion              AS cot,
    sucursal                    AS suc,
    monto                       AS importe,
    COALESCE(concepto, '')      AS concepto
FROM {SCHEMA}.ordenes_compra
WHERE tipo = 'COT_PENDIENTE'
ORDER BY id;
"""

_SQL_FACTURAS_MENSUAL = f"""
SELECT
    f.folio,
    c.nombre        AS cliente,
    f.fecha_emision AS fecha,
    f.concepto,
    f.total,
    f.fecha_pago
FROM {SCHEMA}.facturas f
LEFT JOIN {SCHEMA}.clientes c ON f.cliente_id = c.id
WHERE f.cancelada = 0
ORDER BY f.folio;
"""

_SQL_TRABAJOS = f"""
SELECT
    t.mes,
    tec.nombre      AS tecnico,
    c.nombre        AS cliente,
    t.rep_num,
    t.domicilio,
    t.telefono,
    t.tipo_trabajo,
    t.pagado,
    t.recibe
FROM {SCHEMA}.trabajos t
LEFT JOIN {SCHEMA}.clientes  c   ON t.cliente_id  = c.id
LEFT JOIN {SCHEMA}.tecnicos  tec ON t.tecnico_id  = tec.id
ORDER BY t.id;
"""


# ─── Función pública ─────────────────────────────────────────────────────────────

def cargar_datos_desde_postgres(engine=None) -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]
]:
    """
    Lee los cuatro DataFrames desde Postgres y los devuelve en el mismo orden
    y formato que _cargar_datos() de cli.py:
      (facturado, pendiente, facturas_mensual, trabajos, advertencias)

    Las advertencias son una lista vacía: la validación de calidad de datos
    ya ocurrió cuando el ETL insertó los registros. Si alguna tabla está vacía
    se registra como advertencia informativa (no error).
    """
    eng = engine or get_engine()
    advertencias: list[str] = []

    with eng.connect() as conn:
        facturado        = pd.read_sql(text(_SQL_FACTURADO),        conn)
        pendiente        = pd.read_sql(text(_SQL_PENDIENTE),        conn)
        facturas_mensual = pd.read_sql(text(_SQL_FACTURAS_MENSUAL), conn)
        trabajos         = pd.read_sql(text(_SQL_TRABAJOS),         conn)

    # El ETL insertó el string literal "nan" para celdas vacías del Excel
    # (str(float('nan')) = "nan", que es truthy y no se convirtió a None).
    # Replicamos la normalización de cleaner.py: reemplazamos "nan" por "".
    _limpiar = lambda df, cols: [
        df.__setitem__(c, df[c].replace("nan", "")) for c in cols if c in df.columns
    ] or df
    _limpiar(facturado,        ["oc", "prioridad", "estado"])
    _limpiar(pendiente,        ["concepto"])
    _limpiar(facturas_mensual, ["cliente", "concepto"])
    _limpiar(trabajos,         ["mes", "tecnico", "cliente", "rep_num",
                                "domicilio", "telefono", "tipo_trabajo", "recibe"])

    if facturado.empty:
        advertencias.append("[PG] ordenes_compra OC_EMITIDA está vacía")
    if pendiente.empty:
        advertencias.append("[PG] ordenes_compra COT_PENDIENTE está vacía")
    if facturas_mensual.empty:
        advertencias.append("[PG] tabla facturas está vacía")

    return facturado, pendiente, facturas_mensual, trabajos, advertencias
