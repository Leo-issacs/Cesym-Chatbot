"""
test_facturas_cliente.py
------------------------
Búsqueda de facturas POR CLIENTE (reporte mensual), reutilizando _mask_cliente.

Comandos cubiertos:
  - "facturas de Waldos" / "facturas Waldos"      → facturas del cliente
  - "últimas facturas de Waldos"                  → idem, más recientes primero
  - "facturas <folio>"                            → factura por número (folio)
  - "facturas" (a secas)                          → comportamiento original intacto
"""

import pandas as pd

from src.query_engine import run_query

_VACIO = pd.DataFrame()


def _facturas():
    """facturas_mensual con columnas reales: folio, cliente, fecha, concepto, total, fecha_pago."""
    return pd.DataFrame({
        "folio":      pd.array([101, 102, 103, 201], dtype="Int64"),
        "cliente":    ["WALDOS", "WALDOS", "OXXO", "WALDOS"],
        "fecha":      pd.to_datetime(["2025-09-01", "2025-11-15", "2025-12-01", "2025-10-20"]),
        "concepto":   ["a", "b", "c", "d"],
        "total":      [100.0, 200.0, 300.0, 400.0],
        "fecha_pago": pd.to_datetime(["2025-09-10", pd.NaT, "2025-12-05", pd.NaT]),
    })


def _q(cmd, facturas=None):
    return run_query(cmd, _VACIO, _VACIO, facturas if facturas is not None else _facturas(), _VACIO)


# ─── Por cliente (NUEVO) ──────────────────────────────────────────────────────

def test_facturas_de_cliente_filtra_por_nombre():
    out = _q("facturas de waldos")
    assert "facturas de WALDOS" in out
    # Las 3 de Waldos sí; la de OXXO no.
    assert "Fac 101" in out and "Fac 102" in out and "Fac 201" in out
    assert "Fac 103" not in out


def test_facturas_cliente_sin_de():
    # También sin la preposición: "facturas waldos"
    out = _q("facturas waldos")
    assert "Fac 102" in out and "Fac 103" not in out


def test_facturas_cliente_inexistente():
    out = _q("facturas de zzz")
    assert "No se encontraron facturas de 'zzz'" in out


# ─── "últimas" ordena por fecha desc (NUEVO) ─────────────────────────────────

def test_ultimas_facturas_ordena_por_fecha_desc():
    out = _q("últimas facturas de waldos")
    # Fechas Waldos: 102=15/11, 201=20/10, 101=01/09 → orden desc esperado.
    i102, i201, i101 = out.index("Fac 102"), out.index("Fac 201"), out.index("Fac 101")
    assert i102 < i201 < i101


def test_ultimas_respeta_limite():
    # 20 facturas del mismo cliente, limite por defecto = 15
    df = pd.DataFrame({
        "folio":      pd.array(range(1, 21), dtype="Int64"),
        "cliente":    ["WALDOS"] * 20,
        "fecha":      pd.date_range("2025-01-01", periods=20, freq="D"),
        "concepto":   ["x"] * 20,
        "total":      [10.0] * 20,
        "fecha_pago": [pd.NaT] * 20,
    })
    out = _q("últimas facturas de waldos", df)
    assert "(de 20 en total)" in out
    # La más reciente (folio 20, 20/01) aparece; una vieja fuera del top-15 no.
    assert "Fac 20" in out and "Fac 1 " not in out


# ─── Por número → folio (NUEVO, distingue número de nombre) ──────────────────

def test_facturas_por_folio_numero():
    out = _q("facturas 102")
    assert "Factura 102" in out and "WALDOS" in out
    assert "Fac 101" not in out


def test_folio_inexistente():
    out = _q("facturas 999")
    assert "No se encontró la factura con folio 999" in out


# ─── "facturas" a secas: comportamiento ORIGINAL intacto ─────────────────────

def test_facturas_a_secas_no_busca_por_cliente():
    out = _q("facturas")
    # No debe caer en la búsqueda por cliente (no inventa un cliente vacío).
    assert "No se encontraron facturas de" not in out
