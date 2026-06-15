"""
test_migracion.py
-----------------
Tests del UPSERT de scripts/migrar_sqlite_a_postgres.py.

Herméticos: el "origen" es un SQLite in-memory con el esquema de cesym.db, y el
"destino Postgres" es otro SQLite con un schema `chatbot` adjunto (ATTACH), donde
el SQL `{SCHEMA}.facturas` (= chatbot.facturas) resuelve igual. No se usa Postgres.

Nota SQLite: `CAST('2026-06-15' AS DATE)` en SQLite devuelve `2026` (el año), no
la fecha. Por eso las aserciones sobre fechas verifican "pasó de NULL a no-NULL"
y se apoyan en columnas sin CAST (total) para el valor exacto.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

# Cargar el script de migración como módulo (no es un paquete importable).
_RUTA = Path(__file__).parent.parent / "scripts" / "migrar_sqlite_a_postgres.py"
_spec = importlib.util.spec_from_file_location("migracion_cesym", _RUTA)
migracion = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migracion)


def _origen() -> sqlite3.Connection:
    """SQLite 'origen' (cesym.db) con facturas y clientes."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE facturas (
            id INTEGER PRIMARY KEY, folio INTEGER UNIQUE, cliente_id INTEGER,
            fecha_emision TEXT, concepto TEXT, total REAL, fecha_pago TEXT, cancelada INTEGER)
    """)
    conn.execute("""
        CREATE TABLE clientes (
            id INTEGER PRIMARY KEY, nombre TEXT, nombre_raw TEXT, fuente TEXT)
    """)
    return conn


def _destino_pg():
    """Engine 'Postgres' stand-in: SQLite con un schema `chatbot` adjunto."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS chatbot"))
        c.execute(text("""
            CREATE TABLE chatbot.facturas (
                id INTEGER PRIMARY KEY, folio INTEGER UNIQUE, cliente_id INTEGER,
                fecha_emision, concepto TEXT, total REAL, fecha_pago, cancelada INTEGER)
        """))
        c.execute(text("""
            CREATE TABLE chatbot.clientes (
                id INTEGER PRIMARY KEY, nombre TEXT, nombre_raw TEXT, fuente TEXT)
        """))
    return eng


def _insert_factura(src, folio, total, fecha_pago):
    src.execute(
        "INSERT INTO facturas (id, folio, cliente_id, fecha_emision, concepto, total, fecha_pago, cancelada) "
        "VALUES (1, ?, NULL, '2026-01-01', 'Servicio', ?, ?, 0)",
        (folio, total, fecha_pago),
    )
    src.commit()


# ─── 1: upsert actualiza factura existente ───────────────────────────────────
def test_upsert_actualiza_factura_existente():
    src, dst = _origen(), _destino_pg()
    _insert_factura(src, folio=8001, total=1000, fecha_pago=None)   # impaga
    migracion.migrar_facturas(src, dst, "upsert")

    # En el origen cambia: ahora pagada y con total corregido.
    src.execute("UPDATE facturas SET fecha_pago='2026-06-15', total=1200 WHERE folio=8001")
    src.commit()
    migracion.migrar_facturas(src, dst, "upsert")

    with dst.connect() as c:
        total, fecha_pago = c.execute(
            text("SELECT total, fecha_pago FROM chatbot.facturas WHERE folio=8001")
        ).first()
    assert total == 1200            # total actualizado
    assert fecha_pago is not None   # fecha_pago dejó de ser NULL (factura ahora pagada)


# ─── 2: upsert inserta factura nueva ─────────────────────────────────────────
def test_upsert_inserta_factura_nueva():
    src, dst = _origen(), _destino_pg()
    _insert_factura(src, folio=9001, total=500, fecha_pago=None)
    migracion.migrar_facturas(src, dst, "upsert")

    with dst.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM chatbot.facturas WHERE folio=9001")).scalar()
        total = c.execute(text("SELECT total FROM chatbot.facturas WHERE folio=9001")).scalar()
    assert n == 1 and total == 500


# ─── 3: --modo insertar NO actualiza (DO NOTHING) ────────────────────────────
def test_insertar_no_actualiza_existente():
    src, dst = _origen(), _destino_pg()
    _insert_factura(src, folio=8001, total=1000, fecha_pago=None)
    migracion.migrar_facturas(src, dst, "insertar")

    src.execute("UPDATE facturas SET total=1200 WHERE folio=8001")
    src.commit()
    migracion.migrar_facturas(src, dst, "insertar")   # DO NOTHING

    with dst.connect() as c:
        total = c.execute(text("SELECT total FROM chatbot.facturas WHERE folio=8001")).scalar()
    assert total == 1000   # NO se actualizó


# ─── 4: clientes (catálogo) siempre DO NOTHING ───────────────────────────────
def test_clientes_do_nothing_no_sobrescribe():
    src, dst = _origen(), _destino_pg()
    src.execute("INSERT INTO clientes (id, nombre, nombre_raw, fuente) VALUES (1, 'TOYODA', 'toyoda', 'FACTURAS')")
    src.commit()
    migracion.migrar_clientes(src, dst)

    # Variante del mismo cliente (mismo id) con nombre distinto.
    src.execute("UPDATE clientes SET nombre='TOYODA SA' WHERE id=1")
    src.commit()
    migracion.migrar_clientes(src, dst)   # ON CONFLICT (id) DO NOTHING

    with dst.connect() as c:
        nombre = c.execute(text("SELECT nombre FROM chatbot.clientes WHERE id=1")).scalar()
    assert nombre == 'TOYODA'   # NO se sobrescribió el canónico original
