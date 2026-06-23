"""Tests herméticos de src/cotizaciones_pg.py con SQLite in-memory."""
import datetime as dt

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src import cotizaciones_pg as cpg

_DDL = [
    """CREATE TABLE clientes (rfc TEXT PRIMARY KEY, nombre_fiscal TEXT NOT NULL,
        nombre_comercial TEXT, tipo TEXT)""",
    """CREATE TABLE sucursales (id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_rfc TEXT NOT NULL, suc TEXT, nombre TEXT,
        UNIQUE (cliente_rfc, suc))""",
    """CREATE TABLE cotizaciones (id INTEGER PRIMARY KEY AUTOINCREMENT,
        cot_num TEXT, cliente_rfc TEXT NOT NULL, sucursal_id INTEGER,
        descripcion TEXT, importe REAL, iva_tasa REAL, fecha TEXT, estado TEXT)""",
]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return eng


def test_crear_cliente_idempotente_no_sobrescribe(engine):
    """ON CONFLICT DO NOTHING: re-crear el mismo RFC no duplica ni sobrescribe."""
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "WALDOS DOLAR MART", "WALDOS")
        # Segunda vez con otros nombres: no falla y NO sobrescribe (DO NOTHING).
        cpg.crear_cliente(conn, "WDM990126350", "OTRO NOMBRE", "OTRO")
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
        nf = conn.execute(text("SELECT nombre_fiscal FROM clientes")).scalar()
        tipo = conn.execute(text("SELECT tipo FROM clientes")).scalar()
    assert n == 1 and nf == "WALDOS DOLAR MART" and tipo == "empresa"


def test_crear_sucursal_devuelve_id(engine):
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "W", "WALDOS")
        sid = cpg.crear_sucursal(conn, "WDM990126350", "5208", "CENTRO")
    assert isinstance(sid, int) and sid > 0


def test_insertar_cotizacion_espeja_cot_num(engine):
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "W", "WALDOS")
        cid = cpg.insertar_cotizacion(conn, {
            "cliente_rfc": "WDM990126350", "sucursal_id": None,
            "descripcion": "Mantenimiento minisplit", "importe": 1000.0,
            "iva_tasa": 0.08, "fecha": dt.date(2026, 6, 22), "estado": "cotizada"})
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT cot_num, estado, iva_tasa FROM cotizaciones WHERE id = :i"),
            {"i": cid}).first()
    assert cid > 0 and row[0] == str(cid) and row[1] == "cotizada" and row[2] == 0.08


def test_guardar_cotizacion_cliente_nuevo_atomico(engine, monkeypatch):
    monkeypatch.setattr(cpg, "get_cesym_engine", lambda *a, **k: engine)
    datos = {
        "cliente_nuevo": True, "cliente_rfc": "OOM090327365",
        "nombre_fiscal": "OHD OPERATORS DE MEXICO", "nombre_comercial": "GENIE",
        "nombre": "GENIE", "sucursal_nueva": False, "sucursal_id": None,
        "descripcion": "Cambio de compresor", "importe": 5000.0, "iva_tasa": 0.16,
    }
    msg = cpg.guardar_cotizacion(datos)
    assert msg.startswith("Cotizacion #1 ")
    assert "GENIE" in msg and "5,800.00" in msg  # total = 5000 * 1.16
    with engine.connect() as conn:
        ncli = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
        estado = conn.execute(text("SELECT estado FROM cotizaciones")).scalar()
    assert ncli == 1 and estado == "cotizada"


def test_guardar_cotizacion_sucursal_nueva(engine, monkeypatch):
    monkeypatch.setattr(cpg, "get_cesym_engine", lambda *a, **k: engine)
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "W", "WALDOS")
    datos = {
        "cliente_nuevo": False, "cliente_rfc": "WDM990126350",
        "nombre_fiscal": "W", "nombre_comercial": "WALDOS", "nombre": "WALDOS",
        "sucursal_nueva": True, "sucursal_id": None, "suc": "5208",
        "sucursal_nombre": "CENTRO",
        "descripcion": "Servicio", "importe": 100.0, "iva_tasa": 0.08,
    }
    cpg.guardar_cotizacion(datos)
    with engine.connect() as conn:
        sid = conn.execute(text("SELECT sucursal_id FROM cotizaciones")).scalar()
        suc = conn.execute(text("SELECT suc FROM sucursales WHERE id = :i"),
                           {"i": sid}).scalar()
    assert suc == "5208"
