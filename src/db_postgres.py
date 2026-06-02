"""
db_postgres.py
--------------
Capa de acceso a PostgreSQL (Fase 1 — migración de SQLite).

Conexión:
  DATABASE_URL            → URL de runtime. Acepta el pooler de Supabase (puerto 6543)
                            o la URL directa de Railway. El bot la usa para leer/escribir.
  DATABASE_MIGRATION_URL  → URL directa para DDL (CREATE TABLE, Alembic, migraciones).
                            En Supabase: usa el puerto 5432 (no el pooler).
                            En Railway:  puede ser la misma que DATABASE_URL.
                            Si no está definida, se usa DATABASE_URL para todo.

  Por qué dos URLs en Supabase:
    El Transaction Pooler (puerto 6543) no admite comandos DDL que cruzan transacciones
    (como CREATE TABLE con FK en el mismo bloque). El puerto 5432 (directo) sí lo admite.
    En Railway no hay esta distinción: una sola URL sirve para todo.

Esquema PostgreSQL: "chatbot"
  Aisla nuestras tablas del schema "public" por si la instancia es compartida.
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

SCHEMA = "chatbot"

# DDL completo del esquema.
# Equivalente al SCHEMA_SQL de db.py pero con tipos nativos de PostgreSQL:
#   INTEGER AUTOINCREMENT → SERIAL (o BIGSERIAL para tablas grandes)
#   REAL                  → DOUBLE PRECISION
#   TEXT para fechas      → DATE (Postgres sí tiene tipo nativo)
#   JSONB para sesiones   → tipo nativo binario, más eficiente que JSON plano
SCHEMA_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {SCHEMA}.clientes (
    id          SERIAL           PRIMARY KEY,
    nombre      TEXT             NOT NULL UNIQUE,
    nombre_raw  TEXT,
    fuente      TEXT
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.tecnicos (
    id      SERIAL  PRIMARY KEY,
    nombre  TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.facturas (
    id             SERIAL           PRIMARY KEY,
    folio          INTEGER          NOT NULL UNIQUE,
    cliente_id     INTEGER          REFERENCES {SCHEMA}.clientes(id),
    fecha_emision  DATE,
    concepto       TEXT,
    total          DOUBLE PRECISION,
    fecha_pago     DATE,
    cancelada      SMALLINT         NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.ordenes_compra (
    id              SERIAL           PRIMARY KEY,
    tipo            TEXT             NOT NULL,
    numero_oc       TEXT,
    folio_factura   INTEGER,
    monto           DOUBLE PRECISION,
    prioridad       TEXT,
    estado          TEXT,
    fecha           DATE,
    num_cotizacion  INTEGER,
    sucursal        INTEGER,
    concepto        TEXT
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.trabajos (
    id           SERIAL           PRIMARY KEY,
    mes          TEXT,
    tecnico_id   INTEGER          REFERENCES {SCHEMA}.tecnicos(id),
    cliente_id   INTEGER          REFERENCES {SCHEMA}.clientes(id),
    rep_num      TEXT,
    domicilio    TEXT,
    telefono     TEXT,
    tipo_trabajo TEXT,
    pagado       DOUBLE PRECISION,
    recibe       TEXT
);

-- Reemplaza data/sesiones.json (que en Railway se borra en cada deploy).
-- estado: JSONB almacena el dict Python de la sesión multi-turno directamente.
-- actualizado_en: permite limpiar sesiones inactivas con un cron si se desea.
CREATE TABLE IF NOT EXISTS {SCHEMA}.sesiones_bot (
    numero         TEXT        PRIMARY KEY,
    estado         JSONB       NOT NULL,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# SQL para resetear las secuencias SERIAL después de insertar con IDs explícitos.
# Necesario si el script de migración inserta con los mismos IDs del SQLite.
RESET_SEQUENCES_SQL = f"""
SELECT setval(
    pg_get_serial_sequence('{SCHEMA}.clientes', 'id'),
    COALESCE((SELECT MAX(id) FROM {SCHEMA}.clientes), 0)
);
SELECT setval(
    pg_get_serial_sequence('{SCHEMA}.tecnicos', 'id'),
    COALESCE((SELECT MAX(id) FROM {SCHEMA}.tecnicos), 0)
);
SELECT setval(
    pg_get_serial_sequence('{SCHEMA}.facturas', 'id'),
    COALESCE((SELECT MAX(id) FROM {SCHEMA}.facturas), 0)
);
SELECT setval(
    pg_get_serial_sequence('{SCHEMA}.ordenes_compra', 'id'),
    COALESCE((SELECT MAX(id) FROM {SCHEMA}.ordenes_compra), 0)
);
SELECT setval(
    pg_get_serial_sequence('{SCHEMA}.trabajos', 'id'),
    COALESCE((SELECT MAX(id) FROM {SCHEMA}.trabajos), 0)
);
"""


def _normalizar_url(url: str) -> str:
    """Convierte 'postgres://' a 'postgresql+psycopg2://' para SQLAlchemy 2.x."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


def get_engine(url: str | None = None):
    """
    Motor SQLAlchemy para operaciones de runtime (lectura/escritura del bot).

    Acepta el pooler de Supabase (puerto 6543) o la URL directa de Railway.
    pool_pre_ping=True: verifica la conexión antes de cada operación (evita
    errores silenciosos cuando el pooler cierra conexiones inactivas).
    """
    raw_url = url or os.environ.get("DATABASE_URL", "")
    if not raw_url:
        raise RuntimeError(
            "DATABASE_URL no está definida. "
            "Agrégala al .env (desarrollo) o a las variables de Railway (producción)."
        )
    return create_engine(_normalizar_url(raw_url), pool_pre_ping=True)


def get_migration_engine():
    """
    Motor SQLAlchemy para DDL (CREATE TABLE, ALTER TABLE, Alembic).

    Usa DATABASE_MIGRATION_URL si está disponible (conexión directa, puerto 5432).
    Si no está, usa DATABASE_URL — funciona siempre, pero con Supabase Transaction
    Pooler puede fallar en DDL multi-statement.

    Recomendación Supabase:
      DATABASE_URL           = postgresql://...supabase.com:6543/postgres?pgbouncer=true
      DATABASE_MIGRATION_URL = postgresql://...supabase.com:5432/postgres

    Railway:
      DATABASE_URL y DATABASE_MIGRATION_URL pueden ser la misma URL.

    NullPool: cada operación abre y cierra su propia conexión física.
    Obligatorio para Alembic y DDL con el pooler de Supabase.
    """
    raw_url = (
        os.environ.get("DATABASE_MIGRATION_URL")
        or os.environ.get("DATABASE_URL", "")
    )
    if not raw_url:
        raise RuntimeError(
            "Ni DATABASE_MIGRATION_URL ni DATABASE_URL están definidas."
        )
    return create_engine(_normalizar_url(raw_url), poolclass=NullPool)


def crear_schema(engine=None) -> None:
    """
    Crea el schema 'chatbot' y todas sus tablas si no existen (idempotente).
    Usar siempre con get_migration_engine() para garantizar compatibilidad DDL.
    """
    eng = engine or get_migration_engine()
    with eng.connect() as conn:
        conn.execute(text(SCHEMA_SQL))
        conn.commit()
    print(f"[db_postgres] Schema '{SCHEMA}' y tablas verificadas/creadas correctamente.")


def resetear_secuencias(engine=None) -> None:
    """
    Sincroniza los contadores SERIAL con el MAX(id) de cada tabla.
    Llamar siempre después de insertar filas con IDs explícitos (migración).
    """
    eng = engine or get_migration_engine()
    with eng.connect() as conn:
        for stmt in RESET_SEQUENCES_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()
    print("[db_postgres] Secuencias SERIAL reseteadas correctamente.")


def contar_filas(engine=None) -> dict[str, int]:
    """Retorna conteo de filas por tabla. Útil para verificar la migración."""
    eng = engine or get_engine()
    tablas = [
        "clientes", "tecnicos", "facturas",
        "ordenes_compra", "trabajos", "sesiones_bot",
    ]
    conteos: dict[str, int] = {}
    with eng.connect() as conn:
        for tabla in tablas:
            try:
                conteos[tabla] = conn.execute(
                    text(f"SELECT COUNT(*) FROM {SCHEMA}.{tabla}")
                ).scalar()
            except Exception:
                conteos[tabla] = -1
    return conteos
