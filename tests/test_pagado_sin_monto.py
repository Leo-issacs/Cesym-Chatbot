"""
test_pagado_sin_monto.py
------------------------
En "agregar trabajo", el paso "monto cobrado" acepta "pagado" (y variantes)
para los reportes que solo indican que ya se pagó, sin el importe. Se guarda el
marcador "PAGADO" (texto en Excel; NULL en Postgres por ser columna numérica) y
se muestra como "Pagado (sin monto)".
"""

import src.sesiones as ses
from src.escritor import pago_a_numero, formato_monto_pagado


# ─── Normalización de la respuesta al monto ──────────────────────────────────

def test_normalizar_pagado_marcador():
    assert ses._normalizar_pagado("pagado") == "PAGADO"
    assert ses._normalizar_pagado("Ya pagado") == "PAGADO"
    assert ses._normalizar_pagado("ya quedó pagado") == "PAGADO"


def test_normalizar_pagado_sin_cobrar():
    for v in ("sin cobrar", "sin", "no", "0", ""):
        assert ses._normalizar_pagado(v) == ""


def test_normalizar_pagado_numero():
    assert ses._normalizar_pagado("1500") == "1500"
    assert ses._normalizar_pagado("$1,500") == "1500"


# ─── Conversión y visualización ──────────────────────────────────────────────

def test_pago_a_numero():
    assert pago_a_numero("PAGADO") is None   # marcador → sin monto numérico (NULL)
    assert pago_a_numero("1500") == 1500.0
    assert pago_a_numero("") is None
    assert pago_a_numero(None) is None
    assert pago_a_numero(1500.0) == 1500.0


def test_formato_monto_pagado():
    assert formato_monto_pagado("PAGADO") == "Pagado (sin monto)"
    assert formato_monto_pagado("1500") == "$1,500.00"
    assert formato_monto_pagado(1500.0) == "$1,500.00"
    assert formato_monto_pagado("") == "sin cobrar"
    assert formato_monto_pagado(None) == "sin cobrar"


# ─── Flujo completo de "agregar trabajo" respondiendo "pagado" ───────────────

def test_flujo_agregar_con_pagado(monkeypatch, tmp_path):
    monkeypatch.setattr(ses, "_USE_POSTGRES", False)
    monkeypatch.setattr(ses, "_SESIONES_PATH", tmp_path / "sesiones.json")
    monkeypatch.setattr(ses, "_sesiones", {})
    monkeypatch.delenv("DRIVE_FOLDER_ID", raising=False)

    numero = "whatsapp:+5210000000000"
    ses.iniciar(numero)
    for entrada in ["MAYO", "Juan", "ACME", "Calle 1", "5551234", "Mantenimiento"]:
        ses.procesar(numero, entrada)

    # Paso "monto cobrado": el usuario escribe "pagado" (sin importe).
    _, datos = ses.procesar(numero, "pagado")
    assert datos is None   # aún falta 'recibe', no debe romper

    # Paso "recibe" → mensaje de confirmación.
    msg, datos = ses.procesar(numero, "Ing Lopez")
    assert datos is None
    assert "Pagado (sin monto)" in msg   # así se visualiza en la confirmación

    # Confirmar → datos completos con el marcador.
    _, datos = ses.procesar(numero, "si")
    assert datos is not None
    assert datos["pagado"] == "PAGADO"
