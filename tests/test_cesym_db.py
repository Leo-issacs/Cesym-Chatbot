"""Tests herméticos de src/cesym_db.py con SQLite in-memory (tablas desnudas que
reflejan public.clientes / public.sucursales de cesym_db)."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src import cesym_db

_DDL = [
    """CREATE TABLE clientes (
        rfc TEXT PRIMARY KEY, nombre_fiscal TEXT NOT NULL,
        nombre_comercial TEXT, tipo TEXT)""",
    """CREATE TABLE sucursales (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_rfc TEXT NOT NULL,
        suc TEXT, nombre TEXT)""",
]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
        conn.execute(text(
            "INSERT INTO clientes (rfc, nombre_fiscal, nombre_comercial, tipo) VALUES "
            "('WDM990126350','WALDOS DOLAR MART','WALDOS','empresa'),"
            "('DME860313ND7','DURA DE MEXICO','DURA','empresa')"))
        conn.execute(text(
            "INSERT INTO sucursales (cliente_rfc, suc, nombre) VALUES "
            "('WDM990126350','5208','WALDOS CENTRO')"))
    return eng


def test_buscar_por_nombre_parcial(engine):
    res = cesym_db.buscar_clientes("waldo", engine=engine)
    assert len(res) == 1 and res[0]["rfc"] == "WDM990126350"


def test_buscar_por_rfc_exacto(engine):
    res = cesym_db.buscar_clientes("dme860313nd7", engine=engine)
    assert len(res) == 1 and res[0]["nombre_comercial"] == "DURA"


def test_buscar_sin_resultados(engine):
    assert cesym_db.buscar_clientes("zzz", engine=engine) == []


def test_listar_sucursales(engine):
    sucs = cesym_db.listar_sucursales("WDM990126350", engine=engine)
    assert len(sucs) == 1 and sucs[0]["suc"] == "5208"
