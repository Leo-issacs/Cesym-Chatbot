# Captura de cotizaciones por WhatsApp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capturar cotizaciones nuevas por WhatsApp, validadas, directo en `cesym_db.cotizaciones`, con escrituras atómicas diferidas al confirmar.

**Architecture:** Conexión aparte a `cesym_db` (`CESYM_DB_URL`). Lecturas de catálogo en `src/cesym_db.py`; escrituras (reciben `conn`) + orquestador en `src/cotizaciones_pg.py`. Flujo conversacional nuevo en `src/sesiones.py`, ruteado desde `src/webhook.py`. Todo lo que escribe se hace en una sola transacción al confirmar.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x (psycopg2), pytest. Tests herméticos con SQLite in-memory (`StaticPool`) y `monkeypatch`.

## Global Constraints

- Commits: Conventional Commits **en español** (`feat:`, `fix:`, `docs:`, `chore:`).
- ≤ 400 líneas de código de producción en el PR (docs y tests no cuentan).
- Todo cambio de comportamiento entra **con sus tests** en el mismo PR.
- `chatbot_db` no se toca (este flujo ni la lee). `DATABASE_URL` no se reemplaza.
- Tests herméticos: sin BD real, sin secretos, sin red. Corren en CI tal cual.
- Tablas con **nombres desnudos** (`clientes`, `sucursales`, `cotizaciones`) para que el mismo SQL corra en Postgres (search_path=public) y SQLite.
- Esquema destino ya existe (Fase 1): `clientes(rfc PK, nombre_fiscal, nombre_comercial, tipo)`, `sucursales(id PK, cliente_rfc, suc, nombre)`, `cotizaciones(id PK IDENTITY, cot_num, cliente_rfc, sucursal_id, descripcion, importe, iva_tasa, fecha, estado)`.

---

### Task 1: `cesym_db.py` — engine + lecturas de catálogo

**Files:**
- Create: `src/cesym_db.py`
- Test: `tests/test_cesym_db.py`

**Interfaces:**
- Produces:
  - `get_cesym_engine(url: str | None = None) -> Engine` (lee `CESYM_DB_URL`).
  - `buscar_clientes(texto: str, engine=None) -> list[dict]` → `[{"rfc","nombre_fiscal","nombre_comercial"}]`.
  - `listar_sucursales(cliente_rfc: str, engine=None) -> list[dict]` → `[{"id","suc","nombre"}]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cesym_db.py
"""Tests herméticos de src/cesym_db.py con SQLite in-memory (tablas desnudas que
reflejan public.clientes / public.sucursales de cesym_db)."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src import cesym_db

_DDL = [
    """CREATE TABLE clientes (
        rfc TEXT PRIMARY KEY, nombre_fiscal TEXT NOT NULL,
        nombre_comercial TEXT, tipo TEXT)""",
    """CREATE TABLE sucursales (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_rfc TEXT NOT NULL,
        suc TEXT, nombre TEXT)""",
]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
        conn.execute(text(
            "INSERT INTO clientes (rfc, nombre_fiscal, nombre_comercial, tipo) VALUES "
            "('WDM990126350','WALDOS DOLAR MART','WALDOS','empresa'),"
            "('DME860313ND7','DURA DE MEXICO','DURA','empresa')"))
        conn.execute(text(
            "INSERT INTO sucursales (cliente_rfc, suc, nombre) VALUES "
            "('WDM990126350','5208','WALDOS CENTRO')"))
    return eng


def test_buscar_por_nombre_parcial(engine):
    res = cesym_db.buscar_clientes("waldo", engine=engine)
    assert len(res) == 1 and res[0]["rfc"] == "WDM990126350"


def test_buscar_por_rfc_exacto(engine):
    res = cesym_db.buscar_clientes("dme860313nd7", engine=engine)
    assert len(res) == 1 and res[0]["nombre_comercial"] == "DURA"


def test_buscar_sin_resultados(engine):
    assert cesym_db.buscar_clientes("zzz", engine=engine) == []


def test_listar_sucursales(engine):
    sucs = cesym_db.listar_sucursales("WDM990126350", engine=engine)
    assert len(sucs) == 1 and sucs[0]["suc"] == "5208"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cesym_db.py -v`
Expected: FAIL (`ModuleNotFoundError: src.cesym_db` o `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/cesym_db.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cesym_db.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cesym_db.py tests/test_cesym_db.py
git commit -m "feat(cesym_db): conexión a cesym_db y lecturas de catálogo"
```

---

### Task 2: `cotizaciones_pg.py` — primitivas de escritura

**Files:**
- Create: `src/cotizaciones_pg.py`
- Test: `tests/test_cotizaciones_pg.py`

**Interfaces:**
- Consumes: nada de tareas previas (recibe `conn` abierto del caller).
- Produces:
  - `crear_cliente(conn, rfc, nombre_fiscal, nombre_comercial, tipo="empresa") -> str`
  - `crear_sucursal(conn, cliente_rfc, suc, nombre) -> int`
  - `insertar_cotizacion(conn, datos: dict) -> int` — `datos`: `cliente_rfc, sucursal_id, descripcion, importe, iva_tasa, fecha, estado`. Inserta, obtiene `id` (RETURNING), espeja `cot_num = str(id)`, devuelve `id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cotizaciones_pg.py
"""Tests herméticos de src/cotizaciones_pg.py con SQLite in-memory."""
import datetime as dt

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src import cotizaciones_pg as cpg

_DDL = [
    """CREATE TABLE clientes (rfc TEXT PRIMARY KEY, nombre_fiscal TEXT NOT NULL,
        nombre_comercial TEXT, tipo TEXT)""",
    """CREATE TABLE sucursales (id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_rfc TEXT NOT NULL, suc TEXT, nombre TEXT,
        UNIQUE (cliente_rfc, suc))""",
    """CREATE TABLE cotizaciones (id INTEGER PRIMARY KEY AUTOINCREMENT,
        cot_num TEXT, cliente_rfc TEXT NOT NULL, sucursal_id INTEGER,
        descripcion TEXT, importe REAL, iva_tasa REAL, fecha TEXT, estado TEXT)""",
]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return eng


def test_crear_cliente_idempotente(engine):
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "WALDOS DOLAR MART", "WALDOS")
        cpg.crear_cliente(conn, "WDM990126350", "WALDOS DOLAR MART", "WALDOS")
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
        tipo = conn.execute(text("SELECT tipo FROM clientes")).scalar()
    assert n == 1 and tipo == "empresa"


def test_crear_sucursal_devuelve_id(engine):
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "W", "WALDOS")
        sid = cpg.crear_sucursal(conn, "WDM990126350", "5208", "CENTRO")
    assert isinstance(sid, int) and sid > 0


def test_insertar_cotizacion_espeja_cot_num(engine):
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "W", "WALDOS")
        cid = cpg.insertar_cotizacion(conn, {
            "cliente_rfc": "WDM990126350", "sucursal_id": None,
            "descripcion": "Mantenimiento minisplit", "importe": 1000.0,
            "iva_tasa": 0.08, "fecha": dt.date(2026, 6, 22), "estado": "cotizada"})
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT cot_num, estado, iva_tasa FROM cotizaciones WHERE id = :i"),
            {"i": cid}).first()
    assert cid > 0 and row[0] == str(cid) and row[1] == "cotizada" and row[2] == 0.08
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cotizaciones_pg.py -v`
Expected: FAIL (`ModuleNotFoundError: src.cotizaciones_pg`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/cotizaciones_pg.py
"""
cotizaciones_pg.py
------------------
Escrituras en cesym_db para el flujo de cotizaciones. Las primitivas reciben una
conexión SQLAlchemy ya abierta y NO manejan la transacción (el caller hace
engine.begin()), igual que escritor_pg.py. `guardar_cotizacion` orquesta todo en
una sola transacción (escrituras diferidas al confirmar).
"""
import datetime as dt
import logging

from sqlalchemy import text

from src.cesym_db import get_cesym_engine

logger = logging.getLogger(__name__)


def crear_cliente(conn, rfc, nombre_fiscal, nombre_comercial, tipo="empresa") -> str:
    """Upsert idempotente de cliente por RFC. Devuelve el RFC."""
    conn.execute(
        text("""
            INSERT INTO clientes (rfc, nombre_fiscal, nombre_comercial, tipo)
            VALUES (:rfc, :nf, :nc, :tipo)
            ON CONFLICT (rfc) DO UPDATE
                SET nombre_fiscal = excluded.nombre_fiscal,
                    nombre_comercial = excluded.nombre_comercial,
                    tipo = excluded.tipo
        """),
        {"rfc": rfc, "nf": nombre_fiscal, "nc": nombre_comercial, "tipo": tipo},
    )
    return rfc


def crear_sucursal(conn, cliente_rfc, suc, nombre) -> int:
    """Crea una sucursal y devuelve su id."""
    return int(conn.execute(
        text("INSERT INTO sucursales (cliente_rfc, suc, nombre) "
             "VALUES (:r, :suc, :n) RETURNING id"),
        {"r": cliente_rfc, "suc": suc, "n": nombre},
    ).scalar_one())


def insertar_cotizacion(conn, datos: dict) -> int:
    """Inserta una cotización, espeja el número en cot_num y devuelve el id."""
    cid = int(conn.execute(
        text("""
            INSERT INTO cotizaciones
                (cliente_rfc, sucursal_id, descripcion, importe, iva_tasa, fecha, estado)
            VALUES (:cliente_rfc, :sucursal_id, :descripcion, :importe, :iva_tasa,
                    :fecha, :estado)
            RETURNING id
        """),
        datos,
    ).scalar_one())
    conn.execute(text("UPDATE cotizaciones SET cot_num = :c WHERE id = :i"),
                 {"c": str(cid), "i": cid})
    return cid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cotizaciones_pg.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cotizaciones_pg.py tests/test_cotizaciones_pg.py
git commit -m "feat(cotizaciones): primitivas de escritura en cesym_db"
```

---

### Task 3: `guardar_cotizacion` — orquestador atómico

**Files:**
- Modify: `src/cotizaciones_pg.py` (añade `guardar_cotizacion`)
- Test: `tests/test_cotizaciones_pg.py` (añade casos)

**Interfaces:**
- Consumes: `crear_cliente`, `crear_sucursal`, `insertar_cotizacion`, `get_cesym_engine`.
- Produces: `guardar_cotizacion(datos: dict) -> str`. `datos` lleva: `cliente_nuevo: bool`, `cliente_rfc`, `nombre_fiscal`, `nombre_comercial`, `nombre` (display), `sucursal_nueva: bool`, `sucursal_id: int|None`, `suc`, `sucursal_nombre`, `descripcion`, `importe: float`, `iva_tasa: float`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cotizaciones_pg.py  (añadir al final)
def test_guardar_cotizacion_cliente_nuevo_atomico(engine, monkeypatch):
    monkeypatch.setattr(cpg, "get_cesym_engine", lambda *a, **k: engine)
    datos = {
        "cliente_nuevo": True, "cliente_rfc": "OOM090327365",
        "nombre_fiscal": "OHD OPERATORS DE MEXICO", "nombre_comercial": "GENIE",
        "nombre": "GENIE", "sucursal_nueva": False, "sucursal_id": None,
        "descripcion": "Cambio de compresor", "importe": 5000.0, "iva_tasa": 0.16,
    }
    msg = cpg.guardar_cotizacion(datos)
    assert msg.startswith("Cotizacion #1 ")
    assert "GENIE" in msg and "5,800.00" in msg  # total = 5000 * 1.16
    with engine.connect() as conn:
        ncli = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
        estado = conn.execute(text("SELECT estado FROM cotizaciones")).scalar()
    assert ncli == 1 and estado == "cotizada"


def test_guardar_cotizacion_sucursal_nueva(engine, monkeypatch):
    monkeypatch.setattr(cpg, "get_cesym_engine", lambda *a, **k: engine)
    with engine.begin() as conn:
        cpg.crear_cliente(conn, "WDM990126350", "W", "WALDOS")
    datos = {
        "cliente_nuevo": False, "cliente_rfc": "WDM990126350",
        "nombre_fiscal": "W", "nombre_comercial": "WALDOS", "nombre": "WALDOS",
        "sucursal_nueva": True, "sucursal_id": None, "suc": "5208",
        "sucursal_nombre": "CENTRO",
        "descripcion": "Servicio", "importe": 100.0, "iva_tasa": 0.08,
    }
    cpg.guardar_cotizacion(datos)
    with engine.connect() as conn:
        sid = conn.execute(text("SELECT sucursal_id FROM cotizaciones")).scalar()
        suc = conn.execute(text("SELECT suc FROM sucursales WHERE id = :i"),
                           {"i": sid}).scalar()
    assert suc == "5208"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cotizaciones_pg.py -k guardar -v`
Expected: FAIL (`AttributeError: guardar_cotizacion`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/cotizaciones_pg.py  (añadir al final)
def guardar_cotizacion(datos: dict) -> str:
    """Crea cliente/sucursal nuevos (si aplica) e inserta la cotización en una
    sola transacción. fecha = hoy, estado = 'cotizada'. Devuelve el mensaje de
    confirmación con el número asignado (el id) y el total."""
    eng = get_cesym_engine()
    with eng.begin() as conn:
        if datos.get("cliente_nuevo"):
            crear_cliente(conn, datos["cliente_rfc"], datos["nombre_fiscal"],
                          datos["nombre_comercial"], "empresa")
        if datos.get("sucursal_nueva"):
            sucursal_id = crear_sucursal(conn, datos["cliente_rfc"],
                                         datos["suc"], datos["sucursal_nombre"])
        else:
            sucursal_id = datos.get("sucursal_id")
        cid = insertar_cotizacion(conn, {
            "cliente_rfc": datos["cliente_rfc"],
            "sucursal_id": sucursal_id,
            "descripcion": datos["descripcion"],
            "importe": datos["importe"],
            "iva_tasa": datos["iva_tasa"],
            "fecha": dt.date.today(),
            "estado": "cotizada",
        })
    total = datos["importe"] * (1 + datos["iva_tasa"])
    return (f"Cotizacion #{cid} registrada para {datos['nombre']}. "
            f"Total ${total:,.2f}.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cotizaciones_pg.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cotizaciones_pg.py tests/test_cotizaciones_pg.py
git commit -m "feat(cotizaciones): guardar_cotizacion atómico (cliente+sucursal+cotización)"
```

---

### Task 4: Flujo conversacional `cotizacion` en `sesiones.py`

**Files:**
- Modify: `src/sesiones.py` (helpers de validación + flujo + dispatch en `procesar`)
- Test: `tests/test_flujo_cotizacion.py`, `tests/test_validaciones_cotizacion.py`

**Interfaces:**
- Consumes: `src.cesym_db.buscar_clientes`, `src.cesym_db.listar_sucursales` (se monkeypatchean en tests).
- Produces:
  - `iniciar_cotizacion(numero: str) -> str`
  - `_procesar_cotizacion(numero, texto, sesion) -> tuple[str, dict | None]` (interno; lo llama `procesar` cuando `sesion["tipo"] == "cotizacion"`).
  - Helpers: `_normalizar_iva(texto) -> float | None`, `_parse_importe(texto) -> float | None`, `_rfc_valido(texto) -> bool`.
  - Al confirmar devuelve `(mensaje, datos)` con `datos["tipo"] == "cotizacion"` y las claves que consume `guardar_cotizacion` (Task 3).

- [ ] **Step 1: Write the failing test (validaciones)**

```python
# tests/test_validaciones_cotizacion.py
"""Validaciones puras del flujo de cotización (sin BD)."""
from src import sesiones as ses


def test_normalizar_iva():
    assert ses._normalizar_iva("") == 0.08
    assert ses._normalizar_iva("8") == 0.08
    assert ses._normalizar_iva("8%") == 0.08
    assert ses._normalizar_iva("frontera") == 0.08
    assert ses._normalizar_iva("16") == 0.16
    assert ses._normalizar_iva("16%") == 0.16
    assert ses._normalizar_iva("10") is None
    assert ses._normalizar_iva("basura") is None


def test_parse_importe():
    assert ses._parse_importe("1500") == 1500.0
    assert ses._parse_importe("$1,500.50") == 1500.50
    assert ses._parse_importe("0") is None
    assert ses._parse_importe("-5") is None
    assert ses._parse_importe("abc") is None


def test_rfc_valido():
    assert ses._rfc_valido("WDM990126350") is True       # 12 (moral)
    assert ses._rfc_valido("OOGL800309HG1") is True       # 13 (física)
    assert ses._rfc_valido("corto") is False
    assert ses._rfc_valido("CON ESPACIOS!!") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validaciones_cotizacion.py -v`
Expected: FAIL (`AttributeError` en `_normalizar_iva`).

- [ ] **Step 3: Write minimal implementation (helpers)**

```python
# src/sesiones.py  (añadir cerca de los otros helpers, después de _normalizar_pagado)
import re as _re  # si no está ya importado arriba

_IVA_8 = {"", "8", "8%", "0.08", ".08", "frontera"}
_IVA_16 = {"16", "16%", "0.16", ".16"}
_RFC_RE = _re.compile(r"^[A-ZÑ&0-9]{12,13}$")


def _normalizar_iva(texto: str) -> float | None:
    """Mapea la respuesta de IVA a 0.08 (frontera, default) o 0.16; None si inválido."""
    t = (texto or "").strip().lower()
    if t in _IVA_8:
        return 0.08
    if t in _IVA_16:
        return 0.16
    return None


def _parse_importe(texto: str) -> float | None:
    """Convierte el importe a float (quita $ y comas). > 0, si no None."""
    t = (texto or "").replace("$", "").replace(",", "").strip()
    try:
        val = float(t)
    except ValueError:
        return None
    return val if val > 0 else None


def _rfc_valido(texto: str) -> bool:
    """RFC de 12 (moral) o 13 (física) caracteres alfanuméricos."""
    return bool(_RFC_RE.match((texto or "").strip().upper()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validaciones_cotizacion.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the failing test (flujo completo)**

```python
# tests/test_flujo_cotizacion.py
"""Flujo de cotización end-to-end, hermético: catálogo cesym_db monkeypatcheado
con datos en memoria; sesiones en modo memoria (USE_POSTGRES=False)."""
import pytest

from src import sesiones as ses


@pytest.fixture
def flujo(monkeypatch):
    monkeypatch.setattr(ses, "_USE_POSTGRES", False)
    monkeypatch.setattr(ses, "_sesiones", {})
    monkeypatch.delenv("DRIVE_FOLDER_ID", raising=False)
    catalogo = {
        "clientes": [
            {"rfc": "WDM990126350", "nombre_fiscal": "WALDOS DOLAR MART",
             "nombre_comercial": "WALDOS"},
        ],
        "sucursales": {"WDM990126350": [{"id": 7, "suc": "5208", "nombre": "CENTRO"}]},
    }
    import src.cesym_db as cdb

    def _buscar(texto, engine=None):
        t = texto.lower()
        return [c for c in catalogo["clientes"]
                if t in c["nombre_comercial"].lower() or t == c["rfc"].lower()]

    monkeypatch.setattr(cdb, "buscar_clientes", _buscar)
    monkeypatch.setattr(cdb, "listar_sucursales",
                        lambda rfc, engine=None: catalogo["sucursales"].get(rfc, []))
    return ses


def test_cliente_existente_sucursal_existente(flujo):
    n = "521111"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos")               # cliente_buscar → 1 match
    flujo.procesar(n, "si")                    # confirma cliente
    flujo.procesar(n, "5208")                  # sucursal existente
    flujo.procesar(n, "Mantenimiento aire")    # descripcion
    flujo.procesar(n, "1500")                  # importe
    flujo.procesar(n, "")                       # iva default 8%
    msg, datos = flujo.procesar(n, "si")        # confirmar
    assert datos["tipo"] == "cotizacion"
    assert datos["cliente_rfc"] == "WDM990126350"
    assert datos["cliente_nuevo"] is False
    assert datos["sucursal_id"] == 7 and datos["sucursal_nueva"] is False
    assert datos["descripcion"] == "Mantenimiento aire"
    assert datos["importe"] == 1500.0 and datos["iva_tasa"] == 0.08


def test_cliente_nuevo_con_rfc(flujo):
    n = "521222"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "ferreteria lopez")      # 0 matches → crear
    flujo.procesar(n, "FLO9901011AA")          # RFC nuevo (12)
    flujo.procesar(n, "FERRETERIA LOPEZ SA")   # nombre fiscal
    flujo.procesar(n, "sin")                    # sucursal omitida
    flujo.procesar(n, "Instalacion")           # descripcion
    flujo.procesar(n, "2000")                  # importe
    msg, datos = flujo.procesar(n, "16")        # iva 16 → va directo a confirmar? no: pide confirmar
    # "16" fija iva y pasa a confirmando; confirmamos:
    msg, datos = flujo.procesar(n, "si")
    assert datos["cliente_nuevo"] is True
    assert datos["cliente_rfc"] == "FLO9901011AA"
    assert datos["nombre_fiscal"] == "FERRETERIA LOPEZ SA"
    assert datos["sucursal_id"] is None and datos["sucursal_nueva"] is False
    assert datos["iva_tasa"] == 0.16


def test_importe_invalido_repregunta(flujo):
    n = "521333"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos"); flujo.procesar(n, "si")
    flujo.procesar(n, "sin")                    # sucursal
    flujo.procesar(n, "Servicio")              # descripcion
    msg, datos = flujo.procesar(n, "abc")       # importe inválido
    assert datos is None and "importe" in msg.lower()


def test_sucursal_nueva_al_vuelo(flujo):
    n = "521444"
    flujo.iniciar_cotizacion(n)
    flujo.procesar(n, "waldos"); flujo.procesar(n, "si")
    flujo.procesar(n, "9999")                  # sucursal inexistente
    flujo.procesar(n, "PLAZA NORTE")           # nombre de la nueva sucursal
    flujo.procesar(n, "Servicio")              # descripcion
    flujo.procesar(n, "300")                   # importe
    msg, datos = flujo.procesar(n, "8")        # iva 8 → confirmar
    msg, datos = flujo.procesar(n, "si")
    assert datos["sucursal_nueva"] is True
    assert datos["suc"] == "9999" and datos["sucursal_nombre"] == "PLAZA NORTE"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_flujo_cotizacion.py -v`
Expected: FAIL (`AttributeError: iniciar_cotizacion`).

- [ ] **Step 7: Write minimal implementation (flujo)**

```python
# src/sesiones.py  (añadir tras los flujos existentes, antes de "API pública")

# ─── Flujo: cotización ──────────────────────────────────────────────────────────

def iniciar_cotizacion(numero: str) -> str:
    estado = {"tipo": "cotizacion", "paso": "cliente_buscar", "datos": {}}
    _escribir_sesion(numero, estado)
    return ("Nueva cotización.\n"
            "Escribe 'cancelar' en cualquier momento para salir.\n\n"
            "Cliente (nombre o RFC):")


def _ir_a_sucursal(numero, sesion):
    sesion["paso"] = "sucursal"
    _escribir_sesion(numero, sesion)
    return "Sucursal (código) o 'sin':"


def _ir_a_confirmar(numero, sesion):
    d = sesion["datos"]
    sesion["paso"] = "confirmando"
    _escribir_sesion(numero, sesion)
    suc = d["sucursal_nombre"] if d.get("sucursal_nueva") else (
        d.get("suc_label") or "sin")
    total = d["importe"] * (1 + d["iva_tasa"])
    return ("Confirma la cotización:\n\n"
            f"Cliente : {d['nombre']} ({d['cliente_rfc']})\n"
            f"Sucursal: {suc}\n"
            f"Trabajo : {d['descripcion']}\n"
            f"Importe : ${d['importe']:,.2f}\n"
            f"IVA     : {int(d['iva_tasa'] * 100)}%\n"
            f"Total   : ${total:,.2f}\n\n"
            "Escribe 'si' para guardar o 'no' para cancelar.")


def _procesar_cotizacion(numero, texto, sesion):
    from src import cesym_db
    paso = sesion["paso"]
    d = sesion["datos"]
    valor = texto.strip()

    if paso == "cliente_buscar":
        try:
            res = cesym_db.buscar_clientes(valor)
        except Exception:
            _borrar_sesion(numero)
            return "No pude consultar el catálogo. Intenta más tarde.", None
        if not res:
            d["_comercial"] = valor
            sesion["paso"] = "cliente_crear_rfc"
            _escribir_sesion(numero, sesion)
            return (f"No encontré '{valor}'. Para crearlo, escribe su RFC "
                    "(o 'cancelar'):"), None
        if len(res) == 1:
            d["_match"] = res[0]
            sesion["paso"] = "cliente_confirma"
            _escribir_sesion(numero, sesion)
            c = res[0]
            return (f"¿Es {c['nombre_comercial']} ({c['rfc']})? si/no"), None
        d["_matches"] = res[:9]
        sesion["paso"] = "cliente_elegir"
        _escribir_sesion(numero, sesion)
        lineas = ["Encontré varios. Elige el número:"]
        for i, c in enumerate(res[:9], 1):
            lineas.append(f"{i}. {c['nombre_comercial']} ({c['rfc']})")
        return "\n".join(lineas), None

    if paso == "cliente_confirma":
        if valor.lower() in ("si", "sí", "s", "1"):
            _fijar_cliente(d, d["_match"])
            return _ir_a_sucursal(numero, sesion), None
        sesion["paso"] = "cliente_buscar"
        _escribir_sesion(numero, sesion)
        return "De acuerdo. Cliente (nombre o RFC):", None

    if paso == "cliente_elegir":
        try:
            i = int(valor)
            c = d["_matches"][i - 1]
        except (ValueError, IndexError):
            return "Escribe el número de la lista.", None
        _fijar_cliente(d, c)
        return _ir_a_sucursal(numero, sesion), None

    if paso == "cliente_crear_rfc":
        if not _rfc_valido(valor):
            return ("RFC inválido. Deben ser 12 o 13 caracteres "
                    "(ej. WDM990126350). Inténtalo de nuevo:"), None
        d["cliente_rfc"] = valor.upper()
        sesion["paso"] = "cliente_crear_nombre"
        _escribir_sesion(numero, sesion)
        return "Nombre o razón social del cliente:", None

    if paso == "cliente_crear_nombre":
        if not valor:
            return "El nombre no puede ir vacío. Escríbelo:", None
        d["cliente_nuevo"] = True
        d["nombre_fiscal"] = valor
        d["nombre_comercial"] = d.get("_comercial") or valor
        d["nombre"] = d["nombre_comercial"]
        return _ir_a_sucursal(numero, sesion), None

    if paso == "sucursal":
        if valor.lower() in ("sin", "no", ""):
            d["sucursal_id"] = None
            d["sucursal_nueva"] = False
            sesion["paso"] = "descripcion"
            _escribir_sesion(numero, sesion)
            return "Descripción del trabajo:", None
        try:
            sucs = cesym_db.listar_sucursales(d["cliente_rfc"])
        except Exception:
            sucs = []
        existente = next((s for s in sucs if str(s["suc"]) == valor), None)
        if existente:
            d["sucursal_id"] = existente["id"]
            d["sucursal_nueva"] = False
            d["suc_label"] = f"{existente['suc']} - {existente.get('nombre') or ''}".strip()
            sesion["paso"] = "descripcion"
            _escribir_sesion(numero, sesion)
            return "Descripción del trabajo:", None
        d["_suc"] = valor
        sesion["paso"] = "sucursal_crear_nombre"
        _escribir_sesion(numero, sesion)
        return (f"La sucursal '{valor}' no existe. Escribe su nombre para crearla "
                "(o 'sin' para omitir):"), None

    if paso == "sucursal_crear_nombre":
        if valor.lower() in ("sin", "no", ""):
            d["sucursal_id"] = None
            d["sucursal_nueva"] = False
        else:
            d["sucursal_nueva"] = True
            d["suc"] = d["_suc"]
            d["sucursal_nombre"] = valor
        sesion["paso"] = "descripcion"
        _escribir_sesion(numero, sesion)
        return "Descripción del trabajo:", None

    if paso == "descripcion":
        if not valor:
            return "La descripción no puede ir vacía. Escríbela:", None
        d["descripcion"] = valor
        sesion["paso"] = "importe"
        _escribir_sesion(numero, sesion)
        return "Importe (subtotal, sin IVA):", None

    if paso == "importe":
        monto = _parse_importe(valor)
        if monto is None:
            return "Importe inválido. Escribe un número mayor que 0 (ej. 1500):", None
        d["importe"] = monto
        sesion["paso"] = "iva"
        _escribir_sesion(numero, sesion)
        return "IVA: 8% (frontera) por default; escribe 16 si aplica 16%:", None

    if paso == "iva":
        tasa = _normalizar_iva(valor)
        if tasa is None:
            return "IVA inválido. Escribe 8 o 16:", None
        d["iva_tasa"] = tasa
        return _ir_a_confirmar(numero, sesion), None

    if paso == "confirmando":
        if valor.lower() in ("si", "sí", "s", "1"):
            datos = {
                "tipo": "cotizacion",
                "cliente_nuevo": d.get("cliente_nuevo", False),
                "cliente_rfc": d["cliente_rfc"],
                "nombre_fiscal": d.get("nombre_fiscal", d.get("nombre", "")),
                "nombre_comercial": d.get("nombre_comercial", d.get("nombre", "")),
                "nombre": d["nombre"],
                "sucursal_nueva": d.get("sucursal_nueva", False),
                "sucursal_id": d.get("sucursal_id"),
                "suc": d.get("suc"),
                "sucursal_nombre": d.get("sucursal_nombre"),
                "descripcion": d["descripcion"],
                "importe": d["importe"],
                "iva_tasa": d["iva_tasa"],
            }
            _borrar_sesion(numero)
            return "Guardando...", datos
        _borrar_sesion(numero)
        return "Cotización cancelada.", None

    return "Error en el flujo. Escribe 'cancelar' e intenta de nuevo.", None


def _fijar_cliente(d: dict, c: dict) -> None:
    d["cliente_nuevo"] = False
    d["cliente_rfc"] = c["rfc"]
    d["nombre_fiscal"] = c.get("nombre_fiscal", "")
    d["nombre_comercial"] = c.get("nombre_comercial", "")
    d["nombre"] = c.get("nombre_comercial") or c.get("nombre_fiscal") or c["rfc"]
```

- [ ] **Step 8: Wire the dispatch in `procesar`**

En `src/sesiones.py`, dentro de `procesar`, añade el branch (antes del `return _procesar_agregar(...)`):

```python
    if tipo == "cotizacion":
        return _procesar_cotizacion(numero, texto, sesion)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_flujo_cotizacion.py tests/test_validaciones_cotizacion.py -v`
Expected: PASS (todos).

- [ ] **Step 10: Commit**

```bash
git add src/sesiones.py tests/test_flujo_cotizacion.py tests/test_validaciones_cotizacion.py
git commit -m "feat(sesiones): flujo de captura de cotización con validaciones"
```

---

### Task 5: Cableado en `webhook.py`

**Files:**
- Modify: `src/webhook.py` (imports, triggers, ruteo, persistencia)
- Test: `tests/test_webhook_cotizacion.py`

**Interfaces:**
- Consumes: `sesiones.iniciar_cotizacion`, `cotizaciones_pg.guardar_cotizacion`.
- Produces: ruteo de "nueva cotización"/"cotizar" → flujo; al confirmar, persiste vía `guardar_cotizacion`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_webhook_cotizacion.py
"""El webhook rutea el trigger de cotización y persiste al confirmar."""
import pytest

from src import webhook


def test_es_cotizar_reconoce_triggers():
    assert webhook._es_cotizar("nueva cotizacion") is True
    assert webhook._es_cotizar("cotizar") is True
    assert webhook._es_cotizar("nueva cotización") is True
    assert webhook._es_cotizar("agregar trabajo") is False


@pytest.mark.asyncio
async def test_procesar_mensaje_inicia_cotizacion(monkeypatch):
    monkeypatch.setattr(webhook, "tiene_sesion", lambda n: False)
    llamado = {}
    monkeypatch.setattr(webhook, "iniciar_cotizacion",
                        lambda n: llamado.setdefault("ok", True) or "Nueva cotización.")
    resp = await webhook._procesar_mensaje("521", "cotizar")
    assert llamado.get("ok") and "cotización" in resp.lower()


@pytest.mark.asyncio
async def test_confirmar_persiste_con_guardar_cotizacion(monkeypatch):
    monkeypatch.setattr(webhook, "tiene_sesion", lambda n: True)
    datos = {"tipo": "cotizacion", "nombre": "WALDOS"}
    monkeypatch.setattr(webhook, "procesar", lambda n, t: ("Guardando...", datos))
    monkeypatch.setattr(webhook, "guardar_cotizacion",
                        lambda d: "Cotizacion #1 registrada para WALDOS. Total $1,080.00.")
    monkeypatch.setattr(webhook, "registrar", lambda *a, **k: None)
    resp = await webhook._procesar_mensaje("521", "si")
    assert resp.startswith("Cotizacion #1")
```

Nota: `test_webhook_meta.py` ya usa `@pytest.mark.asyncio`; el plugin está configurado.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook_cotizacion.py -v`
Expected: FAIL (`AttributeError: _es_cotizar` / `guardar_cotizacion`).

- [ ] **Step 3: Add imports and triggers**

En `src/webhook.py`, junto a los imports de sesiones/escritor:

```python
from src.sesiones import (tiene_sesion, iniciar, iniciar_editar, iniciar_borrar,
                          procesar, cancelar, iniciar_cotizacion)
from src.cotizaciones_pg import guardar_cotizacion
```

Junto a `_TRIGGERS_AGREGAR`:

```python
_TRIGGERS_COTIZAR = ["nueva cotizacion", "nueva cotización", "cotizar",
                     "cotizacion", "cotización"]


def _es_cotizar(texto: str) -> bool:
    t = texto.lower().strip()
    if t in _TRIGGERS_COTIZAR:
        return True
    return bool(get_close_matches(t, _TRIGGERS_COTIZAR, n=1, cutoff=0.82))
```

- [ ] **Step 4: Route the trigger and persist on confirm**

En `_procesar_mensaje`, dentro del branch `if tiene_sesion(numero):`, justo antes del `else: resultado = agregar_trabajo(...)`, añade la rama de cotización:

```python
            if datos_completos.get("tipo") == "cotizacion":
                resultado = guardar_cotizacion(datos_completos)
                registrar(numero, entrada, resultado)
                return resultado
```

(colócala como primer `if` dentro del bloque `if datos_completos is not None:`, antes del manejo de "editar"/"borrar"/agregar, para no llamar `_recargar_datos()`.)

Y después de la rama de triggers de trabajo (tras `if _es_agregar_trabajo(entrada): return iniciar(numero)`), añade:

```python
    if _es_cotizar(entrada):
        return iniciar_cotizacion(numero)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_webhook_cotizacion.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run full suite (no regressions)**

Run: `pytest -q`
Expected: toda la suite en verde.

- [ ] **Step 7: Commit**

```bash
git add src/webhook.py tests/test_webhook_cotizacion.py
git commit -m "feat(webhook): ruteo y persistencia del flujo de cotización"
```

---

### Task 6: Seed del catálogo, rol least-privilege y config

**Files:**
- Create: `scripts/seed_clientes_cesym.py`
- Create: `docs/ops/cesym_app_role.sql`
- Modify: `.env.example` (añade `CESYM_DB_URL`)
- Modify: `CLAUDE.md` (fila en la tabla de variables)
- Test: `tests/test_seed_clientes.py`

**Interfaces:**
- Consumes: `cotizaciones_pg.crear_cliente`, `cesym_db.get_cesym_engine`.
- Produces: `scripts/seed_clientes_cesym.py::CLIENTES_SEED` (lista editable) y `sembrar(engine) -> int` (nº de clientes upserted).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_clientes.py
"""El seed de clientes es idempotente: correrlo dos veces deja 3 clientes."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import scripts.seed_clientes_cesym as seed


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE clientes (rfc TEXT PRIMARY KEY, nombre_fiscal TEXT NOT NULL,"
            " nombre_comercial TEXT, tipo TEXT)"))
    return eng


def test_seed_idempotente(engine):
    seed.sembrar(engine)
    n2 = seed.sembrar(engine)            # segunda corrida
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
        tipos = conn.execute(text("SELECT DISTINCT tipo FROM clientes")).scalars().all()
    assert total == 3 and n2 == 3 and tipos == ["empresa"]


def test_seed_incluye_waldos(engine):
    seed.sembrar(engine)
    with engine.connect() as conn:
        nf = conn.execute(text("SELECT nombre_fiscal FROM clientes WHERE rfc='WDM990126350'")).scalar()
    assert "WALDO" in nf
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed_clientes.py -v`
Expected: FAIL (`ModuleNotFoundError: scripts.seed_clientes_cesym`).

- [ ] **Step 3: Write the seed script**

```python
# scripts/seed_clientes_cesym.py
"""
seed_clientes_cesym.py
----------------------
Seed idempotente del catálogo cesym_db.clientes con los clientes principales.
Para agregar más, añade una tupla a CLIENTES_SEED. Correrlo de nuevo no duplica.

Uso (en el servidor, vía SSH):
    CESYM_DB_URL="postgresql://cesym_app:***@localhost:5432/cesym_db" \
        python scripts/seed_clientes_cesym.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cesym_db import get_cesym_engine
from src.cotizaciones_pg import crear_cliente

# (rfc, nombre_fiscal, nombre_comercial). Todos tipo 'empresa'.
# Razones sociales de la auditoría; se afinan al migrar los CFDI (nombre del SAT).
CLIENTES_SEED = [
    ("WDM990126350", "WALDO'S DOLAR MART DE MEXICO", "WALDOS"),
    ("DME860313ND7", "DURA DE MEXICO, S.A. DE C.V.",  "DURA"),
    ("OOM090327365", "OHD OPERATORS DE MEXICO",       "GENIE"),
]


def sembrar(engine=None) -> int:
    """Upsert idempotente de CLIENTES_SEED. Devuelve cuántos se procesaron."""
    eng = engine or get_cesym_engine()
    with eng.begin() as conn:
        for rfc, nombre_fiscal, nombre_comercial in CLIENTES_SEED:
            crear_cliente(conn, rfc, nombre_fiscal, nombre_comercial, "empresa")
    return len(CLIENTES_SEED)


if __name__ == "__main__":
    n = sembrar()
    print(f"[seed] {n} clientes sembrados/actualizados en cesym_db.clientes.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed_clientes.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Write the role SQL and config docs**

```sql
-- docs/ops/cesym_app_role.sql
-- Rol de aplicación least-privilege para que el chatbot escriba cotizaciones en
-- cesym_db. La CONTRASEÑA se define en el servidor (psql) — NUNCA en git.
-- Aplicar como superusuario:  sudo -u postgres psql -d cesym_db -f cesym_app_role.sql
-- y luego:  ALTER ROLE cesym_app PASSWORD '<definir aquí, en el server>';

-- CREATE ROLE cesym_app LOGIN;   -- descomenta si el rol no existe; fija el password aparte
GRANT CONNECT ON DATABASE cesym_db TO cesym_app;
GRANT USAGE ON SCHEMA public TO cesym_app;
GRANT SELECT, INSERT         ON clientes, sucursales TO cesym_app;
GRANT SELECT, INSERT, UPDATE ON cotizaciones         TO cesym_app;
-- IDENTITY no requiere GRANT de secuencia (a diferencia de SERIAL).
```

En `.env.example`, añade (en la sección de Postgres):

```bash
# Conexión a la BD consolidada cesym_db (Fase 3 — captura de cotizaciones).
# INDEPENDIENTE de DATABASE_URL (chatbot_db). En el servidor apunta al rol cesym_app.
CESYM_DB_URL=postgresql://cesym_app:CAMBIAME@localhost:5432/cesym_db
```

En `CLAUDE.md`, añade una fila a la tabla "Variables de entorno":

```markdown
| `CESYM_DB_URL` | — | `cesym_db.py` | Conexión a la BD consolidada `cesym_db` (cotizaciones). Aparte de `DATABASE_URL`. |
```

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: verde.

- [ ] **Step 7: Commit**

```bash
git add scripts/seed_clientes_cesym.py tests/test_seed_clientes.py \
    docs/ops/cesym_app_role.sql .env.example CLAUDE.md
git commit -m "feat(seed): catálogo de clientes en cesym_db + rol cesym_app + config"
```

---

## Cierre

- [ ] **Push y PR**

```bash
git push -u origin feat/captura-cotizaciones
gh pr create --base main --head feat/captura-cotizaciones \
  --title "feat: captura de cotizaciones por WhatsApp en cesym_db (Fase 3)" \
  --body-file docs/superpowers/specs/2026-06-22-captura-cotizaciones-design.md
```

- [ ] **Verificar CI verde** (`gh pr checks`), NO mergear (espera revisión).
- [ ] Tras revisión: aplicar `seed` y `cesym_app_role.sql` a `cesym_db` por SSH y configurar `CESYM_DB_URL` en el servicio.

## Self-Review (cobertura del spec)

- Conexión aparte `CESYM_DB_URL` → Task 1. ✔
- Seed idempotente con los 3 clientes → Task 6. ✔
- Flujo (trigger, cliente buscar/crear, sucursal opcional/crear, descripción, importe, IVA) → Task 4. ✔
- Número secuencial (id), fecha=hoy, estado='cotizada', confirma con número → Tasks 2-3. ✔
- Validaciones (importe, iva ∈ {0.08,0.16}, cliente/RFC, descripción) → Tasks 3-4. ✔
- Tests del flujo + validaciones + escritura + seed → Tasks 1-6. ✔
- Rol least-privilege + docs config → Task 6. ✔
- No tocar chatbot_db / no `_recargar_datos` para cotización → Task 5. ✔
