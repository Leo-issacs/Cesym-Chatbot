"""
logger.py
---------
Registro de consultas al bot. Guarda en data/logs/queries.log.

Cada entrada incluye: timestamp, número (enmascarado), consulta y respuesta corta.
Los logs sobreviven reinicios del servidor pero se pierden en deploys nuevos.
"""

from datetime import datetime
from pathlib import Path

_LOGS_DIR = Path(__file__).parent.parent / "data" / "logs"
_LOG_PATH = _LOGS_DIR / "queries.log"
_MAX_RESP_CHARS = 120


def _enmascarar(numero: str) -> str:
    """whatsapp:+521234567890  →  +52****7890"""
    limpio = numero.replace("whatsapp:", "").strip()
    if len(limpio) >= 6:
        return limpio[:3] + "****" + limpio[-4:]
    return "****"


def registrar(numero: str, consulta: str, respuesta: str) -> None:
    """Agrega una línea al log. Falla silenciosamente si hay error de escritura."""
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        num = _enmascarar(numero)
        resp_corta = respuesta.replace("\n", " ")[:_MAX_RESP_CHARS]
        if len(respuesta) > _MAX_RESP_CHARS:
            resp_corta += "..."
        linea = f"[{ts}] {num} | {consulta!r} → {resp_corta}\n"
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(linea)
    except Exception:
        pass


def leer_recientes(n: int = 20) -> str:
    """Retorna las últimas N líneas del log formateadas para WhatsApp."""
    if not _LOG_PATH.exists():
        return "No hay consultas registradas aún."
    try:
        lineas = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        recientes = lineas[-n:] if len(lineas) > n else lineas
        if not recientes:
            return "No hay consultas registradas aún."
        return f"Últimas {len(recientes)} consultas:\n\n" + "\n".join(recientes)
    except Exception as e:
        return f"Error al leer logs: {e}"
