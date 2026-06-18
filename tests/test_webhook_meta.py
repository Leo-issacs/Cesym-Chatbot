"""
test_webhook_meta.py
--------------------
Soporte de Meta Cloud API AÑADIDO sin romper Twilio. Cubre:
  (a) GET /webhook con token correcto devuelve el hub.challenge (y 403 si no).
  (b) POST con payload de Meta llama a la MISMA lógica de negocio y responde
      por la Graph API.
  (c) POST con payload de Twilio (form-urlencoded) sigue funcionando (TwiML).
  (d) La app arranca/opera sin las variables META_* definidas.
  (+) Status updates de Meta (sin 'messages') se ack-ean con 200 sin procesar.

Se usa TestClient SIN context manager para no disparar el lifespan (Drive/datos):
solo se ejercita el routing del webhook. La lógica de negocio y el envío real a
Meta se mockean (suite hermética: sin red ni secretos, igual que el resto del CI).
"""

import asyncio

from fastapi.testclient import TestClient

import src.webhook as webhook


def _payload_meta(texto="hola", numero="5218681707554", tipo="text"):
    """Construye un webhook de Meta con la estructura real (entry→changes→value)."""
    mensaje = {
        "from": numero,
        "id": "wamid.HBgABC",
        "timestamp": "1700000000",
        "type": tipo,
    }
    if tipo == "text":
        mensaje["text"] = {"body": texto}
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15550001111",
                                 "phone_number_id": "PHONE_ID"},
                    "contacts": [{"profile": {"name": "Leo"}, "wa_id": numero}],
                    "messages": [mensaje],
                },
            }],
        }],
    }


# ─── (a) Verificación GET del webhook de Meta ────────────────────────────────

def test_get_webhook_devuelve_challenge_con_token_correcto(monkeypatch):
    monkeypatch.setenv("META_VERIFY_TOKEN", "secreto123")
    client = TestClient(webhook.app)
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "secreto123",   # guion bajo (no "hub.verify.token")
        "hub.challenge": "1158201444",
    })
    assert r.status_code == 200
    assert r.text == "1158201444"   # devuelve el challenge tal cual


def test_get_webhook_token_incorrecto_devuelve_403(monkeypatch):
    monkeypatch.setenv("META_VERIFY_TOKEN", "secreto123")
    client = TestClient(webhook.app)
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "equivocado",
        "hub.challenge": "x",
    })
    assert r.status_code == 403


# ─── (b) POST de Meta → misma lógica de negocio + envío por Graph API ────────

def test_post_meta_llama_logica_y_envia_respuesta(monkeypatch):
    capturado = {}

    async def fake_procesar(numero, entrada):
        capturado["procesar"] = (numero, entrada)
        return "respuesta-del-bot"

    async def fake_enviar(numero, texto):
        capturado["enviar"] = (numero, texto)
        return True

    monkeypatch.setattr(webhook, "_procesar_mensaje", fake_procesar)
    monkeypatch.setattr(webhook, "enviar_mensaje_meta", fake_enviar)

    client = TestClient(webhook.app)
    r = client.post("/webhook", json=_payload_meta(texto="hola", numero="5218681707554"))

    assert r.status_code == 200
    # Extrae numero y texto del payload Meta y los pasa a la lógica existente.
    assert capturado["procesar"] == ("5218681707554", "hola")
    # Responde por la Graph API con el texto que produjo la lógica de negocio.
    assert capturado["enviar"] == ("5218681707554", "respuesta-del-bot")


def test_post_meta_status_update_no_procesa(monkeypatch):
    """Eventos sin 'messages' (sent/delivered/read) → 200 sin tocar la lógica."""
    llamado = {"v": False}

    async def fake_procesar(numero, entrada):
        llamado["v"] = True
        return "x"

    monkeypatch.setattr(webhook, "_procesar_mensaje", fake_procesar)
    payload = {"object": "whatsapp_business_account",
               "entry": [{"changes": [{"value": {
                   "messaging_product": "whatsapp",
                   "statuses": [{"id": "wamid.X", "status": "delivered"}],
               }}]}]}

    client = TestClient(webhook.app)
    r = client.post("/webhook", json=payload)
    assert r.status_code == 200
    assert llamado["v"] is False


# ─── (c) POST de Twilio: comportamiento intacto ──────────────────────────────

def test_post_twilio_sigue_funcionando(monkeypatch):
    monkeypatch.delenv("ENFORCE_TWILIO_SIGNATURE", raising=False)
    monkeypatch.delenv("ENFORCE_WHITELIST", raising=False)

    async def fake_procesar(numero, entrada):
        return f"eco:{entrada}"

    monkeypatch.setattr(webhook, "_procesar_mensaje", fake_procesar)

    client = TestClient(webhook.app)
    r = client.post("/webhook",
                    data={"Body": "total", "From": "whatsapp:+5218681707554"})

    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]   # TwiML
    assert "<Response>" in r.text
    assert "eco:total" in r.text


# ─── (d) La app no requiere META_* para arrancar / operar ────────────────────

def test_verificacion_sin_token_configurado_no_crashea(monkeypatch):
    for v in ("META_VERIFY_TOKEN", "META_ACCESS_TOKEN",
              "META_PHONE_NUMBER_ID", "META_GRAPH_VERSION"):
        monkeypatch.delenv(v, raising=False)
    client = TestClient(webhook.app)
    r = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "y",
    })
    assert r.status_code == 403   # sin token configurado: rechaza, no crashea


def test_enviar_meta_sin_credenciales_retorna_false(monkeypatch):
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_PHONE_NUMBER_ID", raising=False)
    ok = asyncio.run(webhook.enviar_mensaje_meta("5218681707554", "hola"))
    assert ok is False   # loguea y no lanza


# ─── Normalización del número mexicano (error 131030) ────────────────────────

def test_normaliza_numero_mexicano():
    # 521 + 10 dígitos (13) → 52 + 10 dígitos (quita el "1")
    assert webhook._normalizar_numero_meta("5218681707554") == "528681707554"


def test_no_altera_numeros_de_otros_paises_ni_mx_ya_normalizado():
    assert webhook._normalizar_numero_meta("14155238886") == "14155238886"   # USA (+1)
    assert webhook._normalizar_numero_meta("34911234567") == "34911234567"   # España (+34)
    assert webhook._normalizar_numero_meta("528681707554") == "528681707554"  # MX ya correcto
    # "521…" pero longitud distinta a 13 → no se toca (no es el patrón MX móvil)
    assert webhook._normalizar_numero_meta("52186817075") == "52186817075"


def test_enviar_meta_usa_numero_normalizado_en_payload(monkeypatch):
    """El destinatario que llega a la Graph API debe ir ya normalizado."""
    monkeypatch.setenv("META_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "PID")
    capturado = {}

    class _FakeResp:
        status_code = 200
        text = ""

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            capturado["to"] = json["to"]
            return _FakeResp()

    monkeypatch.setattr(webhook.httpx, "AsyncClient", _FakeClient)

    ok = asyncio.run(webhook.enviar_mensaje_meta("5218681707554", "hola"))
    assert ok is True
    assert capturado["to"] == "528681707554"   # sin el "1" extra
