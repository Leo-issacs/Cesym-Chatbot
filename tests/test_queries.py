"""
test_queries.py
---------------
Pruebas del motor de consultas (query_engine.py) contra datos SINTÉTICOS.
Validan comportamiento (tipo de respuesta, ramas de error, contenido esperado),
no conteos del Excel real. La precisión textual exacta se cubre en
test_golden_master.py.

Se usa el fixture `rq` (conftest): rq("total") ejecuta run_query con los cuatro
DataFrames sintéticos.
"""

import pytest

from src.query_engine import run_query


class TestComandosGenerales:
    def test_comando_vacio_devuelve_mensaje(self, rq):
        resultado = rq("")
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_comando_desconocido_devuelve_mensaje(self, rq):
        resultado = rq("xyz_inexistente")
        assert "no reconocido" in resultado.lower() or "ayuda" in resultado.lower()

    def test_ayuda_devuelve_string(self, rq):
        assert len(rq("ayuda")) > 50

    def test_ayuda_contiene_comandos_principales(self, rq):
        resultado = rq("ayuda").lower()
        for cmd in ("total", "buscar", "estado", "errores"):
            assert cmd in resultado, f"Comando '{cmd}' no aparece en la ayuda"


class TestTotal:
    def test_total_general_menciona_facturado_y_pendiente(self, rq):
        resultado = rq("total")
        assert "facturado" in resultado.lower()
        assert "pte" in resultado.lower() or "pendiente" in resultado.lower()

    def test_total_facturado_es_positivo(self, rq):
        resultado = rq("total facturado")
        monto = float(resultado.split("$")[-1].replace(",", "").strip())
        assert monto > 0

    def test_total_pendiente_es_positivo(self, rq):
        resultado = rq("total pendiente")
        monto = float(resultado.split("$")[-1].replace(",", "").strip())
        assert monto > 0

    def test_total_trabajos_devuelve_string(self, rq):
        assert "$" in rq("total trabajos")

    def test_total_mensual_devuelve_string(self, rq):
        assert isinstance(rq("total mensual"), str)


class TestResumen:
    def test_resumen_devuelve_bloque(self, rq):
        assert len(rq("resumen")) > 50

    def test_resumen_contiene_conteos(self, rq, facturado):
        resultado = rq("resumen")
        assert "registros" in resultado.lower() or str(len(facturado)) in resultado


class TestListados:
    def test_facturas_contiene_fac_y_total(self, rq):
        resultado = rq("facturas")
        assert "Fac" in resultado
        assert "Total" in resultado or "$" in resultado

    def test_pendientes_contiene_cot(self, rq):
        assert "cot" in rq("pendientes").lower()

    def test_pendientes_sucursal_existente(self, rq):
        """suc 2 existe en el sintético (cot 75)."""
        resultado = rq("pendientes 2")
        assert "Cot" in resultado

    def test_pendientes_sucursal_invalida(self, rq):
        resultado = rq("pendientes abc").lower()
        assert "válido" in resultado or "no es" in resultado

    def test_pendientes_sucursal_inexistente(self, rq):
        resultado = rq("pendientes 99999").lower()
        assert "no hay" in resultado or "no se encontró" in resultado


class TestBuscarFactura:
    def test_buscar_factura_valida(self, rq):
        resultado = rq("buscar factura 8001")
        assert "8001" in resultado

    def test_buscar_factura_no_existente(self, rq):
        assert "no se encontró" in rq("buscar factura 999999999").lower()

    def test_buscar_factura_texto_invalido(self, rq):
        resultado = rq("buscar factura abc").lower()
        assert "no es un número" in resultado or "válido" in resultado


class TestBuscarOC:
    def test_buscar_oc_parcial(self, rq):
        """'O01-' es prefijo común de las OC sintéticas."""
        resultado = rq("buscar oc O01-")
        assert "Subtotal" in resultado or "$" in resultado

    def test_buscar_oc_no_existente(self, rq):
        assert "no se encontró" in rq("buscar oc ZZZZZ_INEXISTENTE").lower()


class TestBuscarCot:
    def test_buscar_cot_valida(self, rq):
        assert "74" in rq("buscar cot 74")

    def test_buscar_cot_no_existente(self, rq):
        assert "no se encontró" in rq("buscar cot 999999999").lower()

    def test_buscar_cot_texto_invalido(self, rq):
        resultado = rq("buscar cot abc").lower()
        assert "no es un número" in resultado or "válido" in resultado


class TestBuscarSuc:
    def test_buscar_suc_valida(self, rq):
        resultado = rq("buscar suc 1")
        assert "$" in resultado or "Cot" in resultado

    def test_buscar_suc_no_existente(self, rq):
        assert "no hay" in rq("buscar suc 99999").lower()

    def test_buscar_suc_texto_invalido(self, rq):
        resultado = rq("buscar suc abc").lower()
        assert "no es un número" in resultado or "válido" in resultado


class TestBuscarCliente:
    def test_buscar_cliente_existente(self, rq):
        """'TOYODA' está en reporte mensual y en trabajos."""
        resultado = rq("buscar cliente TOYODA")
        assert "TOYODA" in resultado

    def test_buscar_cliente_con_typo_usa_fuzzy(self, rq):
        """'TOYODAA' (typo) debe resolverse a TOYODA vía fallback difflib."""
        resultado = rq("buscar cliente TOYODAA")
        assert "TOYODA" in resultado

    def test_buscar_cliente_inexistente(self, rq):
        assert "no se encontró" in rq("buscar cliente ZZNOEXISTE").lower()


class TestEstado:
    def test_estado_aceptada(self, rq):
        assert len(rq("estado aceptada")) > 0

    def test_estado_prioridad(self, rq):
        """8002 tiene prioridad PRIORIDAD en el sintético."""
        assert "8002" in rq("estado prioridad")

    def test_estado_inexistente(self, rq):
        assert "no se encontraron" in rq("estado ZZZINEXISTENTE").lower()


class TestCobradasYCruce:
    def test_cobradas_devuelve_string(self, rq):
        assert isinstance(rq("cobradas"), str)

    def test_sin_cobrar_devuelve_string(self, rq):
        assert isinstance(rq("sin cobrar"), str)

    def test_cruce_devuelve_string(self, rq):
        assert isinstance(rq("cruce"), str)

    def test_trabajos_lista(self, rq):
        assert isinstance(rq("trabajos"), str)
