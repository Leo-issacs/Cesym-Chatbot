"""
db.py
-----
Define el esquema de la base de datos SQLite y las utilidades de conexión.

SQLite es un archivo local (no necesita servidor), perfecto para una PYME
que quiere datos centralizados sin infraestructura compleja.

Responsabilidades de este módulo:
  - Saber dónde vive el archivo .db
  - Abrir/cerrar conexiones de forma segura
  - Crear las tablas si no existen

Lo que NO hace este módulo:
  - Insertar datos (eso es tarea del ETL en cargar_bd.py)
  - Limpiar datos (eso es tarea de cleaner.py)
"""

import sqlite3
from pathlib import Path

# ─── Ruta del archivo de base de datos ────────────────────────────────────────
# Se guarda en data/ junto a los Excels de entrada.
# Path(__file__) apunta a src/db.py, luego subimos un nivel (.parent.parent)
# para llegar a la raíz del proyecto.
DB_PATH = Path(__file__).parent.parent / "data" / "cesym.db"


# ─── Conexión ─────────────────────────────────────────────────────────────────

def conectar() -> sqlite3.Connection:
    """
    Abre la conexión a la base de datos SQLite y la configura.

    Opciones importantes:
      - detect_types: permite que SQLite convierta automáticamente
        columnas TEXT con fechas ISO a objetos Python datetime.
      - PRAGMA foreign_keys = ON: activa la verificación de claves foráneas
        (por defecto SQLite las ignora, lo cual es peligroso).
      - row_factory: hace que cada fila sea accesible por nombre de columna
        (conn.execute("SELECT id FROM ...") retorna obj.id en lugar de obj[0]).

    Retorna:
        Una conexión lista para usar.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─── Creación del esquema ─────────────────────────────────────────────────────

# El SQL está en una constante separada para que sea fácil leerlo y
# copiarlo a una herramienta externa como DB Browser for SQLite.
SCHEMA_SQL = """
-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  TABLA: clientes                                                        │
-- │  Quién  : personas o empresas que contratan servicios.                  │
-- │  Fuente : reporteMensual_FACTURAS.xlsx + CONTROL DE INST. (futuro).     │
-- │                                                                         │
-- │  Por qué una tabla separada y no guardar el nombre directo en facturas? │
-- │  Porque el mismo cliente aparece con variantes ("TEC Y DISEÑO" /        │
-- │  "TEC Y DISEÑOS"). La tabla clientes guarda el nombre canónico (el      │
-- │  "correcto") y todas las facturas apuntan a ese ID único.               │
-- └─────────────────────────────────────────────────────────────────────────┘
CREATE TABLE IF NOT EXISTS clientes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT    NOT NULL UNIQUE,   -- nombre normalizado/canónico
    nombre_raw     TEXT,                      -- cómo aparecía originalmente
    fuente         TEXT                       -- 'FACTURAS' | 'CONTROL'
);

-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  TABLA: tecnicos                                                        │
-- │  Quién  : empleados que realizan los trabajos de instalación/servicio.  │
-- │  Fuente : CONTROL DE INST. MINISPLIT 2026.xlsx (columna TECNICO).       │
-- └─────────────────────────────────────────────────────────────────────────┘
CREATE TABLE IF NOT EXISTS tecnicos (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT    NOT NULL UNIQUE
);

-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  TABLA: facturas                                                        │
-- │  Qué   : cada factura emitida por la empresa.                           │
-- │  Fuente : reporteMensual_FACTURAS.xlsx                                  │
-- │                                                                         │
-- │  cliente_id REFERENCES clientes(id): clave foránea.                    │
-- │  Significa: "el cliente_id que pongas aquí DEBE existir en clientes".   │
-- │  SQLite te dará error si intentas insertar un ID que no existe.         │
-- │                                                                         │
-- │  Las fechas se guardan como TEXT en formato ISO 8601 (YYYY-MM-DD)       │
-- │  porque SQLite no tiene tipo DATE nativo. Este formato permite          │
-- │  ordenar y comparar fechas como si fueran texto (ej: '2026-01' < '2026-03').
-- └─────────────────────────────────────────────────────────────────────────┘
CREATE TABLE IF NOT EXISTS facturas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    folio          INTEGER NOT NULL UNIQUE,   -- número de factura (único)
    cliente_id     INTEGER REFERENCES clientes(id),
    fecha_emision  TEXT,                      -- YYYY-MM-DD
    concepto       TEXT,
    total          REAL,                      -- monto en pesos
    fecha_pago     TEXT,                      -- YYYY-MM-DD; NULL = pendiente de cobro
    cancelada      INTEGER NOT NULL DEFAULT 0 -- 0 = activa, 1 = cancelada
);

-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  TABLA: ordenes_compra                                                  │
-- │  Qué   : órdenes de compra y cotizaciones de la cartera.                │
-- │  Fuente : CARTERA AL 11032026.xlsx (ambas hojas)                        │
-- │                                                                         │
-- │  Esta tabla unifica dos conceptos del Excel:                            │
-- │    tipo='OC_EMITIDA'    → hoja "OC FACTURADO": OC ya asociada a una    │
-- │                           factura emitida (número_oc, folio, monto...). │
-- │    tipo='COT_PENDIENTE' → hoja "PTE OC 25-26": cotizaciones que         │
-- │                           esperan que el cliente emita una OC.          │
-- │                                                                         │
-- │  Guardar ambas en una sola tabla (en lugar de dos tablas separadas)     │
-- │  facilita consultas de tipo "¿cuánto dinero está en juego en total?".   │
-- └─────────────────────────────────────────────────────────────────────────┘
CREATE TABLE IF NOT EXISTS ordenes_compra (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            TEXT    NOT NULL,  -- 'OC_EMITIDA' | 'COT_PENDIENTE'

    -- Campos para tipo = 'OC_EMITIDA' (hoja OC FACTURADO):
    numero_oc       TEXT,              -- ej: 'O01-507749'
    folio_factura   INTEGER,           -- enlace a facturas.folio
    monto           REAL,              -- monto pendiente de cobro
    prioridad       TEXT,              -- 'PRIORIDAD' si el cliente lo marcó urgente
    estado          TEXT,              -- 'ACEPTADA', 'PREV ACEPTADO', vacío...
    fecha           TEXT,              -- YYYY-MM-DD

    -- Campos para tipo = 'COT_PENDIENTE' (hoja PTE OC 25-26):
    num_cotizacion  INTEGER,           -- número de cotización interna
    sucursal        INTEGER,           -- número de sucursal del cliente
    concepto        TEXT               -- descripción del servicio cotizado
);

-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  TABLA: trabajos                                                        │
-- │  Qué   : trabajos realizados a clientes fuera de contrato fijo (OC).   │
-- │  Fuente : CONTROL DE INST. MINISPLIT 2026.xlsx                          │
-- │                                                                         │
-- │  Esta tabla estará vacía al inicio porque el Excel de control solo      │
-- │  tiene los encabezados. Se llenará cuando el equipo empiece a           │
-- │  registrar los trabajos de 2026.                                        │
-- └─────────────────────────────────────────────────────────────────────────┘
CREATE TABLE IF NOT EXISTS trabajos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mes          TEXT,                         -- 'ENERO', 'FEBRERO', etc.
    tecnico_id   INTEGER REFERENCES tecnicos(id),
    cliente_id   INTEGER REFERENCES clientes(id),
    rep_num      TEXT,                         -- número de reporte interno
    domicilio    TEXT,
    telefono     TEXT,
    tipo_trabajo TEXT,
    pagado       REAL,                         -- monto cobrado; NULL = sin cobrar
    recibe       TEXT                          -- nombre de quien firma la entrega
);
"""


def crear_schema(conn: sqlite3.Connection) -> None:
    """
    Ejecuta el DDL (CREATE TABLE IF NOT EXISTS) para todas las tablas.

    IF NOT EXISTS significa que si las tablas ya existen no falla —
    es seguro llamar esta función cada vez que arranca el programa.
    """
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def limpiar_tablas(conn: sqlite3.Connection) -> None:
    """
    Borra todos los registros de todas las tablas (pero mantiene la estructura).

    Se usa cuando queremos recargar los datos desde cero sin recrear el esquema.
    El orden importa: hay que borrar primero las tablas que tienen FKs
    antes de borrar las tablas referenciadas (clientes, tecnicos).

    ⚠ ADVERTENCIA: esta operación es irreversible. Solo llamarla con --limpiar.
    """
    conn.executescript("""
        DELETE FROM trabajos;
        DELETE FROM ordenes_compra;
        DELETE FROM facturas;
        DELETE FROM clientes;
        DELETE FROM tecnicos;
        -- Reinicia los contadores de IDs automáticos
        DELETE FROM sqlite_sequence;
    """)
    conn.commit()
