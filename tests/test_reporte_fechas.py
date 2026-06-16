"""
test_reporte_fechas.py
----------------------
Regresión del hotfix: Postgres devuelve columnas de fecha como datetime.date;
reporte.py las compara contra pd.Timestamp. Antes lanzaba
"Cannot compare Timestamp with datetime.date". Ahora se normalizan a Timestamp.
"""

from datetime import date

import pandas as pd

from src.reporte import _construir_datos_reporte


def test_construir_reporte_con_fechas_date_no_explota():
    df_men = pd.DataFrame({
        "folio": [100, 101], "cliente": ["TOYODA", "WALDOS"],
        "fecha": [date(2026, 5, 1), date(2026, 6, 1)], "concepto": ["S", "S"],
        "total": [1000.0, 2000.0], "fecha_pago": [date(2026, 5, 10), None],
    })
    df_fac = pd.DataFrame({
        "factura": [1], "oc": [""], "monto_actual": [500.0],
        "prioridad": [""], "fecha": [date(2026, 5, 5)], "estado": ["ACEPTADA"],
    })
    vacio_pen = pd.DataFrame(columns=["cot", "suc", "importe", "concepto"])
    vacio_tra = pd.DataFrame(columns=["mes", "tecnico", "cliente", "rep_num",
                                      "domicilio", "telefono", "tipo_trabajo", "pagado", "recibe"])

    datos = _construir_datos_reporte(df_fac, vacio_pen, df_men, vacio_tra, "mensual")
    assert isinstance(datos, dict)


def test_graficas_con_fechas_date_no_explotan():
    """Los helpers de gráfica del PDF (usan .dt) son robustos con columnas date."""
    from src.reporte import _grafica_facturado_por_mes, _grafica_cobradas_vs_pendientes

    df_fac = pd.DataFrame({"fecha": [date(2026, 5, 1), date(2026, 6, 1)],
                           "monto_actual": [1000.0, 2000.0]})
    df_men = pd.DataFrame({"fecha": [date(2026, 5, 1)], "total": [500.0],
                           "fecha_pago": [date(2026, 5, 10)]})
    # No deben lanzar "Can only use .dt accessor with datetimelike values".
    assert _grafica_facturado_por_mes(df_fac, 400, 200) is not None
    assert _grafica_cobradas_vs_pendientes(df_men, 400, 200) is not None
