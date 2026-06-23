"""Validaciones puras del flujo de cotización (sin BD)."""
from src import sesiones as ses


def test_normalizar_iva():
    assert ses._normalizar_iva("") == 0.08
    assert ses._normalizar_iva("8") == 0.08
    assert ses._normalizar_iva("8%") == 0.08
    assert ses._normalizar_iva("frontera") == 0.08
    assert ses._normalizar_iva("16") == 0.16
    assert ses._normalizar_iva("16%") == 0.16
    assert ses._normalizar_iva("10") is None
    assert ses._normalizar_iva("basura") is None


def test_parse_importe():
    assert ses._parse_importe("1500") == 1500.0
    assert ses._parse_importe("$1,500.50") == 1500.50
    assert ses._parse_importe("0") is None
    assert ses._parse_importe("-5") is None
    assert ses._parse_importe("abc") is None


def test_rfc_valido():
    assert ses._rfc_valido("WDM990126350") is True       # 12 (moral)
    assert ses._rfc_valido("OOGL800309HG1") is True       # 13 (física)
    assert ses._rfc_valido("corto") is False
    assert ses._rfc_valido("CON ESPACIOS!!") is False
