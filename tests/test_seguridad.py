"""
test_seguridad.py
-----------------
Pruebas de la seguridad del webhook (src/seguridad.py):
  - Reconstrucción de la URL pública detrás del proxy de Railway (X-Forwarded-*).
  - Validación de firma Twilio: acepta la firma legítima y rechaza la falsa.
  - Whitelist de números autorizados.
  - Modo log-only vs enforcement (no bloquea / bloquea 403).

El escenario central reproduce el caso real de producción: Twilio firma la URL
PÚBLICA (https), pero detrás del proxy FastAPI ve una URL interna (http). Si la
reconstrucción falla, la firma de un mensaje legítimo no validaría.
"""

import os

import pytest
from twilio.request_validator import RequestValidator

import src.seguridad as seg


AUTH_TOKEN = "test_auth_token_para_pruebas"
DOMINIO_PUBLICO = "cesym-bot.up.railway.app"
URL_PUBLICA = f"https://{DOMINIO_PUBLICO}/webhook"

PARAMS = {
    "Body": "hola",
    "From": "whatsapp:+5219999999999",
    "To": "whatsapp:+14155238886",
}


# ─── Dobles de prueba que imitan el Request de FastAPI ──────────────────────────

class _FakeURL:
    """Imita request.url: lo que ve FastAPI DETRÁS del proxy (interno, http)."""
    scheme = "http"
    hostname = "internal.railway.internal"
    path = "/webhook"
    query = ""


class _FakeRequest:
    """Imita un Request con headers de proxy y la firma de Twilio."""
    def __init__(self, headers: dict):
        self.url = _FakeURL()
        self.headers = headers


def _headers_proxy(firma: str) -> dict:
    """Headers como los pone el proxy de Railway para una petición HTTPS pública."""
    return {
        "x-forwarded-proto": "https",
        "x-forwarded-host": DOMINIO_PUBLICO,
        "host": "internal.railway.internal",
        "x-twilio-signature": firma,
    }


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    """Cada test arranca con el token puesto y los flags/whitelist en estado conocido."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("ENFORCE_TWILIO_SIGNATURE", raising=False)
    monkeypatch.delenv("ENFORCE_WHITELIST", raising=False)
    monkeypatch.delenv("NUMEROS_AUTORIZADOS", raising=False)


# ─── Reconstrucción de URL ───────────────────────────────────────────────────────

def test_reconstruir_url_usa_forwarded_proto_y_host():
    """Detrás del proxy, la URL reconstruida debe ser la pública (https), no la interna."""
    req = _FakeRequest(_headers_proxy("x"))
    assert seg._reconstruir_url_publica(req) == URL_PUBLICA


def test_reconstruir_url_prefiere_railway_public_domain(monkeypatch):
    """RAILWAY_PUBLIC_DOMAIN tiene prioridad sobre los headers."""
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "otro-dominio.up.railway.app")
    req = _FakeRequest(_headers_proxy("x"))
    assert seg._reconstruir_url_publica(req) == "https://otro-dominio.up.railway.app/webhook"


# ─── Validación de firma (escenario del proxy) ───────────────────────────────────

def test_firma_legitima_valida_detras_del_proxy():
    """
    CASO CENTRAL: Twilio firma la URL pública; la petición llega con esquema
    interno http + headers de proxy. La firma legítima DEBE validar.
    """
    firma = RequestValidator(AUTH_TOKEN).compute_signature(URL_PUBLICA, PARAMS)
    req = _FakeRequest(_headers_proxy(firma))

    ok, motivo = seg.validar_firma(req, PARAMS)
    assert ok is True, f"la firma legítima no validó: {motivo}"
    assert motivo == ""


def test_firma_falsa_es_rechazada():
    """Una firma calculada con otro token (atacante) debe rechazarse."""
    firma_falsa = RequestValidator("token_de_atacante").compute_signature(URL_PUBLICA, PARAMS)
    req = _FakeRequest(_headers_proxy(firma_falsa))

    ok, motivo = seg.validar_firma(req, PARAMS)
    assert ok is False
    assert "no coincide" in motivo


def test_firma_falla_sin_header():
    """Sin header X-Twilio-Signature no se puede validar."""
    req = _FakeRequest({"x-forwarded-proto": "https", "x-forwarded-host": DOMINIO_PUBLICO})
    ok, motivo = seg.validar_firma(req, PARAMS)
    assert ok is False
    assert "X-Twilio-Signature" in motivo


def test_firma_falla_sin_token(monkeypatch):
    """Sin TWILIO_AUTH_TOKEN no se puede validar."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    firma = RequestValidator(AUTH_TOKEN).compute_signature(URL_PUBLICA, PARAMS)
    req = _FakeRequest(_headers_proxy(firma))
    ok, motivo = seg.validar_firma(req, PARAMS)
    assert ok is False
    assert "TWILIO_AUTH_TOKEN" in motivo


# ─── Whitelist ───────────────────────────────────────────────────────────────────

def test_whitelist_autoriza_numero_en_lista(monkeypatch):
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5219999999999,+5215550001111")
    ok, _ = seg.numero_autorizado("whatsapp:+5219999999999")
    assert ok is True


def test_whitelist_acepta_numero_sin_prefijo_whatsapp(monkeypatch):
    """La lista puede tener el número con o sin 'whatsapp:'; debe normalizar igual."""
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "+5219999999999")
    ok, _ = seg.numero_autorizado("whatsapp:+5219999999999")
    assert ok is True


def test_whitelist_rechaza_numero_fuera(monkeypatch):
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5219999999999")
    ok, motivo = seg.numero_autorizado("whatsapp:+5210000000000")
    assert ok is False
    assert "whitelist" in motivo


def test_whitelist_vacia_autoriza_a_todos():
    """Lista vacía = no filtra (red de seguridad para no dejar fuera a la empresa)."""
    ok, motivo = seg.numero_autorizado("whatsapp:+5210000000000")
    assert ok is True
    assert "vacío" in motivo


# ─── Modo log-only vs enforcement ────────────────────────────────────────────────

def test_log_only_no_bloquea_aunque_falle_todo(monkeypatch):
    """Con flags apagados: firma inválida + número fuera → NO bloquea (retorna None)."""
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5219999999999")
    req = _FakeRequest(_headers_proxy("firma_basura"))
    resultado = seg.verificar_peticion(
        req, {"Body": "x", "From": "whatsapp:+5210000000000"}, "whatsapp:+5210000000000"
    )
    assert resultado is None


def test_enforce_firma_bloquea_con_403(monkeypatch):
    monkeypatch.setenv("ENFORCE_TWILIO_SIGNATURE", "1")
    req = _FakeRequest(_headers_proxy("firma_basura"))
    resultado = seg.verificar_peticion(
        req, {"Body": "x", "From": "whatsapp:+5219999999999"}, "whatsapp:+5219999999999"
    )
    assert resultado is not None
    assert resultado.status_code == 403


def test_enforce_whitelist_bloquea_con_403(monkeypatch):
    """Con firma válida pero número fuera de la whitelist y enforce activo → 403."""
    monkeypatch.setenv("ENFORCE_WHITELIST", "1")
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5219999999999")
    firma = RequestValidator(AUTH_TOKEN).compute_signature(URL_PUBLICA, PARAMS)
    req = _FakeRequest(_headers_proxy(firma))
    resultado = seg.verificar_peticion(
        req, PARAMS, "whatsapp:+5210000000000"
    )
    assert resultado is not None
    assert resultado.status_code == 403


def test_peticion_legitima_y_autorizada_pasa(monkeypatch):
    """Firma válida + número autorizado + enforce activo → pasa (None)."""
    monkeypatch.setenv("ENFORCE_TWILIO_SIGNATURE", "1")
    monkeypatch.setenv("ENFORCE_WHITELIST", "1")
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5219999999999")
    firma = RequestValidator(AUTH_TOKEN).compute_signature(URL_PUBLICA, PARAMS)
    req = _FakeRequest(_headers_proxy(firma))
    resultado = seg.verificar_peticion(req, PARAMS, "whatsapp:+5219999999999")
    assert resultado is None
