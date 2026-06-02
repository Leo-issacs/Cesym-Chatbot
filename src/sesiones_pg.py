"""
sesiones_pg.py
--------------
Backend de almacenamiento de sesiones en PostgreSQL.
Reemplaza la lectura/escritura a data/sesiones.json.

POR QUÉ ESTE MÓDULO EXISTE:
  Railway usa un filesystem efímero: data/sesiones.json se borra en cada deploy.
  Esto significa que usuarios en mitad de un flujo (ej: registrando un trabajo)
  pierden su contexto y el bot les pide empezar de nuevo.
  Al guardar el estado en Postgres, el estado sobrevive cualquier redeploy.

CÓMO ACTIVARLO (cuando estés listo):
  1. Asegúrate de tener DATABASE_URL definida en Railway.
  2. Ejecuta: python scripts/migrar_sqlite_a_postgres.py (crea el schema).
  3. En Railway o en .env, agrega: USE_POSTGRES_SESSIONS=1
  4. Redeploya. Las sesiones ahora viven en chatbot.sesiones_bot.

ESTADO ACTUAL:
  INACTIVO — sesiones.py lee USE_POSTGRES_SESSIONS y delega aquí si está en "1".
  Por defecto es "0", así que nada cambia hasta que lo actives.

INTERFAZ:
  cargar_todas()          → dict {numero: estado_dict}
  guardar_todas(sesiones) → None  (escribe el estado completo)
  guardar_una(numero, estado) → None  (actualiza una sesión)
  borrar(numero)          → None  (elimina una sesión)

  La tabla chatbot.sesiones_bot guarda cada sesión como JSONB:
    numero         TEXT PRIMARY KEY  — número de WhatsApp (ej: "whatsapp:+521234...")
    estado         JSONB             — el dict Python con tipo, paso y datos
    actualizado_en TIMESTAMPTZ       — permite limpiar sesiones inactivas con un cron
"""

import json
import os

from sqlalchemy import text

from src.db_postgres import SCHEMA, get_engine


def _engine():
    return get_engine()


def cargar_todas() -> dict:
    """
    Lee todas las sesiones activas de Postgres.
    Retorna {numero: estado_dict}, equivalente al _sesiones global de sesiones.py.
    """
    try:
        with _engine().connect() as conn:
            filas = conn.execute(
                text(f"SELECT numero, estado FROM {SCHEMA}.sesiones_bot")
            ).fetchall()
        return {fila[0]: fila[1] for fila in filas}
    except Exception as e:
        print(f"[sesiones_pg] Error al cargar sesiones: {e}")
        return {}


def guardar_todas(sesiones: dict) -> None:
    """
    Sobreescribe el estado completo de sesiones.
    Usado cuando sesiones.py llama a _guardar() con el dict global _sesiones.

    Implementa un upsert: si el número ya existe, actualiza el estado.
    Las sesiones que ya no están en el dict se borran de la BD.
    """
    try:
        with _engine().connect() as conn:
            # Borrar sesiones que ya terminaron (no están en el dict)
            numeros_activos = list(sesiones.keys())
            if numeros_activos:
                conn.execute(
                    text(
                        f"DELETE FROM {SCHEMA}.sesiones_bot "
                        f"WHERE numero != ALL(:numeros)"
                    ),
                    {"numeros": numeros_activos},
                )
            else:
                conn.execute(text(f"DELETE FROM {SCHEMA}.sesiones_bot"))

            # Upsert de cada sesión activa
            for numero, estado in sesiones.items():
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {SCHEMA}.sesiones_bot (numero, estado, actualizado_en)
                        VALUES (:numero, CAST(:estado AS JSONB), NOW())
                        ON CONFLICT (numero) DO UPDATE
                            SET estado         = EXCLUDED.estado,
                                actualizado_en = NOW()
                        """
                    ),
                    {"numero": numero, "estado": json.dumps(estado, ensure_ascii=False)},
                )
            conn.commit()
    except Exception as e:
        print(f"[sesiones_pg] Error al guardar sesiones: {e}")


def guardar_una(numero: str, estado: dict) -> None:
    """
    Upsert de una sola sesión. Más eficiente que guardar_todas() para
    actualizaciones incrementales durante un flujo conversacional.
    """
    try:
        with _engine().connect() as conn:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.sesiones_bot (numero, estado, actualizado_en)
                    VALUES (:numero, CAST(:estado AS JSONB), NOW())
                    ON CONFLICT (numero) DO UPDATE
                        SET estado         = EXCLUDED.estado,
                            actualizado_en = NOW()
                    """
                ),
                {"numero": numero, "estado": json.dumps(estado, ensure_ascii=False)},
            )
            conn.commit()
    except Exception as e:
        print(f"[sesiones_pg] Error al guardar sesión {numero}: {e}")


def borrar(numero: str) -> None:
    """Elimina la sesión de un número. Se llama cuando el flujo termina o se cancela."""
    try:
        with _engine().connect() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.sesiones_bot WHERE numero = :numero"),
                {"numero": numero},
            )
            conn.commit()
    except Exception as e:
        print(f"[sesiones_pg] Error al borrar sesión {numero}: {e}")
