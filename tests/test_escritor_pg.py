"""
test_escritor_pg.py
-------------------
Tests herméticos de src/escritor_pg.py con SQLite in-memory (sin schema, sin
Postgres de producción). La tabla `trabajos` y `clientes`/`tecnicos` replican la
estructura de chatbot.* sin prefijo de schema, que es justo lo que escritor_pg
asume (nombres de tabla desnudos).
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src import escritor_pg

_DDL = [
    "CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE)",
    "CREATE TABLE tecnicos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE)",
    """CREATE TABLE trabajos (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        mes          TEXT,
        tecnico_id   INTEGER REFERENCES tecnicos(id),
        cliente_id   INTEGER REFERENCES clientes(id),
        rep_num      TEXT,
        domicilio    TEXT,
        telefono     TEXT,
        tipo_trabajo TEXT,
        pagado       REAL,
        recibe       TEXT
    )""",
]

_DATOS = {
    "mes": "ENERO", "tecnico_id": None, "cliente_id": None, "rep_num": "R1",
    "domicilio": "CALLE 1", "telefono": "5551111", "tipo_trabajo": "INSTALACION",
    "pagado": 1500.0, "recibe": "PEDRO",
}


@pytest.fixture
def engine():
    """SQLite in-memory con una sola conexión persistente (StaticPool)."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with eng.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return eng


# ─── 1-2: insertar ───────────────────────────────────────────────────────────
def test_insertar_devuelve_id_entero(engine):
    with engine.begin() as conn:
        pg_id = escritor_pg.insertar_trabajo(conn, _DATOS)
    assert isinstance(pg_id, int) and pg_id > 0


def test_insertar_guarda_los_datos(engine):
    with engine.begin() as conn:
        pg_id = escritor_pg.insertar_trabajo(conn, _DATOS)
    with engine.connect() as conn:
        fila = conn.execute(
            text("SELECT mes, rep_num, tipo_trabajo, pagado, recibe FROM trabajos WHERE id = :i"),
            {"i": pg_id},
        ).first()
    assert tuple(fila) == ("ENERO", "R1", "INSTALACION", 1500.0, "PEDRO")


# ─── 3: actualizar ─────────────────────────────────────────────────────────────
def test_actualizar_cambia_la_fila(engine):
    with engine.begin() as conn:
        pg_id = escritor_pg.insertar_trabajo(conn, _DATOS)
    with engine.begin() as conn:
        escritor_pg.actualizar_trabajo(conn, pg_id, {"pagado": 9999.0, "recibe": "ANA"})
    with engine.connect() as conn:
        fila = conn.execute(
            text("SELECT pagado, recibe FROM trabajos WHERE id = :i"), {"i": pg_id}
        ).first()
    assert tuple(fila) == (9999.0, "ANA")


# ─── 4: borrar ─────────────────────────────────────────────────────────────────
def test_borrar_elimina_la_fila(engine):
    with engine.begin() as conn:
        pg_id = escritor_pg.insertar_trabajo(conn, _DATOS)
    with engine.begin() as conn:
        escritor_pg.borrar_trabajo(conn, pg_id)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM trabajos WHERE id = :i"), {"i": pg_id}).scalar()
    assert n == 0


# ─── 5: atomicidad (sin commit parcial) ────────────────────────────────────────
def test_excepcion_en_la_transaccion_no_deja_fila(engine):
    """escritor_pg no commitea por sí mismo: si la transacción del caller falla,
    el INSERT del trabajo se revierte (no queda fila parcial)."""
    with pytest.raises(Exception):
        with engine.begin() as conn:
            escritor_pg.insertar_trabajo(conn, _DATOS)        # ok, dentro de la tx
            conn.execute(text("INSERT INTO clientes (nombre) VALUES ('X')"))
            conn.execute(text("INSERT INTO clientes (nombre) VALUES ('X')"))  # viola UNIQUE → aborta
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM trabajos")).scalar()
    assert n == 0  # el trabajo se revirtió con la transacción


# ─── 6-7: resolver_o_crear ─────────────────────────────────────────────────────
def test_resolver_o_crear_cliente_crea_y_reusa(engine):
    with engine.begin() as conn:
        id1 = escritor_pg.resolver_o_crear_cliente(conn, "  juan perez ")  # normaliza
        id2 = escritor_pg.resolver_o_crear_cliente(conn, "JUAN PEREZ")     # mismo cliente
    assert id1 == id2
    with engine.connect() as conn:
        nombre = conn.execute(text("SELECT nombre FROM clientes WHERE id = :i"), {"i": id1}).scalar()
        n = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
    assert nombre == "JUAN PEREZ" and n == 1


def test_resolver_o_crear_tecnico_y_vacio(engine):
    with engine.begin() as conn:
        tid = escritor_pg.resolver_o_crear_tecnico(conn, "maria")
        vacio = escritor_pg.resolver_o_crear_tecnico(conn, "   ")
    assert isinstance(tid, int) and tid > 0
    assert vacio is None
