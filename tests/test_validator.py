"""
test_validator.py
-----------------
Pruebas de detección de inconsistencias (comando 'errores' y advertencias de los
cleaners) contra datos SINTÉTICOS con problemas conocidos a propósito:
  - factura 8004 con monto NaN, 8005 sin fecha, 8003 sin OC;
  - factura 8002 duplicada (y por tanto OC O01-101 repetida);
  - cotización 86 con importe NaN; cotizaciones 74 y 86 duplicadas.

Los asserts validan que esas inconsistencias se detectan y se reportan.
"""

import pandas as pd
import pytest

from src.query_engine import run_query


class TestComandoErrores:
    def test_devuelve_string(self, rq):
        assert isinstance(rq("errores"), str)

    def test_reporta_inconsistencias_de_facturado(self, rq):
        resultado = rq("errores").lower()
        assert "monto inválido" in resultado     # factura 8004 (monto NaN)
        assert "sin fecha" in resultado            # factura 8005
        assert "sin oc" in resultado               # factura 8003

    def test_reporta_factura_y_oc_duplicadas(self, rq):
        resultado = rq("errores")
        assert "8002" in resultado                 # factura duplicada
        assert "duplicad" in resultado.lower()
        assert "O01-101" in resultado              # OC repetida

    def test_reporta_cotizaciones_duplicadas(self, rq):
        resultado = rq("errores")
        assert "74" in resultado and "86" in resultado

    def test_no_lanza_con_facturado_vacio(self, pendiente, facturas_mensual, trabajos):
        """Con facturado vacío no debe romper (pendiente sí tiene duplicados)."""
        df_vacio = pd.DataFrame(
            columns=["factura", "oc", "monto_actual", "prioridad", "fecha", "estado"]
        )
        resultado = run_query("errores", df_vacio, pendiente, facturas_mensual, trabajos)
        assert isinstance(resultado, str)


class TestAdvertenciasFacturado:
    def test_advierte_monto_invalido(self, advertencias_facturado):
        assert any("monto" in w.lower() for w in advertencias_facturado)

    def test_advierte_sin_fecha(self, advertencias_facturado):
        assert any("fecha" in w.lower() for w in advertencias_facturado)

    def test_advierte_sin_oc(self, advertencias_facturado):
        assert any("oc" in w.lower() for w in advertencias_facturado)

    def test_advertencias_son_lista(self, advertencias_facturado):
        assert isinstance(advertencias_facturado, list)


class TestAdvertenciasPendiente:
    def test_advierte_importe_invalido(self, advertencias_pendiente):
        assert any("importe" in w.lower() for w in advertencias_pendiente)

    def test_advierte_cot_duplicada(self, advertencias_pendiente):
        texto = " | ".join(advertencias_pendiente)
        assert "duplicado" in texto and "74" in texto and "86" in texto


class TestDeteccionDirectaEnDataframe:
    """Condiciones verificadas directo sobre el DataFrame limpio sintético."""

    def test_factura_8002_duplicada(self, facturado):
        duplicadas = facturado[facturado.duplicated("factura", keep=False)]
        assert set(duplicadas["factura"]) == {8002}

    def test_oc_repetida(self, facturado):
        ocs_validas = facturado[~facturado["oc"].isin(["nan", "", "NaN"])]
        duplicadas = ocs_validas[ocs_validas.duplicated("oc", keep=False)]
        assert "O01-101" in set(duplicadas["oc"])

    def test_cot_duplicada(self, pendiente):
        duplicadas = pendiente[pendiente.duplicated("cot", keep=False)]
        assert set(duplicadas["cot"]) == {74, 86}
