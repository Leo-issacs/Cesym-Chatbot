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


# ─── 6-8: cableado de editar/borrar por pg_id en escritor.py ─────────────────
import pandas as pd  # noqa: E402
import src.escritor as escritor  # noqa: E402

# DataFrame "Excel" vacío con las 10 columnas posicionales (para mockear la lectura).
_DF_VACIO = pd.DataFrame(columns=[str(i) for i in range(10)])


def test_editar_con_pg_id_actualiza_db(engine, monkeypatch):
    """editar_trabajo con pg_id válido → la fila cambia en la BD (Excel mockeado)."""
    with engine.begin() as conn:
        pgid = escritor_pg.insertar_trabajo(conn, {**_DATOS, "pagado": 1000.0})
    monkeypatch.setenv("USE_POSTGRES_WRITES", "1")
    import src.db_postgres as dbp
    monkeypatch.setattr(dbp, "get_engine", lambda *a, **k: engine)
    monkeypatch.setattr(escritor, "_obtener_o_crear_archivo_trabajos", lambda: None)
    monkeypatch.setattr(escritor, "_cargar_trabajos", lambda path: (_DF_VACIO.copy(), [], "2", "6"))

    res = escritor.editar_trabajo(0, "pagado", "9999", pg_id=pgid,
                                  clave={"cliente": "X", "tipo_trabajo": "Y", "mes": "Z"})
    assert res == "Trabajo actualizado correctamente."
    with engine.connect() as conn:
        v = conn.execute(text("SELECT pagado FROM trabajos WHERE id = :i"), {"i": pgid}).scalar()
    assert v == 9999.0


def test_borrar_con_pg_id_elimina_db(engine, monkeypatch):
    """borrar_trabajo con pg_id válido → la fila desaparece de la BD (Excel mockeado)."""
    with engine.begin() as conn:
        pgid = escritor_pg.insertar_trabajo(conn, _DATOS)
    monkeypatch.setenv("USE_POSTGRES_WRITES", "1")
    import src.db_postgres as dbp
    monkeypatch.setattr(dbp, "get_engine", lambda *a, **k: engine)
    monkeypatch.setattr(escritor, "_obtener_o_crear_archivo_trabajos", lambda: None)
    monkeypatch.setattr(escritor, "_cargar_trabajos", lambda path: (_DF_VACIO.copy(), [], "2", "6"))

    res = escritor.borrar_trabajo(0, pg_id=pgid,
                                  clave={"cliente": "X", "tipo_trabajo": "Y", "mes": "Z"})
    assert "eliminado correctamente" in res
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM trabajos WHERE id = :i"), {"i": pgid}).scalar()
    assert n == 0


def test_editar_sin_pg_id_cae_a_posicional(monkeypatch, capsys):
    """Flag activo pero sin pg_id → edita por índice posicional, loguea aviso, no lanza."""
    monkeypatch.setenv("USE_POSTGRES_WRITES", "1")
    df = pd.DataFrame(
        [["ENERO", "T", "CLI", "R", "D", "TEL", "TIPO", "", "100", "REC"]],
        columns=[str(i) for i in range(10)],
    )
    capturado = {}
    monkeypatch.setattr(escritor, "_obtener_o_crear_archivo_trabajos", lambda: None)
    monkeypatch.setattr(escritor, "_cargar_trabajos", lambda path: (df.copy(), [0], "2", "6"))
    monkeypatch.setattr(escritor, "_persistir_seguro", lambda d, p, n: capturado.update(df=d) or None)
    monkeypatch.setattr(escritor, "_subir_a_drive", lambda p: None)

    res = escritor.editar_trabajo(0, "pagado", "9999", pg_id=None, clave=None)

    assert res == "Trabajo actualizado correctamente."          # no lanza excepción
    assert "pg_id no disponible" in capsys.readouterr().out      # logueó el aviso
    assert capturado["df"].iloc[0, 8] == "9999"                 # editó por posición (col PAGADO)
