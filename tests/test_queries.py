"""
test_queries.py
---------------
Pruebas del motor de consultas (query_engine.py).

Valida:
  - Que cada comando devuelve una respuesta en texto.
  - Que las búsquedas por FACTURA, OC, COT y SUC funcionan.
  - Que los totales son numéricos y positivos.
  - Que comandos inválidos devuelven mensajes de error, no excepciones.
  - Que los resultados tienen el formato esperado.
"""

import pytest

from src.query_engine import run_query


class TestComandosGenerales:
    def test_comando_vacio_devuelve_mensaje(self, facturado, pendiente):
        resultado = run_query("", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_comando_desconocido_devuelve_mensaje(self, facturado, pendiente):
        resultado = run_query("xyz_inexistente", facturado, pendiente)
        assert "no reconocido" in resultado.lower() or "ayuda" in resultado.lower()

    def test_ayuda_devuelve_string(self, facturado, pendiente):
        resultado = run_query("ayuda", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 50

    def test_ayuda_contiene_comandos_principales(self, facturado, pendiente):
        resultado = run_query("ayuda", facturado, pendiente)
        for cmd in ("total", "buscar", "estado", "errores", "salir"):
            assert cmd in resultado.lower(), f"Comando '{cmd}' no aparece en la ayuda"


class TestTotal:
    def test_total_general_devuelve_string(self, facturado, pendiente):
        resultado = run_query("total", facturado, pendiente)
        assert isinstance(resultado, str)

    def test_total_general_contiene_monto_facturado(self, facturado, pendiente):
        resultado = run_query("total", facturado, pendiente)
        assert "Facturado" in resultado or "facturado" in resultado.lower()

    def test_total_general_contiene_monto_pendiente(self, facturado, pendiente):
        resultado = run_query("total", facturado, pendiente)
        assert "PTE" in resultado or "Pendiente" in resultado or "pendiente" in resultado.lower()

    def test_total_facturado_devuelve_monto(self, facturado, pendiente):
        resultado = run_query("total facturado", facturado, pendiente)
        assert "$" in resultado, "El resultado no contiene signo $"

    def test_total_pendiente_devuelve_monto(self, facturado, pendiente):
        resultado = run_query("total pendiente", facturado, pendiente)
        assert "$" in resultado, "El resultado no contiene signo $"

    def test_total_facturado_es_positivo(self, facturado, pendiente):
        resultado = run_query("total facturado", facturado, pendiente)
        monto_str = resultado.split("$")[-1].replace(",", "").strip()
        monto = float(monto_str)
        assert monto > 0, f"Total facturado no positivo: {monto}"

    def test_total_pendiente_es_positivo(self, facturado, pendiente):
        resultado = run_query("total pendiente", facturado, pendiente)
        monto_str = resultado.split("$")[-1].replace(",", "").strip()
        monto = float(monto_str)
        assert monto > 0, f"Total pendiente no positivo: {monto}"


class TestResumen:
    def test_resumen_devuelve_string(self, facturado, pendiente):
        resultado = run_query("resumen", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 50

    def test_resumen_contiene_conteos(self, facturado, pendiente):
        resultado = run_query("resumen", facturado, pendiente)
        assert "registros" in resultado.lower() or str(len(facturado)) in resultado


class TestListados:
    def test_facturas_devuelve_string(self, facturado, pendiente):
        resultado = run_query("facturas", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_facturas_contiene_fac(self, facturado, pendiente):
        resultado = run_query("facturas", facturado, pendiente)
        assert "Fac" in resultado or "factura" in resultado.lower()

    def test_facturas_contiene_total(self, facturado, pendiente):
        resultado = run_query("facturas", facturado, pendiente)
        assert "Total" in resultado or "$" in resultado

    def test_pendientes_devuelve_string(self, facturado, pendiente):
        resultado = run_query("pendientes", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_pendientes_contiene_cot(self, facturado, pendiente):
        resultado = run_query("pendientes", facturado, pendiente)
        assert "Cot" in resultado or "cot" in resultado.lower()

    def test_pendientes_sucursal_invalida(self, facturado, pendiente):
        resultado = run_query("pendientes abc", facturado, pendiente)
        assert "válido" in resultado or "no es" in resultado.lower()

    def test_pendientes_sucursal_inexistente(self, facturado, pendiente):
        resultado = run_query("pendientes 99999", facturado, pendiente)
        assert "no hay" in resultado.lower() or "no se encontró" in resultado.lower()


class TestBuscarFactura:
    def test_buscar_factura_valida(self, facturado, pendiente):
        primera = facturado["factura"].dropna().iloc[0]
        resultado = run_query(f"buscar factura {primera}", facturado, pendiente)
        assert str(primera) in resultado, f"La factura {primera} no aparece en el resultado"

    def test_buscar_factura_no_existente(self, facturado, pendiente):
        resultado = run_query("buscar factura 999999999", facturado, pendiente)
        assert "no se encontró" in resultado.lower()

    def test_buscar_factura_texto_invalido(self, facturado, pendiente):
        resultado = run_query("buscar factura abc", facturado, pendiente)
        assert "no es un número" in resultado.lower() or "válido" in resultado.lower()


class TestBuscarOC:
    def test_buscar_oc_parcial(self, facturado, pendiente):
        primera_oc = facturado["oc"].iloc[0]
        fragmento = primera_oc[:4] if len(primera_oc) >= 4 else primera_oc
        resultado = run_query(f"buscar oc {fragmento}", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_buscar_oc_no_existente(self, facturado, pendiente):
        resultado = run_query("buscar oc ZZZZZ_INEXISTENTE", facturado, pendiente)
        assert "no se encontró" in resultado.lower()

    def test_buscar_oc_devuelve_subtotal(self, facturado, pendiente):
        primera_oc = facturado["oc"].iloc[0]
        resultado = run_query(f"buscar oc {primera_oc}", facturado, pendiente)
        if "no se encontró" not in resultado.lower():
            assert "Subtotal" in resultado or "$" in resultado


class TestBuscarCot:
    def test_buscar_cot_valida(self, facturado, pendiente):
        primera = pendiente["cot"].dropna().iloc[0]
        resultado = run_query(f"buscar cot {primera}", facturado, pendiente)
        assert str(primera) in resultado, f"La cotización {primera} no aparece en el resultado"

    def test_buscar_cot_no_existente(self, facturado, pendiente):
        resultado = run_query("buscar cot 999999999", facturado, pendiente)
        assert "no se encontró" in resultado.lower()

    def test_buscar_cot_texto_invalido(self, facturado, pendiente):
        resultado = run_query("buscar cot abc", facturado, pendiente)
        assert "no es un número" in resultado.lower() or "válido" in resultado.lower()


class TestBuscarSuc:
    def test_buscar_suc_valida(self, facturado, pendiente):
        primera = pendiente["suc"].dropna().iloc[0]
        resultado = run_query(f"buscar suc {primera}", facturado, pendiente)
        assert str(primera) in resultado or "$" in resultado

    def test_buscar_suc_no_existente(self, facturado, pendiente):
        resultado = run_query("buscar suc 99999", facturado, pendiente)
        assert "no hay" in resultado.lower() or "no se encontró" in resultado.lower()

    def test_buscar_suc_texto_invalido(self, facturado, pendiente):
        resultado = run_query("buscar suc abc", facturado, pendiente)
        assert "no es un número" in resultado.lower() or "válido" in resultado.lower()


class TestEstado:
    def test_estado_aceptada(self, facturado, pendiente):
        resultado = run_query("estado aceptada", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_estado_prioridad(self, facturado, pendiente):
        resultado = run_query("estado prioridad", facturado, pendiente)
        assert isinstance(resultado, str) and len(resultado) > 0

    def test_estado_inexistente(self, facturado, pendiente):
        resultado = run_query("estado ZZZINEXISTENTE", facturado, pendiente)
        assert "no se encontraron" in resultado.lower()
