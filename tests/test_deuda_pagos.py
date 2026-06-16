"""
test_deuda_pagos.py
-------------------
Tests de los comandos nuevos `debe` y `pagos` (src/query_engine.py).

Por qué un fixture dedicado y NO los sintéticos compartidos (datos.py):
  - `pagos` filtra por fecha_pago >= datetime.now() - N meses → necesita fechas
    RELATIVAS a hoy para ser determinista (fechas fijas se volverían stale). Esas
    fechas dinámicas no pueden vivir en el fixture del golden master (rompería su
    determinismo).
  - Agregar facturas al fixture compartido cambiaría la salida de comandos
    existentes (cobradas, buscar cliente, cruce) → snapshots del golden master.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.query_engine import run_query


def _facturas_deuda() -> pd.DataFrame:
    """facturas_mensual ya limpio: pendientes (fecha_pago NaT) y pagadas
    (fecha_pago relativa a hoy), para 2 clientes."""
    hoy = datetime.now()
    return pd.DataFrame([
        # TOYODA — 2 pendientes (deuda = 12500 + 8200 = 20700)
        {"folio": 8078, "cliente": "TOYODA", "fecha": hoy, "concepto": "Mantenimiento equipos AC", "total": 12500.0, "fecha_pago": pd.NaT},
        {"folio": 8079, "cliente": "TOYODA", "fecha": hoy, "concepto": "Instalación unidad central", "total": 8200.0, "fecha_pago": pd.NaT},
        # TOYODA — 2 pagadas: una en el último mes, otra a 45 días (en 2 meses, no en 1)
        {"folio": 8050, "cliente": "TOYODA", "fecha": hoy, "concepto": "Servicio", "total": 15000.0, "fecha_pago": hoy - timedelta(days=15)},
        {"folio": 8061, "cliente": "TOYODA", "fecha": hoy, "concepto": "Reparación", "total": 9500.0, "fecha_pago": hoy - timedelta(days=45)},
        # WALDOS — otra cuenta (1 pendiente, 2 pagadas; concepto con "filtros")
        {"folio": 9001, "cliente": "WALDOS", "fecha": hoy, "concepto": "Servicio", "total": 3000.0, "fecha_pago": pd.NaT},
        {"folio": 9002, "cliente": "WALDOS", "fecha": hoy, "concepto": "Mantenimiento filtros AC", "total": 1000.0, "fecha_pago": hoy - timedelta(days=5)},
        {"folio": 9003, "cliente": "WALDOS", "fecha": hoy, "concepto": "Cambio de filtros", "total": 1500.0, "fecha_pago": hoy - timedelta(days=20)},
    ])


@pytest.fixture
def rq_deuda():
    """rq_deuda('debe TOYODA') → run_query con el fixture de deuda/pagos."""
    facturas = _facturas_deuda()
    vacio = pd.DataFrame()
    return lambda cmd: run_query(cmd, vacio, vacio, facturas, vacio)


# ─── debe ─────────────────────────────────────────────────────────────────────

def test_debe_cliente_con_pendientes(rq_deuda):
    out = rq_deuda("debe TOYODA")
    assert "Total pendiente" in out
    assert "$20,700.00" in out
    assert "(2 facturas)" in out


def test_debe_cliente_inexistente(rq_deuda):
    assert "No se encontraron facturas pendientes" in rq_deuda("debe NOEXISTE")


# ─── pagos ─────────────────────────────────────────────────────────────────────

def test_pagos_ultimo_mes(rq_deuda):
    out = rq_deuda("pagos TOYODA 1")
    assert "$15,000.00" in out          # el pago de hace 15 días
    assert "(1 pagos)" in out
    assert "9,500.00" not in out        # el de 45 días NO entra en 1 mes


def test_pagos_dos_meses_incluye_mas(rq_deuda):
    out = rq_deuda("pagos TOYODA 2")
    assert "$24,500.00" in out          # 15000 + 9500
    assert "(2 pagos)" in out


# ─── alias naturales ──────────────────────────────────────────────────────────

def test_alias_cuanto_nos_debe(rq_deuda):
    assert rq_deuda("cuanto nos debe TOYODA") == rq_deuda("debe TOYODA")


def test_alias_cuanto_pago(rq_deuda):
    assert rq_deuda("cuanto pagó TOYODA 1") == rq_deuda("pagos TOYODA 1")


# ─── concepto / últimos pagos / checa-si-pago ────────────────────────────────

def test_concepto_busca_en_descripcion(rq_deuda):
    out = rq_deuda("concepto filtros")
    assert "No se encontraron" not in out
    assert "9002" in out or "9003" in out          # facturas con "filtros" en concepto


def test_pagos_sin_numero_da_ultimos(rq_deuda):
    out = rq_deuda("pagos WALDOS")
    assert "Últimos pagos" in out
    assert "pagos encontrados" in out


def test_alias_checa_si_pago(rq_deuda):
    assert rq_deuda("checa si pago WALDOS") == rq_deuda("pagos WALDOS")
    assert rq_deuda("cobros WALDOS") == rq_deuda("pagos WALDOS")


def test_tabla_sin_cobrar_tiene_concepto():
    """Cada fila de la tabla de sin-cobrar del reporte trae la clave 'concepto'."""
    from datetime import date
    from src.reporte import _construir_datos_reporte

    df_men = pd.DataFrame({
        "folio": [101], "cliente": ["WALDOS"], "fecha": [date(2026, 5, 1)],
        "concepto": ["Mantenimiento filtros"], "total": [2000.0], "fecha_pago": [pd.NaT],
    })
    vacio = pd.DataFrame()
    datos = _construir_datos_reporte(pd.DataFrame(columns=["factura", "oc", "monto_actual",
                                     "prioridad", "fecha", "estado"]), vacio, df_men, vacio, "mensual")
    assert datos["tabla_facturas"]
    assert all("concepto" in fila for fila in datos["tabla_facturas"])
