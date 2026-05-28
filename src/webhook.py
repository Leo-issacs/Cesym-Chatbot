"""
webhook.py
----------
Servidor FastAPI que recibe mensajes de WhatsApp via Twilio y responde
con los resultados del sistema de consulta de cartera.

Arranque local (desarrollo con ngrok):
    uvicorn src.webhook:app --reload --port 8000

Despliegue cloud (Railway / Render):
    Procfile: web: uvicorn src.webhook:app --host 0.0.0.0 --port $PORT
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Response

from src.cli import _cargar_dotenv, _cargar_datos, _sincronizar_drive
from src.query_engine import run_query

_LIMITE_WA = 4000  # Twilio trunca mensajes > 4096 chars

# ─── Estado global ─────────────────────────────────────────────────────────────
_datos: dict = {}
_cliente_ia = None
_traducir_fn = None


def _recargar_datos() -> list[str]:
    fac, pte, men, tra, adv = _cargar_datos()
    _datos.update({"facturado": fac, "pendiente": pte,
                   "facturas_mensual": men, "trabajos": tra})
    return adv


def _init_ia():
    global _cliente_ia, _traducir_fn
    try:
        import anthropic
        from src.ai_query import traducir_a_comando
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            _cliente_ia = anthropic.Anthropic(api_key=key)
            _traducir_fn = traducir_a_comando
    except ImportError:
        pass


# ─── Arranque ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _cargar_dotenv()

    # En cloud: inicializar credenciales de Drive desde variables de entorno
    try:
        from src.drive import init_credenciales_desde_env
        init_credenciales_desde_env()
    except Exception:
        pass

    # Sincronizar datos desde Drive al iniciar (si está configurado)
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id:
        try:
            _sincronizar_drive()
        except Exception:
            pass  # Si falla, intenta cargar lo que haya en data/raw/

    _recargar_datos()
    _init_ia()
    yield


app = FastAPI(lifespan=lifespan)


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _twiml(texto: str) -> Response:
    """Empaqueta texto en TwiML. Trunca si supera el límite de WhatsApp."""
    from twilio.twiml.messaging_response import MessagingResponse

    if len(texto) > _LIMITE_WA:
        texto = texto[:_LIMITE_WA - 60] + "\n...(respuesta muy larga, afiná la consulta)"
    r = MessagingResponse()
    r.message(texto)
    return Response(content=str(r), media_type="application/xml")


def _ejecutar_consulta(entrada: str) -> str:
    respuesta = run_query(
        entrada,
        _datos["facturado"],
        _datos["pendiente"],
        _datos["facturas_mensual"],
        _datos["trabajos"],
    )
    if respuesta.startswith("Comando no reconocido") and _cliente_ia:
        cmd = _traducir_fn(entrada, _cliente_ia)
        if cmd:
            respuesta = run_query(
                cmd,
                _datos["facturado"],
                _datos["pendiente"],
                _datos["facturas_mensual"],
                _datos["trabajos"],
            )
    return respuesta


# ─── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    """Health check — también muestra cuántos registros hay cargados."""
    return {
        "status": "ok",
        "registros": {k: len(v) for k, v in _datos.items()},
        "ia": _cliente_ia is not None,
    }


@app.post("/webhook")
async def webhook(Body: str = Form(...)):
    entrada = Body.strip()

    if not entrada:
        return _twiml("Hola. Escribí 'ayuda' para ver los comandos disponibles.")

    if entrada.lower() in ("salir", "exit", "quit"):
        return _twiml("Escribí 'ayuda' para ver los comandos disponibles.")

    if entrada.lower() == "actualizar":
        try:
            descargados = _sincronizar_drive()
            _recargar_datos()
            lineas = ["Datos actualizados desde Drive."]
            lineas += [f"  • {f}" for f in descargados]
            lineas.append(
                f"Cargados: {len(_datos['facturado'])} facturas | "
                f"{len(_datos['pendiente'])} pendientes | "
                f"{len(_datos['facturas_mensual'])} mensual | "
                f"{len(_datos['trabajos'])} trabajos"
            )
            return _twiml("\n".join(lineas))
        except Exception as e:
            return _twiml(f"Error al actualizar: {e}")

    return _twiml(_ejecutar_consulta(entrada))
