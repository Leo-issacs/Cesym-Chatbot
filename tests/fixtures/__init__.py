"""
tests/fixtures
--------------
Datos sintéticos construidos EN CÓDIGO para los tests. El objetivo es que los
tests validen la LÓGICA de limpieza/lectura, no el contenido del Excel del mes.
Ningún test debe leer data/raw/ — para eso está scripts/data_quality.py.

Los builders viven en `datos.py`; se re-exportan aquí por comodidad.
"""

from tests.fixtures.datos import (  # noqa: F401
    df_facturado_raw,
    df_pendiente_raw,
    df_facturas_mensual_raw,
    df_trabajos_raw,
    escribir_excel_cartera,
)
