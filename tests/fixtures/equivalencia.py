"""
tests/fixtures/equivalencia.py
------------------------------
Dataset A MEDIDA para la prueba de equivalencia Excel ↔ Postgres (PR-12).

A diferencia de los fixtures de cleaner (tests/fixtures/datos.py), estos datos
son REPRESENTABLES EN AMBAS RUTAS:
  - sin folios duplicados (chatbot.facturas.folio es UNIQUE);
  - clientes ya en MAYÚSCULAS y sin espacios (el upper/strip del cleaner es no-op,
    así el mismo cliente sale igual leyendo de Excel o de Postgres);
  - los "vacíos" solo se usan en columnas que limpian a "" en ambas rutas
    (prioridad/estado vía replace('nan','') en Excel y COALESCE(...,'') en SQL),
    o en numéricas/fechas (→ NaN/NaT en ambas).

El MISMO dataset se materializa de dos formas:
  - como mini-Excels (ruta loader→cleaner), via `cargar_dfs_excel()`;
  - como filas en el schema `chatbot`, via `poblar_postgres()`.

Así la prueba demuestra que run_query responde EXACTAMENTE lo mismo por las dos
rutas (ver tests/test_equivalencia_postgres.py).
"""

from datetime import date

import pandas as pd
from sqlalchemy import text

from src.cleaner import (
    clean_facturado,
    clean_pendiente,
    clean_facturas_mensual,
    clean_trabajos,
)
from src.db_postgres import SCHEMA, SCHEMA_SQL


# ─── Dataset canónico (una sola fuente de verdad para ambas materializaciones) ─

# OC FACTURADO → facturado: factura, oc, monto, prioridad, estado, fecha(ISO)
FACTURADO = [
    (9001, "OC-A1", 1000.00, "",          "ACEPTADA",      "2026-01-10"),
    (9002, "OC-A2", 2500.50, "PRIORIDAD", "PREV ACEPTADO", "2026-02-15"),
    (9003, "OC-A3", None,    "",          "",              "2026-03-20"),  # monto NaN, estado vacío
    (9004, "OC-A4", 1750.25, "",          "ACEPTADA",      "2026-03-25"),
]

# PTE OC → pendiente: cot, suc, importe, concepto
PENDIENTE = [
    (501, 1, 4000.00, "INSTALACION MINISPLIT"),
    (502, 2, 3200.00, "MANTENIMIENTO"),
    (503, 1, 1500.00, "REVISION"),
]

# Reporte mensual → facturas_mensual: folio, cliente, fecha(ISO), concepto, total, fecha_pago(ISO)
MENSUAL = [
    (7001, "TOYODA",       "2026-01-05", "SERVICIO",      5000.00, "2026-01-20"),
    (7002, "TEC Y DISENO", "2026-02-08", "MANTENIMIENTO", 3000.00, None),         # sin cobrar
    (7003, "TOYODA",       "2026-02-12", "REPARACION",    1200.00, "2026-02-25"),
    (7004, "ACME SA",      "2026-03-01", "INSTALACION",   None,    "2026-03-10"),  # total NaN
]

# Control de trabajos → trabajos
TRABAJOS = [
    # mes, tecnico, cliente, rep_num, domicilio, telefono, tipo_trabajo, pagado, recibe
    ("ENERO",   "JUAN",  "TOYODA",  "T1", "CALLE 1", "5551111", "INSTALACION",   2000.00, "PEDRO"),
    ("FEBRERO", "MARIA", "ACME SA", "T2", "CALLE 2", "5552222", "MANTENIMIENTO", None,    "LUIS"),
    ("MARZO",   "JUAN",  "TOYODA",  "T3", "CALLE 3", "5553333", "REPARACION",    800.00,  "ANA"),
]

# Comandos representativos para el golden master de equivalencia.
COMANDOS = [
    ("total",                 "total"),
    ("resumen",               "resumen"),
    ("facturas",              "facturas"),
    ("pendientes_suc1",       "pendientes 1"),
    ("buscar_factura_9001",   "buscar factura 9001"),
    ("buscar_oc_a",           "buscar oc OC-A"),
    ("buscar_cliente_toyoda", "buscar cliente TOYODA"),
    ("buscar_suc_1",          "buscar suc 1"),
    ("cobradas",              "cobradas"),
    ("sin_cobrar",            "sin cobrar"),
    ("trabajos",              "trabajos"),
    ("estado_prioridad",      "estado prioridad"),
    ("errores",               "errores"),
    ("ayuda",                 "ayuda"),
    ("comando_invalido",      "comando_que_no_existe"),
]


# ─── Materialización A: DataFrames raw → cleaner (la "ruta Excel") ───────────
#
# Alimentamos el MISMO cleaner que usa la ruta Excel en producción, desde raw en
# memoria (los vacíos como "", igual que tests/fixtures/datos.py). No pasamos por
# un .xlsx real a propósito: con pandas 3.0, las celdas en blanco vuelven <NA>
# (astype(str) ya no las hace "nan"), un artefacto del loader ajeno a la
# equivalencia cleaner↔Postgres que probamos aquí. El loader está cubierto por
# tests/test_loader.py.

def _ddmmyyyy(iso: str | None) -> str:
    """ISO 'YYYY-MM-DD' → texto 'DD/MM/YYYY' (lo que el cleaner del mensual parsea)."""
    if not iso:
        return ""
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def df_facturado_raw() -> pd.DataFrame:
    columnas = ["FACTURA", "OC", "CURTRXAM", "ORCTRXAM1", "FECHA_CALCULO", "ESTADO"]
    filas = [[factura, oc, monto, prioridad, date.fromisoformat(fecha), estado]
             for factura, oc, monto, prioridad, estado, fecha in FACTURADO]
    filas.append(["TOTAL", None, None, None, None, None])  # fila de totales → se descarta
    return pd.DataFrame(filas, columns=columnas)


def df_pendiente_raw() -> pd.DataFrame:
    columnas = ["VACIA", "COT", "SUC", "IMPORTE", "CONCEPTO"]
    filas = [[None, cot, suc, importe, concepto]
             for cot, suc, importe, concepto in PENDIENTE]
    filas.append([None, "TOTAL", None, None, None])
    return pd.DataFrame(filas, columns=columnas)


def df_facturas_mensual_raw() -> pd.DataFrame:
    columnas = ["Folio", " Cliente ", "Fecha", "Concepto", " Total ", "FECHA DE PAGO"]
    filas = [[str(folio), cliente, _ddmmyyyy(fecha), concepto,
              "" if total is None else f"{total:.2f}", _ddmmyyyy(fecha_pago)]
             for folio, cliente, fecha, concepto, total, fecha_pago in MENSUAL]
    filas.append(["TOTAL", "", "", "", "", ""])
    return pd.DataFrame(filas, columns=columnas)


def df_trabajos_raw() -> pd.DataFrame:
    columnas = ["MES", "TECNICO", "CLIENTE", "REP #", "DOMICILIO", "TELEFONO",
                "TIPO DE TRABAJO", "Unnamed: 7", "PAGADO", "RECIBE"]
    filas = [[mes, tec, cli, rep, dom, tel, tipo, "",
              "" if pagado is None else f"{pagado:.2f}", recibe]
             for mes, tec, cli, rep, dom, tel, tipo, pagado, recibe in TRABAJOS]
    return pd.DataFrame(filas, columns=columnas)


def cargar_dfs_via_cleaner() -> tuple:
    """Devuelve (facturado, pendiente, facturas_mensual, trabajos) limpios desde
    el cleaner — la mitad "Excel" de la equivalencia."""
    facturado, _ = clean_facturado(df_facturado_raw())
    pendiente, _ = clean_pendiente(df_pendiente_raw())
    mensual, _ = clean_facturas_mensual(df_facturas_mensual_raw())
    trabajos, _ = clean_trabajos(df_trabajos_raw())
    return facturado, pendiente, mensual, trabajos


# ─── Materialización B: tablas del schema chatbot en Postgres ─────────────────

def _fecha(iso: str | None):
    return date.fromisoformat(iso) if iso else None


def poblar_postgres(engine) -> None:
    """Recrea el schema `chatbot` y lo llena con el dataset canónico.

    Destructivo sobre el schema chatbot: usar SIEMPRE contra una BD desechable
    (el servicio efímero de CI vía TEST_DATABASE_URL), nunca producción.
    """
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        conn.execute(text(SCHEMA_SQL))

    with engine.begin() as conn:
        # clientes y tecnicos (nombres únicos preservando el orden de aparición)
        nombres_cli, nombres_tec = [], []
        for fila in MENSUAL:
            if fila[1] not in nombres_cli:
                nombres_cli.append(fila[1])
        for fila in TRABAJOS:
            if fila[2] not in nombres_cli:
                nombres_cli.append(fila[2])
            if fila[1] not in nombres_tec:
                nombres_tec.append(fila[1])

        cli_id, tec_id = {}, {}
        for nombre in nombres_cli:
            cli_id[nombre] = conn.execute(
                text(f"INSERT INTO {SCHEMA}.clientes (nombre) VALUES (:n) RETURNING id"),
                {"n": nombre},
            ).scalar()
        for nombre in nombres_tec:
            tec_id[nombre] = conn.execute(
                text(f"INSERT INTO {SCHEMA}.tecnicos (nombre) VALUES (:n) RETURNING id"),
                {"n": nombre},
            ).scalar()

        # ordenes_compra: primero OC_EMITIDA (ids ascendentes = orden de FACTURADO)
        for factura, oc, monto, prioridad, estado, fecha in FACTURADO:
            conn.execute(
                text(f"""
                    INSERT INTO {SCHEMA}.ordenes_compra
                        (tipo, folio_factura, numero_oc, monto, prioridad, estado, fecha)
                    VALUES ('OC_EMITIDA', :folio, :oc, :monto, :prio, :estado, :fecha)
                """),
                {"folio": factura, "oc": oc or None, "monto": monto,
                 "prio": prioridad or None, "estado": estado or None,
                 "fecha": _fecha(fecha)},
            )
        # luego COT_PENDIENTE
        for cot, suc, importe, concepto in PENDIENTE:
            conn.execute(
                text(f"""
                    INSERT INTO {SCHEMA}.ordenes_compra
                        (tipo, num_cotizacion, sucursal, monto, concepto)
                    VALUES ('COT_PENDIENTE', :cot, :suc, :monto, :concepto)
                """),
                {"cot": cot, "suc": suc, "monto": importe, "concepto": concepto},
            )

        # facturas (reporte mensual)
        for folio, cliente, fecha, concepto, total, fecha_pago in MENSUAL:
            conn.execute(
                text(f"""
                    INSERT INTO {SCHEMA}.facturas
                        (folio, cliente_id, fecha_emision, concepto, total, fecha_pago, cancelada)
                    VALUES (:folio, :cid, :fe, :concepto, :total, :fp, 0)
                """),
                {"folio": folio, "cid": cli_id[cliente], "fe": _fecha(fecha),
                 "concepto": concepto, "total": total, "fp": _fecha(fecha_pago)},
            )

        # trabajos (ids ascendentes = orden de TRABAJOS)
        for mes, tec, cli, rep, dom, tel, tipo, pagado, recibe in TRABAJOS:
            conn.execute(
                text(f"""
                    INSERT INTO {SCHEMA}.trabajos
                        (mes, tecnico_id, cliente_id, rep_num, domicilio, telefono,
                         tipo_trabajo, pagado, recibe)
                    VALUES (:mes, :tid, :cid, :rep, :dom, :tel, :tipo, :pagado, :recibe)
                """),
                {"mes": mes, "tid": tec_id[tec], "cid": cli_id[cli], "rep": rep,
                 "dom": dom, "tel": tel, "tipo": tipo, "pagado": pagado, "recibe": recibe},
            )
