"""
test_escritor.py
----------------
Pruebas de caracterización del bug P0.2 (auditoría): las operaciones de escritura
de src/escritor.py (agregar/editar/borrar trabajo) deben PRESERVAR las filas
parciales del Excel real (capturas a medias, notas, filas con solo cliente o solo
tipo de trabajo), en lugar de borrarlas al persistir el DataFrame filtrado.

El filtro "cliente Y tipo_trabajo no nulos" solo sirve para localizar los índices
que el bot muestra por WhatsApp; NO debe usarse como lo que se escribe al archivo.

Estas pruebas son herméticas: construyen un Excel sintético en tmp_path, apuntan
a él con TRABAJOS_PATH y desactivan toda subida a Drive. No tocan data/raw/ real.
"""

import pandas as pd
import pytest

import src.escritor as escritor

# Cabeceras EXACTAS del Excel de control de trabajos (mismas que escritor._COLUMNAS_TRABAJOS).
# El código de escritor opera por POSICIÓN de columna, no por nombre.
_HEADERS = [
    "ENERO", "TECNICO", "CLIENTE", "REP #",
    "DOMICILIO", "TELEFONO", "TIPO DE TRABAJO",
    "Unnamed: 7", "PAGADO", "RECIBE",
]

# Filas sintéticas. Posición 2 = CLIENTE, posición 6 = TIPO DE TRABAJO.
#   - 2 filas COMPLETAS (cliente Y tipo)  → las únicas "visibles" para el bot.
#   - 1 fila SOLO CLIENTE  (tipo nulo)    → parcial, debe sobrevivir.
#   - 1 fila VACÍA INTERMEDIA con una nota suelta en DOMICILIO → debe sobrevivir.
#   - 1 fila SOLO TIPO     (cliente nulo) → parcial, debe sobrevivir.
_FILAS = [
    ["ENERO",   "Tec1", "Cliente A",        "", "Dom A",       "111", "Instalacion",   "", "1000", "R1"],
    ["FEBRERO", "Tec2", "Cliente B parcial","", "",            "",    None,            "", "",     ""],
    [None,      None,   None,               None, "nota suelta",None, None,            None, None, None],
    ["MARZO",   "Tec3", None,               "", "",            "",    "Solo tipo",     "", "",     ""],
    ["ABRIL",   "Tec4", "Cliente C",        "", "Dom C",       "444", "Mantenimiento", "", "2000", "R4"],
]


@pytest.fixture
def excel_trabajos(tmp_path, monkeypatch):
    """
    Crea el Excel sintético, lo registra como TRABAJOS_PATH y aísla los efectos:
      - backups van a tmp_path (no a data/backups/ del repo)
      - sin DRIVE_FOLDER_ID / DRIVE_BACKUPS_FOLDER_ID → no se sube nada a Drive
    Devuelve la ruta del Excel.
    """
    path = tmp_path / "CONTROL DE INST. MINISPLIT 2026.xlsx"
    pd.DataFrame(_FILAS, columns=_HEADERS).to_excel(path, index=False)

    monkeypatch.setenv("TRABAJOS_PATH", str(path))
    monkeypatch.delenv("DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("DRIVE_BACKUPS_FOLDER_ID", raising=False)
    monkeypatch.setattr(escritor, "DATA_BACKUPS_DIR", tmp_path / "backups")
    return path


def _leer(path):
    """Lee el Excel crudo como strings (NaN para celdas vacías)."""
    return pd.read_excel(path, header=0, dtype=str)


def _clientes(df):
    return set(df["CLIENTE"].dropna())


def _tipos(df):
    return set(df["TIPO DE TRABAJO"].dropna())


# ─── agregar_trabajo ─────────────────────────────────────────────────────────

def test_agregar_preserva_filas_parciales(excel_trabajos):
    """Agregar un trabajo NO debe borrar las filas parciales existentes."""
    resultado = escritor.agregar_trabajo({
        "mes": "MAYO", "tecnico": "Tec5", "cliente": "Cliente Nuevo",
        "domicilio": "Dom N", "telefono": "555",
        "tipo_trabajo": "Reparacion", "pagado": "1500", "recibe": "R5",
    })

    df = _leer(excel_trabajos)

    # Las filas parciales (solo cliente / solo tipo / nota suelta) siguen ahí.
    assert "Cliente B parcial" in _clientes(df), "se perdió la fila solo-cliente"
    assert "Solo tipo" in _tipos(df), "se perdió la fila solo-tipo"
    assert "nota suelta" in set(df["DOMICILIO"].dropna()), "se perdió la nota suelta"

    # Las filas completas y la nueva conviven.
    assert {"Cliente A", "Cliente C", "Cliente Nuevo"} <= _clientes(df)

    # Mensaje de retorno intacto (se manda por WhatsApp tal cual).
    assert resultado == (
        "Trabajo registrado correctamente.\n"
        "Cliente Nuevo | Reparacion | $1,500.00"
    )


# ─── editar_trabajo ──────────────────────────────────────────────────────────

def test_editar_usa_indice_visible_y_preserva_parciales(excel_trabajos):
    """
    El índice del bot es posicional sobre las filas VISIBLES (cliente Y tipo).
    Visible 0 = Cliente A, visible 1 = Cliente C. Editar el visible 1 debe tocar
    a Cliente C, no a una fila parcial, y conservar todas las parciales.
    """
    resultado = escritor.editar_trabajo(1, "pagado", "9999")

    df = _leer(excel_trabajos)

    # Se editó la fila correcta (Cliente C).
    fila_c = df[df["CLIENTE"] == "Cliente C"]
    assert len(fila_c) == 1
    assert float(fila_c.iloc[0]["PAGADO"]) == 9999.0

    # Cliente A quedó intacto.
    fila_a = df[df["CLIENTE"] == "Cliente A"]
    assert float(fila_a.iloc[0]["PAGADO"]) == 1000.0

    # Parciales preservadas.
    assert "Cliente B parcial" in _clientes(df)
    assert "Solo tipo" in _tipos(df)
    assert "nota suelta" in set(df["DOMICILIO"].dropna())

    assert resultado == "Trabajo actualizado correctamente."


# ─── borrar_trabajo ──────────────────────────────────────────────────────────

def test_borrar_elimina_solo_el_visible_y_preserva_parciales(excel_trabajos):
    """
    Borrar el visible 0 (Cliente A) debe quitar SOLO esa fila y conservar las
    parciales y la otra fila completa.
    """
    resultado = escritor.borrar_trabajo(0)

    df = _leer(excel_trabajos)

    # Cliente A eliminado; Cliente C sigue.
    assert "Cliente A" not in _clientes(df)
    assert "Cliente C" in _clientes(df)

    # Parciales preservadas (el borrado fue intencional solo sobre Cliente A).
    assert "Cliente B parcial" in _clientes(df)
    assert "Solo tipo" in _tipos(df)
    assert "nota suelta" in set(df["DOMICILIO"].dropna())

    assert resultado == "Trabajo de 'Cliente A' eliminado correctamente."


# ─── guard de seguridad ──────────────────────────────────────────────────────

def test_guard_aborta_sin_escribir_si_se_perderian_filas(excel_trabajos):
    """
    Si la operación fuera a escribir menos filas de las esperadas, _persistir_seguro
    debe abortar (devolver el mensaje de error) y dejar el Excel intacto.
    """
    antes = _leer(excel_trabajos)

    # Simulamos una regresión: intentamos persistir un df recortado a 1 fila pero
    # diciendo que esperamos conservar todas.
    df_recortado = antes.iloc[:1].copy()
    msg = escritor._persistir_seguro(df_recortado, excel_trabajos, filas_esperadas=len(antes))

    assert msg == escritor._MSG_ABORTO_GUARDIA

    # El Excel no se tocó.
    despues = _leer(excel_trabajos)
    assert len(despues) == len(antes)
    assert _clientes(despues) == _clientes(antes)


# ─── dual write Postgres+Excel (USE_POSTGRES_WRITES) ─────────────────────────

_NUEVO = {
    "mes": "MAYO", "tecnico": "Tec5", "cliente": "Cliente Nuevo", "domicilio": "Dom N",
    "telefono": "555", "tipo_trabajo": "Reparacion", "pagado": "1500", "recibe": "R5",
}


def test_dual_write_apagado_no_toca_postgres(excel_trabajos, monkeypatch):
    """Con USE_POSTGRES_WRITES sin definir (default 0), ni se intenta abrir Postgres."""
    monkeypatch.delenv("USE_POSTGRES_WRITES", raising=False)
    import src.db_postgres as dbp

    def _no_llamar(*a, **k):
        raise AssertionError("no debe tocar Postgres con el flag apagado")

    monkeypatch.setattr(dbp, "get_engine", _no_llamar)
    resultado = escritor.agregar_trabajo(_NUEVO)
    assert "registrado correctamente" in resultado
    assert "Cliente Nuevo" in _clientes(_leer(excel_trabajos))


def test_dual_write_cae_a_excel_si_postgres_falla(excel_trabajos, monkeypatch):
    """Con el flag en 1 pero Postgres caído, el trabajo igual se guarda en Excel."""
    monkeypatch.setenv("USE_POSTGRES_WRITES", "1")
    import src.db_postgres as dbp

    def _boom(*a, **k):
        raise RuntimeError("Postgres caído")

    monkeypatch.setattr(dbp, "get_engine", _boom)
    resultado = escritor.agregar_trabajo(_NUEVO)
    assert "registrado correctamente" in resultado          # no propaga la excepción
    assert "Cliente Nuevo" in _clientes(_leer(excel_trabajos))  # Excel escribió igual


def test_dual_write_encendido_llama_insertar_trabajo(excel_trabajos, monkeypatch):
    """Integración del wiring (sin Postgres real): con USE_POSTGRES_WRITES=1,
    agregar_trabajo resuelve cliente/técnico a id y llama a insertar_trabajo."""
    monkeypatch.setenv("USE_POSTGRES_WRITES", "1")

    # SQLite como stand-in de Postgres, solo con las tablas que usa resolver_o_crear.
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE)"))
        c.execute(text("CREATE TABLE tecnicos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE)"))
    import src.db_postgres as dbp
    monkeypatch.setattr(dbp, "get_engine", lambda *a, **k: eng)

    # Mock de insertar_trabajo (no escribe; registra la llamada).
    import src.escritor_pg as epg
    llamadas = []
    monkeypatch.setattr(epg, "insertar_trabajo", lambda conn, datos: llamadas.append(datos) or 123)

    resultado = escritor.agregar_trabajo(_NUEVO)

    assert "registrado correctamente" in resultado
    assert len(llamadas) == 1                                # se llamó a insertar_trabajo
    assert llamadas[0]["cliente_id"] is not None             # cliente resuelto a id
    assert llamadas[0]["tecnico_id"] is not None             # técnico resuelto a id
    assert llamadas[0]["tipo_trabajo"] == "Reparacion"
    assert "Cliente Nuevo" in _clientes(_leer(excel_trabajos))  # Excel también escribió
