"""
test_sesiones_workers.py
------------------------
Regresión del bug reportado (vía Meta): durante el flujo de REGISTRO, al pedir el
teléfono el usuario escribió "sin" y el bot lo interpretó como COMANDO (devolvió
facturas "sin pago") en vez de tomarlo como campo vacío. Se perdió el flujo.

Causa raíz: el estado de sesión vivía en un dict en memoria por worker. Con
`uvicorn --workers 2`, el siguiente mensaje caía en OTRO worker que no veía la
sesión (`tiene_sesion()` → False), y `_procesar_mensaje` re-enrutaba "sin" a un
comando de consulta.

Fix: en modo Postgres (USE_POSTGRES_SESSIONS=1) las sesiones se leen/escriben por
número en el store compartido EN VIVO, así cualquier worker ve el mismo estado.

El store de Postgres se simula con un dict compartido (la "BD" única que ven todos
los workers). "Otro worker" = vaciar el espejo en memoria `_sesiones`.
"""

import pytest


@pytest.fixture
def pg(monkeypatch):
    import src.sesiones as ses
    import src.sesiones_pg as spg

    store: dict = {}
    monkeypatch.setattr(ses, "_USE_POSTGRES", True)
    monkeypatch.setattr(spg, "cargar_todas", lambda: dict(store))
    monkeypatch.setattr(spg, "cargar_una", lambda n: store.get(n))
    monkeypatch.setattr(spg, "guardar_una", lambda n, e: store.__setitem__(n, e))
    monkeypatch.setattr(spg, "borrar", lambda n: store.pop(n, None))
    return ses, store


def _avanzar_hasta_telefono(ses, numero):
    """Lleva el flujo de registro hasta justo antes del paso 'telefono'."""
    ses.iniciar(numero)
    ses.procesar(numero, "MAYO")        # mes
    ses.procesar(numero, "Juan Perez")  # tecnico
    ses.procesar(numero, "ACME SA")     # cliente
    pregunta = ses.procesar(numero, "Calle 1 #2")[0]   # domicilio → pide telefono
    assert "Telefono" in pregunta       # confirma que el siguiente campo es teléfono


def test_sin_en_paso_telefono_es_campo_vacio_no_comando(pg):
    """Caso literal del bug: 'sin' esperando teléfono = vacío, no comando."""
    ses, store = pg
    numero = "5218681707554"
    _avanzar_hasta_telefono(ses, numero)

    resp, datos = ses.procesar(numero, "sin")

    assert datos is None                              # el flujo CONTINÚA (no comando)
    assert store[numero]["datos"]["telefono"] == ""   # 'sin' → teléfono vacío
    assert "Tipo de trabajo" in resp                  # avanzó al siguiente campo


def test_sesion_sobrevive_entre_workers(pg, monkeypatch):
    """El núcleo del bug: el siguiente mensaje cae en OTRO worker (memoria vacía)
    y aún así la sesión se recupera del store compartido."""
    ses, store = pg
    numero = "5218681707554"
    _avanzar_hasta_telefono(ses, numero)

    # Simula que el mensaje "sin" llega a un worker DISTINTO: su _sesiones en
    # memoria está vacío (se cargó en su propio arranque, sin esta sesión).
    monkeypatch.setattr(ses, "_sesiones", {})

    assert ses.tiene_sesion(numero) is True   # lee del store compartido, no de memoria

    resp, datos = ses.procesar(numero, "sin")
    assert datos is None
    assert store[numero]["datos"]["telefono"] == ""
    assert "Tipo de trabajo" in resp


def test_flujo_completo_entre_workers_distintos(pg, monkeypatch):
    """Cada mensaje cae en un worker 'fresco'; el registro debe completarse igual."""
    ses, store = pg
    numero = "5218681707554"

    pasos = ["MAYO", "Juan Perez", "ACME SA", "Calle 1 #2", "sin",
             "Mantenimiento", "1500", "Ing. Lopez"]
    ses.iniciar(numero)
    for entrada in pasos:
        monkeypatch.setattr(ses, "_sesiones", {})   # worker nuevo en cada turno
        assert ses.tiene_sesion(numero) is True
        _, datos = ses.procesar(numero, entrada)
        assert datos is None                        # aún en flujo (falta confirmar)

    # Paso final: confirmar. Otro worker más.
    monkeypatch.setattr(ses, "_sesiones", {})
    msg, datos = ses.procesar(numero, "si")
    assert datos is not None                        # registro listo para guardar
    assert datos["telefono"] == ""                  # el 'sin' del paso 5 persistió
    assert datos["mes"] == "MAYO"
    assert datos["pagado"] == "1500"
    assert ses.tiene_sesion(numero) is False        # sesión borrada del store


def test_modo_archivo_sigue_funcionando(monkeypatch, tmp_path):
    """Sin Postgres, el flujo en memoria/archivo sigue intacto (1 worker)."""
    import src.sesiones as ses
    monkeypatch.setattr(ses, "_USE_POSTGRES", False)
    monkeypatch.setattr(ses, "_SESIONES_PATH", tmp_path / "sesiones.json")
    monkeypatch.setattr(ses, "_sesiones", {})
    monkeypatch.delenv("DRIVE_FOLDER_ID", raising=False)

    numero = "whatsapp:+5218681707554"
    ses.iniciar(numero)
    assert ses.tiene_sesion(numero) is True
    ses.procesar(numero, "MAYO")
    resp, datos = ses.procesar(numero, "Juan Perez")
    assert datos is None
    assert "Nombre del cliente" in resp
