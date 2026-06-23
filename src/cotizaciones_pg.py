"""
cotizaciones_pg.py
------------------
Escrituras en cesym_db para el flujo de cotizaciones. Las primitivas reciben una
conexión SQLAlchemy ya abierta y NO manejan la transacción (el caller hace
engine.begin()), igual que escritor_pg.py. `guardar_cotizacion` orquesta todo en
una sola transacción (escrituras diferidas al confirmar).
"""
import datetime as dt
import logging

from sqlalchemy import text

from src.cesym_db import get_cesym_engine

logger = logging.getLogger(__name__)


def crear_cliente(conn, rfc, nombre_fiscal, nombre_comercial, tipo="empresa") -> str:
    """Upsert idempotente de cliente por RFC. Devuelve el RFC."""
    conn.execute(
        text("""
            INSERT INTO clientes (rfc, nombre_fiscal, nombre_comercial, tipo)
            VALUES (:rfc, :nf, :nc, :tipo)
            ON CONFLICT (rfc) DO UPDATE
                SET nombre_fiscal = excluded.nombre_fiscal,
                    nombre_comercial = excluded.nombre_comercial,
                    tipo = excluded.tipo
        """),
        {"rfc": rfc, "nf": nombre_fiscal, "nc": nombre_comercial, "tipo": tipo},
    )
    return rfc


def crear_sucursal(conn, cliente_rfc, suc, nombre) -> int:
    """Crea una sucursal y devuelve su id."""
    return int(conn.execute(
        text("INSERT INTO sucursales (cliente_rfc, suc, nombre) "
             "VALUES (:r, :suc, :n) RETURNING id"),
        {"r": cliente_rfc, "suc": suc, "n": nombre},
    ).scalar_one())


def insertar_cotizacion(conn, datos: dict) -> int:
    """Inserta una cotización, espeja el número en cot_num y devuelve el id."""
    cid = int(conn.execute(
        text("""
            INSERT INTO cotizaciones
                (cliente_rfc, sucursal_id, descripcion, importe, iva_tasa, fecha, estado)
            VALUES (:cliente_rfc, :sucursal_id, :descripcion, :importe, :iva_tasa,
                    :fecha, :estado)
            RETURNING id
        """),
        datos,
    ).scalar_one())
    conn.execute(text("UPDATE cotizaciones SET cot_num = :c WHERE id = :i"),
                 {"c": str(cid), "i": cid})
    return cid


def guardar_cotizacion(datos: dict) -> str:
    """Crea cliente/sucursal nuevos (si aplica) e inserta la cotización en una
    sola transacción. fecha = hoy, estado = 'cotizada'. Devuelve el mensaje de
    confirmación con el número asignado (el id) y el total."""
    eng = get_cesym_engine()
    with eng.begin() as conn:
        if datos.get("cliente_nuevo"):
            crear_cliente(conn, datos["cliente_rfc"], datos["nombre_fiscal"],
                          datos["nombre_comercial"], "empresa")
        if datos.get("sucursal_nueva"):
            sucursal_id = crear_sucursal(conn, datos["cliente_rfc"],
                                         datos["suc"], datos["sucursal_nombre"])
        else:
            sucursal_id = datos.get("sucursal_id")
        cid = insertar_cotizacion(conn, {
            "cliente_rfc": datos["cliente_rfc"],
            "sucursal_id": sucursal_id,
            "descripcion": datos["descripcion"],
            "importe": datos["importe"],
            "iva_tasa": datos["iva_tasa"],
            "fecha": dt.date.today(),
            "estado": "cotizada",
        })
    total = datos["importe"] * (1 + datos["iva_tasa"])
    return (f"Cotizacion #{cid} registrada para {datos['nombre']}. "
            f"Total ${total:,.2f}.")
