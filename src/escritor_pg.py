"""
escritor_pg.py
--------------
Escritura de trabajos en PostgreSQL (schema chatbot). Primitivas INSERT/UPDATE/
DELETE sobre la tabla `trabajos`, más resolución nombre→id para clientes/técnicos.

CONTRATO DE TRANSACCIÓN
  Todas las funciones reciben una conexión SQLAlchemy ya abierta y NO manejan la
  transacción: el caller decide commit/rollback (típicamente `with engine.begin()`).
  Así un fallo a mitad deja todo revertido (sin commit parcial).

NOMBRES DE TABLA SIN PREFIJO DE SCHEMA
  Se usan nombres desnudos (`trabajos`, `clientes`, `tecnicos`) a propósito:
    - en Postgres, el caller fija el schema con `SET search_path TO chatbot`;
    - en los tests, SQLite (que no tiene schemas) los resuelve directo.
  El mismo SQL sirve para ambos.

RESOLUCIÓN nombre→id
  chatbot.trabajos referencia clientes/tecnicos por id (FK). Un trabajo nuevo
  llega con NOMBRES (desde WhatsApp), así que resolver_o_crear_* normaliza
  (strip + upper, igual que el ETL en cargar_bd.py) y crea la fila si no existe,
  para que el trabajo aparezca con su cliente/técnico al leer desde Postgres.
"""

from sqlalchemy import text

# Columnas de trabajos que escribe el bot (id es SERIAL, lo asigna Postgres).
_COLUMNAS = [
    "mes", "tecnico_id", "cliente_id", "rep_num", "domicilio",
    "telefono", "tipo_trabajo", "pagado", "recibe",
]


def insertar_trabajo(conn, datos: dict) -> int:
    """
    INSERT INTO trabajos (...) VALUES (...) RETURNING id.

    `datos` usa las claves de las columnas de la tabla (incluidos tecnico_id y
    cliente_id ya resueltos). Devuelve el id asignado por la BD. Lanza excepción
    si falla (el caller decide el fallback).
    """
    cols = ", ".join(_COLUMNAS)
    placeholders = ", ".join(f":{c}" for c in _COLUMNAS)
    sql = text(f"INSERT INTO trabajos ({cols}) VALUES ({placeholders}) RETURNING id")
    params = {c: datos.get(c) for c in _COLUMNAS}
    return int(conn.execute(sql, params).scalar_one())


def actualizar_trabajo(conn, pg_id: int, datos: dict) -> None:
    """UPDATE trabajos SET ... WHERE id = pg_id. Solo toca las columnas presentes en `datos`."""
    columnas = [c for c in _COLUMNAS if c in datos]
    if not columnas:
        return
    asignaciones = ", ".join(f"{c} = :{c}" for c in columnas)
    params = {c: datos[c] for c in columnas}
    params["pg_id"] = pg_id
    conn.execute(text(f"UPDATE trabajos SET {asignaciones} WHERE id = :pg_id"), params)


def borrar_trabajo(conn, pg_id: int) -> None:
    """DELETE FROM trabajos WHERE id = pg_id."""
    conn.execute(text("DELETE FROM trabajos WHERE id = :pg_id"), {"pg_id": pg_id})


def resolver_o_crear_cliente(conn, nombre: str) -> int | None:
    """Devuelve el id del cliente (normalizado strip+upper); lo crea si no existe.
    Nombre vacío → None (trabajo sin cliente asignado)."""
    return _resolver_o_crear(conn, "clientes", nombre)


def resolver_o_crear_tecnico(conn, nombre: str) -> int | None:
    """Devuelve el id del técnico (normalizado strip+upper); lo crea si no existe.
    Nombre vacío → None."""
    return _resolver_o_crear(conn, "tecnicos", nombre)


def _resolver_o_crear(conn, tabla: str, nombre: str) -> int | None:
    n = (nombre or "").strip().upper()
    if not n:
        return None
    fila = conn.execute(
        text(f"SELECT id FROM {tabla} WHERE nombre = :n"), {"n": n}
    ).first()
    if fila is not None:
        return int(fila[0])
    nuevo_id = conn.execute(
        text(f"INSERT INTO {tabla} (nombre) VALUES (:n) RETURNING id"), {"n": n}
    ).scalar_one()
    return int(nuevo_id)
