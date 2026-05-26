"""
test_cleaner.py
---------------
Pruebas de limpieza y normalización de datos.

Valida:
  - Que clean_facturado() y clean_pendiente() devuelven la estructura esperada.
  - Que las filas de totales quedan excluidas.
  - Que los tipos de datos son correctos (Int64, float, datetime).
  - Que la conversión de fechas de Excel funciona.
  - Que el DataFrame limpio tiene menos filas que el RAW (totales excluidos).
  - Que no quedan valores no-numéricos en columnas clave.
"""

import pandas as pd
import pytest

from src.loader import load_facturado, load_pendiente
from src.cleaner import clean_facturado, clean_pendiente


COLUMNAS_FACTURADO = ["factura", "oc", "monto_actual", "prioridad", "fecha", "estado"]
COLUMNAS_PENDIENTE = ["cot", "suc", "importe", "concepto"]


class TestCleanFacturado:
    def test_retorna_tuple(self, raw_facturado):
        resultado = clean_facturado(raw_facturado)
        assert isinstance(resultado, tuple) and len(resultado) == 2

    def test_retorna_dataframe_y_lista(self, raw_facturado):
        df, warns = clean_facturado(raw_facturado)
        assert isinstance(df, pd.DataFrame)
        assert isinstance(warns, list)

    def test_columnas_correctas(self, facturado):
        assert list(facturado.columns) == COLUMNAS_FACTURADO, (
            f"Columnas inesperadas: {list(facturado.columns)}"
        )

    def test_no_esta_vacio(self, facturado):
        assert len(facturado) > 0, "El DataFrame limpio está vacío"

    def test_filas_totales_excluidas(self, raw_facturado, facturado):
        """Debe haber menos filas limpias que RAW (se eliminan totales y encabezados)."""
        assert len(facturado) < len(raw_facturado), (
            "El limpiador no eliminó filas de totales o encabezados"
        )

    def test_factura_sin_nulos(self, facturado):
        nulos = facturado["factura"].isna().sum()
        assert nulos == 0, f"Hay {nulos} valores nulos en la columna 'factura'"

    def test_factura_es_numerico(self, facturado):
        assert pd.api.types.is_integer_dtype(facturado["factura"]), (
            f"Tipo inesperado en 'factura': {facturado['factura'].dtype}"
        )

    def test_monto_es_float(self, facturado):
        assert pd.api.types.is_float_dtype(facturado["monto_actual"]), (
            f"Tipo inesperado en 'monto_actual': {facturado['monto_actual'].dtype}"
        )

    def test_fecha_es_datetime(self, facturado):
        assert pd.api.types.is_datetime64_any_dtype(facturado["fecha"]), (
            f"Tipo inesperado en 'fecha': {facturado['fecha'].dtype}"
        )

    def test_no_quedan_filas_de_totales(self, facturado):
        """Asegura que ningún valor de factura es texto (ej: 'TOTAL', 'OC FACTURADO')."""
        valores_texto = facturado["factura"].apply(
            lambda x: isinstance(x, str) and not str(x).isdigit()
        )
        assert not valores_texto.any(), "Quedan filas de texto en la columna 'factura'"

    def test_montos_positivos_o_nan(self, facturado):
        """Todos los montos válidos deben ser positivos."""
        validos = facturado["monto_actual"].dropna()
        negativos = (validos < 0).sum()
        assert negativos == 0, f"Hay {negativos} montos negativos"

    def test_fechas_convertidas_correctamente(self, facturado):
        """Las fechas no deben ser fechas de época 1970 (indica conversión fallida)."""
        fechas_validas = facturado["fecha"].dropna()
        if len(fechas_validas) > 0:
            anio_minimo = fechas_validas.dt.year.min()
            assert anio_minimo >= 2000, (
                f"Fechas sospechosas detectadas (año mínimo: {anio_minimo})"
            )

    def test_no_modifica_dataframe_original(self, raw_facturado):
        """La limpieza trabaja sobre copias, no modifica el DataFrame de entrada."""
        columnas_antes = list(raw_facturado.columns)
        filas_antes = len(raw_facturado)
        clean_facturado(raw_facturado)
        assert list(raw_facturado.columns) == columnas_antes
        assert len(raw_facturado) == filas_antes


class TestCleanPendiente:
    def test_retorna_tuple(self, raw_pendiente):
        resultado = clean_pendiente(raw_pendiente)
        assert isinstance(resultado, tuple) and len(resultado) == 2

    def test_retorna_dataframe_y_lista(self, raw_pendiente):
        df, warns = clean_pendiente(raw_pendiente)
        assert isinstance(df, pd.DataFrame)
        assert isinstance(warns, list)

    def test_columnas_correctas(self, pendiente):
        assert list(pendiente.columns) == COLUMNAS_PENDIENTE, (
            f"Columnas inesperadas: {list(pendiente.columns)}"
        )

    def test_no_esta_vacio(self, pendiente):
        assert len(pendiente) > 0, "El DataFrame limpio de pendientes está vacío"

    def test_filas_totales_excluidas(self, raw_pendiente, pendiente):
        assert len(pendiente) < len(raw_pendiente), (
            "El limpiador no eliminó filas de totales en pendientes"
        )

    def test_cot_sin_nulos(self, pendiente):
        nulos = pendiente["cot"].isna().sum()
        assert nulos == 0, f"Hay {nulos} valores nulos en la columna 'cot'"

    def test_cot_es_numerico(self, pendiente):
        assert pd.api.types.is_integer_dtype(pendiente["cot"]), (
            f"Tipo inesperado en 'cot': {pendiente['cot'].dtype}"
        )

    def test_importe_es_float(self, pendiente):
        assert pd.api.types.is_float_dtype(pendiente["importe"]), (
            f"Tipo inesperado en 'importe': {pendiente['importe'].dtype}"
        )

    def test_suc_es_numerico(self, pendiente):
        assert pd.api.types.is_integer_dtype(pendiente["suc"]), (
            f"Tipo inesperado en 'suc': {pendiente['suc'].dtype}"
        )

    def test_no_modifica_dataframe_original(self, raw_pendiente):
        columnas_antes = list(raw_pendiente.columns)
        filas_antes = len(raw_pendiente)
        clean_pendiente(raw_pendiente)
        assert list(raw_pendiente.columns) == columnas_antes
        assert len(raw_pendiente) == filas_antes
