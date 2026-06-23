"""Flujo de cotización end-to-end, hermético: catálogo cesym_db monkeypatcheado
con datos en memoria; sesiones en modo memoria (USE_POSTGRES=False)."""
import pytest

from src import sesiones as ses


@pytest.fixture
def flujo(monkeypatch):
    monkeypatch.setattr(ses, "_USE_POSTGRES", False)
    monkeypatch.setattr(ses, "_sesiones", {})
    monkeypatch.delenv("DRIVE_FOLDER_ID", raising=False)
    catalogo = {
        "clientes": [
            {"rfc": "WDM990126350", "nombre_fiscal": "WALDOS DOLAR MART",
             "nombre_comercial": "WALDOS"},
        ],
        "sucursales": {"WDM990126350": [{"id": 7, "suc": "5208", "nombre": "CENTRO"}]},
    }
    import src.cesym_db as cdb

    def _buscar(texto, engine=None):
        t = texto.lower()
        return [c for c in catalogo["clientes"]
                if t in c["nombre_comercial"].lower() or t == c["rfc"].lower()]

    monkeypatch.setattr(cdb, "buscar_clientes", _buscar)
    monkeypatch.setattr(cdb, "listar_sucursales",
                        lambda rfc, engine=None: catalogo["sucursales"].get(rfc, []))
    return ses


def test_cliente_existente_sucursal_existente(flujo):
    n = "521111"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos")               # cliente_buscar → 1 match
    flujo.procesar(n, "si")                    # confirma cliente
    flujo.procesar(n, "5208")                  # sucursal existente
    flujo.procesar(n, "Mantenimiento aire")    # descripcion
    flujo.procesar(n, "1500")                  # importe
    flujo.procesar(n, "")                       # iva default 8%
    msg, datos = flujo.procesar(n, "si")        # confirmar
    assert datos["tipo"] == "cotizacion"
    assert datos["cliente_rfc"] == "WDM990126350"
    assert datos["cliente_nuevo"] is False
    assert datos["sucursal_id"] == 7 and datos["sucursal_nueva"] is False
    assert datos["descripcion"] == "Mantenimiento aire"
    assert datos["importe"] == 1500.0 and datos["iva_tasa"] == 0.08


def test_cliente_nuevo_con_rfc(flujo):
    n = "521222"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "ferreteria lopez")      # 0 matches → crear
    flujo.procesar(n, "FLO9901011AA")          # RFC nuevo (12)
    flujo.procesar(n, "FERRETERIA LOPEZ SA")   # nombre fiscal
    flujo.procesar(n, "sin")                    # sucursal omitida
    flujo.procesar(n, "Instalacion")           # descripcion
    flujo.procesar(n, "2000")                  # importe
    flujo.procesar(n, "16")                     # iva 16 → pasa a confirmar
    msg, datos = flujo.procesar(n, "si")
    assert datos["cliente_nuevo"] is True
    assert datos["cliente_rfc"] == "FLO9901011AA"
    assert datos["nombre_fiscal"] == "FERRETERIA LOPEZ SA"
    assert datos["sucursal_id"] is None and datos["sucursal_nueva"] is False
    assert datos["iva_tasa"] == 0.16


def test_importe_invalido_repregunta(flujo):
    n = "521333"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos"); flujo.procesar(n, "si")
    flujo.procesar(n, "sin")                    # sucursal
    flujo.procesar(n, "Servicio")              # descripcion
    msg, datos = flujo.procesar(n, "abc")       # importe inválido
    assert datos is None and "importe" in msg.lower()


def test_sucursal_nueva_al_vuelo(flujo):
    n = "521444"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos"); flujo.procesar(n, "si")
    flujo.procesar(n, "9999")                  # sucursal inexistente
    flujo.procesar(n, "PLAZA NORTE")           # nombre de la nueva sucursal
    flujo.procesar(n, "Servicio")              # descripcion
    flujo.procesar(n, "300")                   # importe
    flujo.procesar(n, "8")                      # iva 8 → confirmar
    msg, datos = flujo.procesar(n, "si")
    assert datos["sucursal_nueva"] is True
    assert datos["suc"] == "9999" and datos["sucursal_nombre"] == "PLAZA NORTE"


def test_varios_matches_elegir(flujo, monkeypatch):
    import src.cesym_db as cdb
    monkeypatch.setattr(cdb, "buscar_clientes", lambda t, engine=None: [
        {"rfc": "AAA010101AA1", "nombre_fiscal": "A UNO", "nombre_comercial": "ACME UNO"},
        {"rfc": "BBB020202BB2", "nombre_fiscal": "A DOS", "nombre_comercial": "ACME DOS"},
    ])
    n = "521555"
    flujo.iniciar_cotizacion(n)
    msg, _ = flujo.procesar(n, "acme")          # varios → lista
    assert "1." in msg and "2." in msg
    flujo.procesar(n, "2")                       # elige el segundo
    flujo.procesar(n, "sin")
    flujo.procesar(n, "Servicio")
    flujo.procesar(n, "100")
    flujo.procesar(n, "8")
    _, datos = flujo.procesar(n, "si")
    assert datos["cliente_rfc"] == "BBB020202BB2"


def test_cancelar_aborta(flujo):
    n = "521666"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos")
    msg, datos = flujo.procesar(n, "cancelar")
    assert datos is None and flujo.tiene_sesion(n) is False
