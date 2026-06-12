"""
conftest.py
-----------
Fixtures compartidas para los tests. Se construyen 100% con DATOS SINTÉTICOS
(tests/fixtures/), nunca desde data/raw/. Así los tests validan la LÓGICA de
limpieza/lectura y no el contenido del Excel del mes.

Los chequeos que sí dependen de los datos reales (conteos, % de facturas sin
fecha de pago, etc.) viven en scripts/data_quality.py, fuera de pytest.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cleaner import (
    clean_facturado,
    clean_pendiente,
    clean_facturas_mensual,
    clean_trabajos,
)
from tests.fixtures import datos as fx


# ─── OC FACTURADO ────────────────────────────────────────────────────────────
@pytest.fixture
def raw_facturado():
    return fx.df_facturado_raw()


@pytest.fixture
def facturado(raw_facturado):
    df, _ = clean_facturado(raw_facturado)
    return df


@pytest.fixture
def advertencias_facturado(raw_facturado):
    _, warns = clean_facturado(raw_facturado)
    return warns


# ─── PTE OC ──────────────────────────────────────────────────────────────────
@pytest.fixture
def raw_pendiente():
    return fx.df_pendiente_raw()


@pytest.fixture
def pendiente(raw_pendiente):
    df, _ = clean_pendiente(raw_pendiente)
    return df


@pytest.fixture
def advertencias_pendiente(raw_pendiente):
    _, warns = clean_pendiente(raw_pendiente)
    return warns


# ─── Reporte mensual de facturas ─────────────────────────────────────────────
@pytest.fixture
def raw_facturas_mensual():
    return fx.df_facturas_mensual_raw()


@pytest.fixture
def facturas_mensual(raw_facturas_mensual):
    df, _ = clean_facturas_mensual(raw_facturas_mensual)
    return df


@pytest.fixture
def advertencias_facturas_mensual(raw_facturas_mensual):
    _, warns = clean_facturas_mensual(raw_facturas_mensual)
    return warns


# ─── Control de trabajos ─────────────────────────────────────────────────────
@pytest.fixture
def raw_trabajos():
    return fx.df_trabajos_raw()


@pytest.fixture
def trabajos(raw_trabajos):
    df, _ = clean_trabajos(raw_trabajos)
    return df


@pytest.fixture
def advertencias_trabajos(raw_trabajos):
    _, warns = clean_trabajos(raw_trabajos)
    return warns


# ─── Mini-Excel de cartera (para tests de loader.py) ─────────────────────────
@pytest.fixture(scope="session")
def excel_cartera(tmp_path_factory):
    """Escribe una sola vez un .xlsx sintético con la estructura real de cartera."""
    destino = tmp_path_factory.mktemp("cartera") / "CARTERA_SINTETICA.xlsx"
    return fx.escribir_excel_cartera(destino)
