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
  trabajos       → id, mes, tecnico, cliente, rep_num, domicilio, telefono,
                   tipo_trabajo, pagado, recibe

  (trabajos lleva una columna EXTRA `id` —el pg_id de chatbot.trabajos— que
   query_engine.py ignora; se usa solo para editar/borrar por clave estable.
   La ruta Excel/cleaner no la produce, así que puede no estar presente.)

ACTIVACIÓN:
  Este módulo se usa cuando USE_POSTGRES_READS=1, que es el DEFAULT desde PR-14.
  Con USE_POSTGRES_READS=0 se fuerza la lectura desde Excel. Si la lectura de
  Postgres falla, cli._cargar_datos cae a Excel automáticamente.

PENDIENTE DESDE cesym_db (detrás de flag, APAGADO por default):
  Con USE_CESYM_DB_PENDIENTE=1, SOLO el DataFrame `pendiente` se lee desde la
  vista `chatbot_pendiente_v1` de cesym_db. Los otros tres DataFrames no
  cambian. Si la vista falla por cualquier razón, se loggea el error y se usa
  el `pendiente` de chatbot_db ya leído (fallback sin romper).
  Contexto: la vista fue validada 59/59 contra chatbot_db el 2026-07-11
  (Cesym/04-auditorias/2026-07-11-puente-pendiente-cierre-59de59.md).

  CESYM_DB_READ_URL vs CESYM_DB_URL:
    CESYM_DB_URL ya está en uso por el flujo de captura de cotizaciones con
    el rol de ESCRITURA `cesym_app` (src/cesym_db.py, cotizaciones_pg.py) —
    reapuntarla a un rol de solo lectura rompería esas escrituras. Por eso
    esta lectura de `pendiente` usa una variable aparte:
      CESYM_DB_READ_URL, si existe → rol de solo lectura `chatbot_ro`.
      Si no existe, cae a CESYM_DB_URL (compatibilidad; get_cesym_engine ya
      hace ese fallback internamente cuando se le pasa url=None).
    CESYM_DB_URL de escritura NUNCA se toca desde aquí.
"""

import logging
import os

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.db_postgres import SCHEMA, get_engine

logger = logging.getLogger(__name__)


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
    t.id,
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


# La vista vive en el schema public de cesym_db (no en el schema chatbot).
# ORDER BY estable: la vista no tiene id; cot es único salvo folios repetidos
# con sucursal distinta (caso documentado), así que (cot, suc) es determinista.
_SQL_PENDIENTE_CESYM = """
SELECT cot, suc, importe, concepto
FROM chatbot_pendiente_v1
ORDER BY cot NULLS LAST, suc NULLS LAST;
"""


def _flag_pendiente_cesym() -> bool:
    """USE_CESYM_DB_PENDIENTE=1 activa la lectura de `pendiente` desde cesym_db.
    Default '0' (apagado): el comportamiento actual queda intacto."""
    return os.environ.get("USE_CESYM_DB_PENDIENTE", "0") == "1"


def _entero_compatible(serie: pd.Series) -> pd.Series:
    """Deja cot/suc con el mismo dtype que produce la ruta chatbot (int64)
    cuando no hay nulos; si los hay (p. ej. suc NULL en una cotización sin
    sucursal), usa Int64 nullable en vez de degradar a float64 con .0"""
    numerica = pd.to_numeric(serie, errors="coerce")
    if numerica.isna().any():
        return numerica.astype("Int64")
    return numerica.astype("int64")


def _cargar_pendiente_desde_cesym(cesym_engine=None) -> pd.DataFrame:
    """Lee `pendiente` desde cesym_db.chatbot_pendiente_v1 y lo normaliza al
    contrato exacto del query engine (cot, suc, importe, concepto).

    Usa CESYM_DB_READ_URL (rol solo-lectura chatbot_ro) si está definida; si
    no, cae a CESYM_DB_URL (rol de escritura cesym_app, compatibilidad) sin
    tocar esa variable ni afectar las escrituras de cotizaciones que la usan."""
    if cesym_engine is None:
        # import perezoso: sin el flag, este módulo no depende de cesym_db
        from src.cesym_db import get_cesym_engine
        url_lectura = os.environ.get("CESYM_DB_READ_URL")
        fuente = "CESYM_DB_READ_URL" if url_lectura else "CESYM_DB_URL (sin CESYM_DB_READ_URL, fallback)"
        logger.info(f"[datos_postgres] pendiente/cesym_db: conectando via {fuente}")
        cesym_engine = get_cesym_engine(url_lectura or None)
    with cesym_engine.connect() as conn:
        pendiente = pd.read_sql(text(_SQL_PENDIENTE_CESYM), conn)
    pendiente = pendiente[["cot", "suc", "importe", "concepto"]]
    pendiente["cot"] = _entero_compatible(pendiente["cot"])
    pendiente["suc"] = _entero_compatible(pendiente["suc"])
    pendiente["importe"] = pd.to_numeric(pendiente["importe"], errors="coerce")
    pendiente["concepto"] = (
        pendiente["concepto"].fillna("").astype(str).replace("nan", "")
    )
    return pendiente


# ─── Función pública ─────────────────────────────────────────────────────────────

def cargar_datos_desde_postgres(engine=None, cesym_engine=None) -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]
] | None:
    """
    Lee los cuatro DataFrames desde Postgres y los devuelve en el mismo orden
    y formato que _cargar_datos() de cli.py:
      (facturado, pendiente, facturas_mensual, trabajos, advertencias)

    Devuelve None si la conexión a Postgres falla (OperationalError, timeout):
    el caller (cli._cargar_datos) cae a Excel cuando recibe None.

    Las advertencias son una lista vacía: la validación de calidad de datos
    ya ocurrió cuando el ETL insertó los registros. Si alguna tabla está vacía
    se registra como advertencia informativa (no error).
    """
    eng = engine or get_engine()
    advertencias: list[str] = []

    try:
        with eng.connect() as conn:
            facturado        = pd.read_sql(text(_SQL_FACTURADO),        conn)
            pendiente        = pd.read_sql(text(_SQL_PENDIENTE),        conn)
            facturas_mensual = pd.read_sql(text(_SQL_FACTURAS_MENSUAL), conn)
            trabajos         = pd.read_sql(text(_SQL_TRABAJOS),         conn)
    except OperationalError as exc:
        logger.error(f"[datos_postgres] Conexión a Postgres falló, se usará Excel: {exc}")
        return None

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

    # Detrás de flag (default apagado): `pendiente` desde cesym_db. Se intenta
    # DESPUÉS de tener el pendiente de chatbot_db en mano, para que cualquier
    # fallo (URL ausente, permiso, red, vista borrada) caiga a lo ya leído sin
    # romper el bot ni afectar a los otros tres DataFrames.
    if _flag_pendiente_cesym():
        try:
            pendiente = _cargar_pendiente_desde_cesym(cesym_engine)
            logger.info("[datos_postgres] pendiente leído desde cesym_db.chatbot_pendiente_v1")
        except Exception as exc:  # noqa: BLE001 - fallback deliberado, se loggea
            logger.error(
                "[datos_postgres] USE_CESYM_DB_PENDIENTE=1 pero la lectura de "
                f"cesym_db.chatbot_pendiente_v1 falló; se usa el pendiente de "
                f"chatbot_db como fallback: {exc}"
            )
            advertencias.append("[PG] pendiente: fallback a chatbot_db (cesym_db falló)")

    if facturado.empty:
        advertencias.append("[PG] ordenes_compra OC_EMITIDA está vacía")
    if pendiente.empty:
        advertencias.append("[PG] ordenes_compra COT_PENDIENTE está vacía")
    if facturas_mensual.empty:
        advertencias.append("[PG] tabla facturas está vacía")

    return facturado, pendiente, facturas_mensual, trabajos, advertencias
