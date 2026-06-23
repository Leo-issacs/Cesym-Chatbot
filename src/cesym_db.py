"""
cesym_db.py
-----------
Acceso a la BD consolidada `cesym_db` (esquema Fase 1, tablas en `public`).
Conexión por CESYM_DB_URL, INDEPENDIENTE de DATABASE_URL (chatbot_db no se toca).
Aquí viven solo las LECTURAS de catálogo que usa el flujo de cotizaciones; las
escrituras están en cotizaciones_pg.py.
"""
import os
import re

from sqlalchemy import create_engine, text

_RFC_RE = re.compile(r"^[A-ZÑ&0-9]{12,13}$")


def _normalizar_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


def get_cesym_engine(url: str | None = None):
    """Motor SQLAlchemy a cesym_db. Lee CESYM_DB_URL si no se pasa `url`."""
    raw = url or os.environ.get("CESYM_DB_URL", "")
    if not raw:
        raise RuntimeError(
            "CESYM_DB_URL no está definida. Agrégala al .env (desarrollo) o a las "
            "variables del servicio (producción). Es independiente de DATABASE_URL."
        )
    return create_engine(
        _normalizar_url(raw), pool_pre_ping=True, pool_size=3, max_overflow=2,
        connect_args={"prepare_threshold": None},
    )


def buscar_clientes(texto: str, engine=None) -> list[dict]:
    """Busca clientes por RFC exacto (si `texto` parece RFC) o por nombre parcial
    (comercial o fiscal, sin distinguir mayúsculas). Devuelve lista de dicts."""
    t = (texto or "").strip()
    if not t:
        return []
    eng = engine or get_cesym_engine()
    if _RFC_RE.match(t.upper()):
        sql = ("SELECT rfc, nombre_fiscal, nombre_comercial FROM clientes "
               "WHERE rfc = :rfc")
        params = {"rfc": t.upper()}
    else:
        sql = ("SELECT rfc, nombre_fiscal, nombre_comercial FROM clientes "
               "WHERE LOWER(nombre_comercial) LIKE :t OR LOWER(nombre_fiscal) LIKE :t "
               "ORDER BY nombre_comercial")
        params = {"t": f"%{t.lower()}%"}
    with eng.connect() as conn:
        filas = conn.execute(text(sql), params).mappings().all()
    return [dict(f) for f in filas]


def listar_sucursales(cliente_rfc: str, engine=None) -> list[dict]:
    """Sucursales de un cliente (id, suc, nombre)."""
    eng = engine or get_cesym_engine()
    with eng.connect() as conn:
        filas = conn.execute(
            text("SELECT id, suc, nombre FROM sucursales WHERE cliente_rfc = :r "
                 "ORDER BY suc"),
            {"r": cliente_rfc},
        ).mappings().all()
    return [dict(f) for f in filas]
