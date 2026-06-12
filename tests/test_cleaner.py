"""
test_cleaner.py
---------------
Pruebas de la LÓGICA de limpieza/normalización (src/cleaner.py) contra datos
SINTÉTICOS (tests/fixtures/). No dependen del contenido del Excel del mes; los
asserts validan transformaciones concretas (ej. "TOYODA  " → "TOYODA",
des-inversión de fechas ISO), no conteos de datos reales.

Los chequeos sobre datos reales viven en scripts/data_quality.py.
"""

import pandas as pd
import pytest

from src.cleaner import (
    clean_facturado,
    clean_pendiente,
    clean_facturas_mensual,
    clean_trabajos,
)

COLUMNAS_FACTURADO = ["factura", "oc", "monto_actual", "prioridad", "fecha", "estado"]
COLUMNAS_PENDIENTE = ["cot", "suc", "importe", "concepto"]
COLUMNAS_MENSUAL = ["folio", "cliente", "fecha", "concepto", "total", "fecha_pago"]
COLUMNAS_TRABAJOS = ["mes", "tecnico", "cliente", "rep_num", "domicilio",
                     "telefono", "tipo_trabajo", "pagado", "recibe"]


class TestCleanFacturado:
    def test_retorna_df_y_lista(self, raw_facturado):
        df, warns = clean_facturado(raw_facturado)
        assert isinstance(df, pd.DataFrame) and isinstance(warns, list)

    def test_columnas_correctas(self, facturado):
        assert list(facturado.columns) == COLUMNAS_FACTURADO

    def test_descarta_filas_de_totales(self, facturado):
        """Las filas 'TOTAL'/'OC FACTURADO' (factura no numérica) se eliminan."""
        # En el fixture hay 6 facturas válidas + 2 filas de totales.
        assert len(facturado) == 6
        assert not facturado["factura"].astype(str).str.contains("TOTAL").any()

    def test_factura_es_entero_sin_nulos(self, facturado):
        assert pd.api.types.is_integer_dtype(facturado["factura"])
        assert facturado["factura"].isna().sum() == 0

    def test_monto_float_y_fecha_datetime(self, facturado):
        assert pd.api.types.is_float_dtype(facturado["monto_actual"])
        assert pd.api.types.is_datetime64_any_dtype(facturado["fecha"])

    def test_conserva_facturas_duplicadas(self, facturado):
        """clean_facturado NO deduplica: la 8002 repetida debe seguir 2 veces."""
        assert (facturado["factura"] == 8002).sum() == 2

    def test_advierte_monto_invalido_sin_oc_y_sin_fecha(self, advertencias_facturado):
        texto = " | ".join(advertencias_facturado)
        assert "monto inválido" in texto      # factura 8004 con monto NaN
        assert "sin OC" in texto               # factura 8003 sin OC
        assert "sin fecha" in texto            # factura 8005 sin fecha

    def test_no_modifica_el_dataframe_de_entrada(self, raw_facturado):
        cols, filas = list(raw_facturado.columns), len(raw_facturado)
        clean_facturado(raw_facturado)
        assert list(raw_facturado.columns) == cols and len(raw_facturado) == filas


class TestCleanPendiente:
    def test_columnas_correctas(self, pendiente):
        assert list(pendiente.columns) == COLUMNAS_PENDIENTE

    def test_descarta_totales_y_tipa(self, pendiente):
        assert len(pendiente) == 5  # 5 cotizaciones válidas (se descarta el TOTAL)
        assert pd.api.types.is_integer_dtype(pendiente["cot"])
        assert pd.api.types.is_integer_dtype(pendiente["suc"])
        assert pd.api.types.is_float_dtype(pendiente["importe"])

    def test_advierte_importe_invalido_y_cot_duplicada(self, advertencias_pendiente):
        texto = " | ".join(advertencias_pendiente)
        assert "importe inválido" in texto         # cot 86 con importe NaN
        assert "duplicado" in texto                 # cot 74 y 86 repetidas
        assert "74" in texto and "86" in texto

    def test_no_modifica_el_dataframe_de_entrada(self, raw_pendiente):
        cols, filas = list(raw_pendiente.columns), len(raw_pendiente)
        clean_pendiente(raw_pendiente)
        assert list(raw_pendiente.columns) == cols and len(raw_pendiente) == filas


class TestCleanFacturasMensual:
    def test_normaliza_encabezados_con_espacios(self, facturas_mensual):
        """' Cliente ' y ' Total ' deben quedar como columnas canónicas sin espacios."""
        assert list(facturas_mensual.columns) == COLUMNAS_MENSUAL

    def test_excluye_facturas_canceladas(self, facturas_mensual, advertencias_facturas_mensual):
        """El folio 102 ('venta CANCELADO refac') no debe estar en el resultado."""
        assert (facturas_mensual["folio"] == 102).sum() == 0
        assert any("cancelada" in a for a in advertencias_facturas_mensual)

    def test_normaliza_cliente_espacios_y_mayusculas(self, facturas_mensual):
        """'  toyoda  ' y 'Toyoda' → 'TOYODA' (strip + upper)."""
        assert "TOYODA" in set(facturas_mensual["cliente"])
        assert "  toyoda  " not in set(facturas_mensual["cliente"])

    def test_parsea_fecha_dd_mm_yyyy(self, facturas_mensual):
        """'25/12/2025' (texto que Excel no convirtió) → 2025-12-25."""
        fila = facturas_mensual[facturas_mensual["folio"] == 100].iloc[0]
        assert fila["fecha"] == pd.Timestamp(2025, 12, 25)

    def test_des_invierte_fecha_iso(self, facturas_mensual):
        """'2026-05-03 00:00:00' (Excel leyó dd/mm al revés) → 2026-03-05."""
        fila = facturas_mensual[facturas_mensual["folio"] == 101].iloc[0]
        assert fila["fecha"] == pd.Timestamp(2026, 3, 5)

    def test_limpia_monto_con_simbolos(self, facturas_mensual):
        """' $1,234.00 ' → 1234.0."""
        fila = facturas_mensual[facturas_mensual["folio"] == 100].iloc[0]
        assert fila["total"] == 1234.0

    def test_monto_nan_queda_nan_y_se_advierte(self, facturas_mensual, advertencias_facturas_mensual):
        fila = facturas_mensual[facturas_mensual["folio"] == 103].iloc[0]
        assert pd.isna(fila["total"])
        assert any("monto inválido" in a for a in advertencias_facturas_mensual)

    def test_conserva_folios_duplicados(self, facturas_mensual):
        """clean_facturas_mensual NO deduplica: el folio 100 repetido sigue 2 veces."""
        assert (facturas_mensual["folio"] == 100).sum() == 2

    def test_fecha_pago_vacia_es_nat(self, facturas_mensual):
        fila = facturas_mensual[facturas_mensual["folio"] == 101].iloc[0]
        assert pd.isna(fila["fecha_pago"])


class TestCleanTrabajos:
    def test_columnas_correctas(self, trabajos):
        assert list(trabajos.columns) == COLUMNAS_TRABAJOS

    def test_filtra_filas_parciales(self, trabajos):
        """Filas con solo cliente o solo tipo_trabajo se descartan: quedan 3 de 5."""
        assert len(trabajos) == 3
        assert "Cliente D parcial" not in set(trabajos["cliente"])
        assert "Solo tipo" not in set(trabajos["tipo_trabajo"])

    def test_mes_en_mayusculas(self, trabajos):
        assert set(trabajos["mes"]) == {"ENERO", "FEBRERO", "MARZO"}

    def test_normaliza_cliente_con_espacios(self, trabajos):
        """'  Toyoda  ' → 'Toyoda' (strip; clean_trabajos no aplica upper al cliente)."""
        assert "Toyoda" in set(trabajos["cliente"])

    def test_pagado_numerico_o_nan(self, trabajos):
        """'1500' → 1500.0 ; 'SI' y '' → NaN."""
        por_cliente = trabajos.set_index("cliente")["pagado"]
        assert por_cliente["Toyoda"] == 1500.0
        assert pd.isna(por_cliente["Cliente B"])   # venía "SI"
        assert pd.isna(por_cliente["Cliente C"])   # venía ""
