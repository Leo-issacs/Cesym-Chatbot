"""
seguridad.py
------------
Seguridad del webhook de WhatsApp/Twilio. Dos capas independientes:

  1. Validación de firma (header X-Twilio-Signature) con el RequestValidator
     del SDK de Twilio. Garantiza que el mensaje vino realmente de Twilio y
     nadie inyectó una petición falsa conociendo la URL.

  2. Whitelist de números autorizados (NUMEROS_AUTORIZADOS). Solo los números
     en la lista pueden operar el bot.

MODO "LOG ONLY" (por defecto, seguro para producción):
  Ambas capas SIEMPRE se evalúan y registran cuando algo NO pasaría la
  validación, pero NO bloquean hasta que se activan sus flags:
     ENFORCE_TWILIO_SIGNATURE=1   → bloquea firmas inválidas
     ENFORCE_WHITELIST=1          → bloquea números no autorizados
  Así se puede observar en los logs de Railway, durante días si hace falta,
  que NO se rechazarían mensajes legítimos antes de prender el bloqueo real.

PROXY DE RAILWAY (causa #1 de falsos negativos de firma):
  Twilio firma la URL PÚBLICA (https://tu-app.up.railway.app/webhook), pero
  detrás del proxy FastAPI ve una URL interna (http://host-interno/webhook).
  Si validamos con la URL interna, la firma NUNCA coincide aunque el mensaje
  sea legítimo. Por eso reconstruimos la URL pública con X-Forwarded-Proto y
  el dominio público (RAILWAY_PUBLIC_DOMAIN / X-Forwarded-Host).
"""

import os

from twilio.request_validator import RequestValidator

from src.logger import _enmascarar


# ─── Flags de configuración ─────────────────────────────────────────────────────

def _flag(nombre: str) -> bool:
    """Lee un flag booleano de entorno. Solo '1'/'true'/'yes' lo activan."""
    return os.getenv(nombre, "0").strip().lower() in ("1", "true", "yes", "on")


def enforce_firma() -> bool:
    return _flag("ENFORCE_TWILIO_SIGNATURE")


def enforce_whitelist() -> bool:
    return _flag("ENFORCE_WHITELIST")


# ─── Logging de eventos de seguridad ────────────────────────────────────────────

def _log(evento: str, detalle: str) -> None:
    """
    Registra un evento de seguridad en stdout (capturado por los logs de Railway,
    que es donde se observa durante la fase log-only — el archivo queries.log es
    efímero en Railway y no sirve para esto).
    """
    print(f"[seguridad] {evento} | {detalle}", flush=True)


# ─── Reconstrucción de la URL pública ────────────────────────────────────────────

def _reconstruir_url_publica(request) -> str:
    """
    Reconstruye la URL pública exacta que Twilio usó para firmar.

    Prioridad del esquema (http/https):
        X-Forwarded-Proto (lo pone el proxy de Railway) → request.url.scheme
    Prioridad del host:
        RAILWAY_PUBLIC_DOMAIN (variable que Railway inyecta, la más confiable)
        → X-Forwarded-Host → header Host → request.url.hostname
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = (
        os.getenv("RAILWAY_PUBLIC_DOMAIN")
        or request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.hostname
    )
    url = f"{proto}://{host}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


# ─── Capa 1: validación de firma ─────────────────────────────────────────────────

def validar_firma(request, params: dict) -> tuple[bool, str]:
    """
    Valida la firma X-Twilio-Signature contra la URL pública y los params del POST.

    Retorna (es_valida, motivo). Si es_valida=True, motivo es "".
    """
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not token:
        return False, "TWILIO_AUTH_TOKEN no configurado"

    firma = request.headers.get("x-twilio-signature", "")
    if not firma:
        return False, "falta header X-Twilio-Signature"

    url = _reconstruir_url_publica(request)
    validator = RequestValidator(token)
    es_valida = validator.validate(url, params, firma)
    if es_valida:
        return True, ""
    return False, f"firma no coincide (url reconstruida={url})"


# ─── Capa 2: whitelist de números ────────────────────────────────────────────────

def _normalizar_numero(numero: str) -> str:
    """
    Normaliza un número para comparar: quita 'whatsapp:', espacios y minúsculas.
    Acepta que la whitelist tenga 'whatsapp:+521...' o solo '+521...'.
    """
    return numero.strip().lower().replace("whatsapp:", "").replace(" ", "")


def _numeros_autorizados() -> set[str]:
    """Lee NUMEROS_AUTORIZADOS (separados por comas) y los normaliza."""
    crudo = os.getenv("NUMEROS_AUTORIZADOS", "")
    return {_normalizar_numero(n) for n in crudo.split(",") if n.strip()}


def numero_autorizado(numero: str) -> tuple[bool, str]:
    """
    Verifica si un número está en la whitelist.

    Retorna (autorizado, motivo).

    Caso especial: si NUMEROS_AUTORIZADOS está vacío, se AUTORIZA a todos
    (con advertencia). Es intencional para no dejar fuera a toda la empresa
    si alguien activa ENFORCE_WHITELIST sin haber poblado la lista.
    """
    autorizados = _numeros_autorizados()
    if not autorizados:
        return True, "NUMEROS_AUTORIZADOS vacío — no se filtra (configura la lista)"
    if _normalizar_numero(numero) in autorizados:
        return True, ""
    return False, "número fuera de la whitelist"


# ─── Punto de entrada usado por el webhook ───────────────────────────────────────

def verificar_peticion(request, params: dict, numero: str):
    """
    Ejecuta ambas capas de seguridad sobre una petición entrante.

    Comportamiento:
      - SIEMPRE evalúa firma y whitelist.
      - SIEMPRE registra en el log cuando algo NO pasaría (modo observación).
      - Solo BLOQUEA si el flag de enforcement correspondiente está activo.

    Retorna:
      - None  → la petición puede continuar al manejador del webhook.
      - Response(status_code=403) → la petición debe rechazarse (solo si enforce).
    """
    # Import local para no acoplar este módulo a FastAPI al importarlo en tests.
    from fastapi import Response

    num_mask = _enmascarar(numero)

    # ── Capa 1: firma ──────────────────────────────────────────────
    firma_ok, motivo_firma = validar_firma(request, params)
    if not firma_ok:
        modo = "BLOQUEARÍA" if enforce_firma() else "log-only (no bloquea)"
        _log("FIRMA INVÁLIDA", f"{num_mask} | {motivo_firma} | {modo}")
        if enforce_firma():
            return Response(status_code=403, content="Firma inválida")

    # ── Capa 2: whitelist ──────────────────────────────────────────
    autorizado, motivo_wl = numero_autorizado(numero)
    if not autorizado:
        modo = "BLOQUEARÍA" if enforce_whitelist() else "log-only (no bloquea)"
        _log("NÚMERO NO AUTORIZADO", f"{num_mask} | {motivo_wl} | {modo}")
        if enforce_whitelist():
            return Response(status_code=403, content="Número no autorizado")
    elif motivo_wl:
        # Lista vacía: dejar rastro de que la whitelist no está filtrando.
        _log("WHITELIST ABIERTA", f"{num_mask} | {motivo_wl}")

    return None
