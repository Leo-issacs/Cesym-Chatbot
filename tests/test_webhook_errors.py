"""
test_webhook_errors.py
----------------------
Manejo de errores: el bot nunca responde traceback/silencio, siempre algo útil.
  1. Excepción no manejada en run_query → respuesta TwiML amigable (catch-all).
  2. PermissionError al guardar el Excel → mensaje "archivo abierto", no propaga.
  3. datos_postgres devuelve None → cli._cargar_datos cae a Excel.
"""

import asyncio

import pandas as pd
import pytest

import src.webhook as webhook


# ─── 1: catch-all del handler ────────────────────────────────────────────────

class _FakeURL:
    scheme, hostname, path, query = "https", "x", "/webhook", ""


class _FakeRequest:
    headers: dict = {}
    url = _FakeURL()

    async def form(self):
        return {}


def test_run_query_explota_responde_amigable(monkeypatch):
    monkeypatch.delenv("ENFORCE_TWILIO_SIGNATURE", raising=False)
    monkeypatch.delenv("ENFORCE_WHITELIST", raising=False)
    # Hay datos cargados (para llegar a run_query, no a "no hay datos cargados").
    monkeypatch.setitem(webhook._datos, "facturado", pd.DataFrame({"factura": [1]}))

    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(webhook, "run_query", _boom)

    resp = asyncio.run(webhook.webhook(_FakeRequest(), Body="total", From="whatsapp:+5210000000000"))
    contenido = resp.body.decode("utf-8")
    assert "Ocurrió un error procesando tu mensaje" in contenido


# ─── 2: PermissionError al guardar el Excel ──────────────────────────────────

def test_persistir_permission_error_no_propaga(monkeypatch, tmp_path):
    import src.escritor as esc

    monkeypatch.setattr(esc, "_hacer_backup", lambda p: None)

    def _bloqueado(self, *a, **k):
        raise PermissionError("Excel abierto en otro programa")

    monkeypatch.setattr(pd.DataFrame, "to_excel", _bloqueado)

    msg = esc._persistir_seguro(pd.DataFrame({"a": [1, 2]}), tmp_path / "x.xlsx", filas_esperadas=2)
    assert "está abierto" in msg   # mensaje al usuario, sin excepción


# ─── 3: fallback a Excel cuando Postgres devuelve None ───────────────────────

def test_cargar_datos_fallback_cuando_postgres_none(monkeypatch):
    monkeypatch.setenv("USE_POSTGRES_READS", "1")
    import src.cli as cli
    import src.datos_postgres as dp
    from tests.fixtures import datos as fx

    monkeypatch.setattr(dp, "cargar_datos_desde_postgres", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_facturado", lambda: fx.df_facturado_raw())
    monkeypatch.setattr(cli, "load_pendiente", lambda: fx.df_pendiente_raw())
    monkeypatch.setattr(cli, "load_facturas_mensual", lambda: fx.df_facturas_mensual_raw())
    monkeypatch.setattr(cli, "load_trabajos", lambda: fx.df_trabajos_raw())

    facturado, *_ = cli._cargar_datos()
    assert "factura" in facturado.columns   # cayó a Excel pese a USE_POSTGRES_READS=1


def test_operationalerror_interno_retorna_none():
    """A diferencia del test anterior (mockea la función completa), este ejercita el
    except OperationalError INTERNO de cargar_datos_desde_postgres: la conexión cae
    durante el SELECT y la función atrapa la excepción y retorna None (no la propaga)."""
    from sqlalchemy.exc import OperationalError
    from src.datos_postgres import cargar_datos_desde_postgres

    class _EngineCaido:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    assert cargar_datos_desde_postgres(engine=_EngineCaido()) is None
