"""
test_loader.py
--------------
Pruebas de la LÓGICA de lectura (src/loader.py) contra un mini-Excel SINTÉTICO
(fixture excel_cartera). Validan que la detección dinámica de encabezado funciona
pese a filas de preámbulo, no que exista el Excel real del mes.

Los chequeos sobre el Excel real (existe, 3 hojas, conteos) viven en
scripts/data_quality.py.
"""

import pandas as pd
import pytest

from src.loader import load_facturado, load_pendiente


def _cols_upper(df):
    return [str(c).strip().upper() for c in df.columns]


class TestDeteccionDinamicaFacturado:
    def test_detecta_header_pese_al_preambulo(self, excel_cartera):
        """El encabezado real está en la 2ª fila (tras el título); debe detectarse."""
        df = load_facturado(excel_path=excel_cartera)
        cols = _cols_upper(df)
        assert "FACTURA" in cols and "OC" in cols
        # El título de preámbulo NO debe haberse tomado como encabezado.
        assert "CARTERA AL 11032026" not in cols

    def test_devuelve_dataframe_no_vacio(self, excel_cartera):
        df = load_facturado(excel_path=excel_cartera)
        assert isinstance(df, pd.DataFrame) and len(df) > 0

    def test_multiples_columnas(self, excel_cartera):
        df = load_facturado(excel_path=excel_cartera)
        assert df.shape[1] >= 5

    def test_devuelve_raw_sin_limpiar(self, excel_cartera):
        """loader NO limpia: la fila de totales 'TOTAL' sigue presente en el RAW."""
        df = load_facturado(excel_path=excel_cartera)
        assert df.iloc[:, 0].astype(str).str.contains("TOTAL").any()


class TestDeteccionDinamicaPendiente:
    def test_detecta_header_en_segunda_columna(self, excel_cartera):
        """En PTE OC el keyword 'COT' está en la columna 1 (no la 0)."""
        df = load_pendiente(excel_path=excel_cartera)
        cols = _cols_upper(df)
        assert "COT" in cols and "SUC" in cols

    def test_devuelve_dataframe_no_vacio(self, excel_cartera):
        df = load_pendiente(excel_path=excel_cartera)
        assert isinstance(df, pd.DataFrame) and len(df) > 0


class TestErroresDeEstructura:
    def test_lanza_valueerror_si_no_encuentra_header(self, tmp_path):
        """Si la hoja no tiene el keyword esperado, loader avisa con ValueError."""
        ruta = tmp_path / "CARTERA_MALA.xlsx"
        with pd.ExcelWriter(ruta, engine="openpyxl") as writer:
            # Hoja con el nombre correcto pero SIN la columna 'FACTURA'.
            pd.DataFrame(
                [["columna_x", "columna_y"], [1, 2]]
            ).to_excel(writer, sheet_name="OC FACTURADO", header=False, index=False)

        with pytest.raises(ValueError):
            load_facturado(excel_path=ruta)
