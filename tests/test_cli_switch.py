"""
test_cli_switch.py
------------------
Wiring del switch USE_POSTGRES_READS en cli._cargar_datos (PR-14).

Tras activar Postgres por defecto, se verifica la lógica de ramificación SIN una
BD real (se hace monkeypatch de la lectura de Postgres y de los loaders de Excel):
  - sin la variable → toma la rama Postgres (default = "1");
  - USE_POSTGRES_READS=0 → fuerza Excel y no toca Postgres;
  - default + Postgres falla → cae a Excel.

La igualdad de OUTPUT entre ambas rutas se prueba aparte, contra una Postgres real,
en tests/test_equivalencia_postgres.py.
"""

import pandas as pd
import pytest

import src.cli as cli
import src.datos_postgres as dp
from tests.fixtures import datos as fx

# Tupla con la forma que devuelve _cargar_datos: (fac, pen, men, tra, advertencias)
_CENTINELA_PG = (
    pd.DataFrame({"marca_postgres": [1]}),
    pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), [],
)


def _stub_loaders_excel(monkeypatch):
    """Hace que la rama Excel use datos sintéticos en vez de data/raw/."""
    monkeypatch.setattr(cli, "load_facturado", lambda: fx.df_facturado_raw())
    monkeypatch.setattr(cli, "load_pendiente", lambda: fx.df_pendiente_raw())
    monkeypatch.setattr(cli, "load_facturas_mensual", lambda: fx.df_facturas_mensual_raw())
    monkeypatch.setattr(cli, "load_trabajos", lambda: fx.df_trabajos_raw())


def test_default_lee_postgres(monkeypatch):
    """Sin la variable, el default es "1" → toma la rama Postgres."""
    monkeypatch.delenv("USE_POSTGRES_READS", raising=False)
    monkeypatch.setattr(dp, "cargar_datos_desde_postgres", lambda *a, **k: _CENTINELA_PG)
    resultado = cli._cargar_datos()
    assert resultado is _CENTINELA_PG


def test_flag_cero_fuerza_excel(monkeypatch):
    """USE_POSTGRES_READS=0 → ni siquiera intenta Postgres; usa Excel."""
    monkeypatch.setenv("USE_POSTGRES_READS", "0")

    def _no_llamar(*a, **k):
        raise AssertionError("no debe leer Postgres con USE_POSTGRES_READS=0")

    monkeypatch.setattr(dp, "cargar_datos_desde_postgres", _no_llamar)
    _stub_loaders_excel(monkeypatch)

    facturado, *_ = cli._cargar_datos()
    assert list(facturado.columns) == ["factura", "oc", "monto_actual", "prioridad", "fecha", "estado"]


def test_fallback_a_excel_si_postgres_falla(monkeypatch):
    """Default Postgres, pero si la lectura falla cae a Excel (no propaga la excepción)."""
    monkeypatch.delenv("USE_POSTGRES_READS", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("Postgres caído")

    monkeypatch.setattr(dp, "cargar_datos_desde_postgres", _boom)
    _stub_loaders_excel(monkeypatch)

    facturado, *_ = cli._cargar_datos()
    assert "factura" in facturado.columns  # cayó a Excel pese al default Postgres
