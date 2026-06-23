"""El webhook rutea el trigger de cotización y persiste al confirmar."""
import pytest

from src import webhook


def test_es_cotizar_reconoce_triggers():
    assert webhook._es_cotizar("nueva cotizacion") is True
    assert webhook._es_cotizar("cotizar") is True
    assert webhook._es_cotizar("nueva cotización") is True
    assert webhook._es_cotizar("agregar trabajo") is False


@pytest.mark.asyncio
async def test_procesar_mensaje_inicia_cotizacion(monkeypatch):
    monkeypatch.setattr(webhook, "tiene_sesion", lambda n: False)
    llamado = {}

    def _fake_iniciar(n):
        llamado["ok"] = n
        return "Nueva cotización."

    monkeypatch.setattr(webhook, "iniciar_cotizacion", _fake_iniciar)
    resp = await webhook._procesar_mensaje("521", "cotizar")
    assert llamado.get("ok") == "521" and "cotización" in resp.lower()


@pytest.mark.asyncio
async def test_confirmar_persiste_con_guardar_cotizacion(monkeypatch):
    monkeypatch.setattr(webhook, "tiene_sesion", lambda n: True)
    datos = {"tipo": "cotizacion", "nombre": "WALDOS"}
    monkeypatch.setattr(webhook, "procesar", lambda n, t: ("Guardando...", datos))
    monkeypatch.setattr(webhook, "guardar_cotizacion",
                        lambda d: "Cotizacion #1 registrada para WALDOS. Total $1,080.00.")
    monkeypatch.setattr(webhook, "registrar", lambda *a, **k: None)
    resp = await webhook._procesar_mensaje("521", "si")
    assert resp.startswith("Cotizacion #1")
