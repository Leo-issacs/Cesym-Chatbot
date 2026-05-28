"""
logger.py
---------
Registro de consultas al bot. Guarda en data/logs/queries.log.

Retención: 30 días. En cada escritura se podan entradas más antiguas.
"""

from datetime import datetime, timedelta
from pathlib import Path

_LOGS_DIR = Path(__file__).parent.parent / "data" / "logs"
_LOG_PATH = _LOGS_DIR / "queries.log"
_MAX_RESP_CHARS = 120
_RETENTION_DIAS = 30


def _enmascarar(numero: str) -> str:
    """whatsapp:+521234567890  →  +52****7890"""
    limpio = numero.replace("whatsapp:", "").strip()
    if len(limpio) >= 6:
        return limpio[:3] + "****" + limpio[-4:]
    return "****"


def _podar(lineas: list[str]) -> list[str]:
    """Elimina entradas con más de _RETENTION_DIAS días de antigüedad."""
    limite = datetime.now() - timedelta(days=_RETENTION_DIAS)
    resultado = []
    for linea in lineas:
        try:
            ts = datetime.strptime(linea[1:20], "%Y-%m-%d %H:%M:%S")
            if ts >= limite:
                resultado.append(linea)
        except (ValueError, IndexError):
            resultado.append(linea)  # conservar líneas con formato inesperado
    return resultado


def registrar(numero: str, consulta: str, respuesta: str) -> None:
    """Agrega una línea al log y poda entradas viejas. Falla silenciosamente."""
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        num = _enmascarar(numero)
        resp_corta = respuesta.replace("\n", " ")[:_MAX_RESP_CHARS]
        if len(respuesta) > _MAX_RESP_CHARS:
            resp_corta += "..."
        nueva = f"[{ts}] {num} | {consulta!r} → {resp_corta}"

        lineas = []
        if _LOG_PATH.exists():
            lineas = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        lineas.append(nueva)
        lineas = _podar(lineas)

        _LOG_PATH.write_text("\n".join(lineas) + "\n", encoding="utf-8")
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
