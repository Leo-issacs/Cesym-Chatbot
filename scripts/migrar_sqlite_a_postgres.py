"""
migrar_sqlite_a_postgres.py
---------------------------
Migración idempotente: copia los datos de data/cesym.db a PostgreSQL.

CARACTERÍSTICAS:
  - Idempotente: re-ejecutarlo no duplica datos (ON CONFLICT DO NOTHING en todo).
  - No modifica ni borra el SQLite original — es la red de seguridad.
  - Preserva los IDs originales del SQLite para mantener las FK íntegras.
  - Resetea las secuencias SERIAL al final para que los INSERT futuros funcionen.
  - Imprime un cuadro de conteo origen vs destino al terminar para verificación.

PRERREQUISITOS:
  1. DATABASE_MIGRATION_URL (o DATABASE_URL) definida en el entorno / .env
  2. pip install sqlalchemy psycopg2-binary  (están en requirements.txt)
  3. El archivo data/cesym.db debe existir y tener datos.

USO:
  # Desde la raíz del proyecto con el venv activo:
  python -X utf8 scripts/migrar_sqlite_a_postgres.py

  # Si el .env no está cargado automáticamente:
  set DATABASE_MIGRATION_URL=postgresql://... && python -X utf8 scripts/migrar_sqlite_a_postgres.py

VERIFICACIÓN POST-MIGRACIÓN:
  El script imprime al final una tabla:
    Tabla            | SQLite | Postgres | Match
    clientes         |     17 |       17 | OK
    ...
  Si algún conteo no coincide, investiga antes de apagar el SQLite.

CUÁNDO BORRAR EL SQLITE:
  NUNCA durante v1. El SQLite es la red de seguridad. Solo cuando Postgres
  lleve semanas operativo sin problemas y tengas backups automáticos activos.
"""

import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# Permite ejecutar desde la raíz o desde scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Carga .env si existe (para desarrollo local)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv opcional; en Railway las vars ya están en el entorno

from sqlalchemy import text

from src.db_postgres import (
    SCHEMA,
    crear_schema,
    get_migration_engine,
    resetear_secuencias,
    contar_filas,
)

# ─── Configuración ─────────────────────────────────────────────────────────────

SQLITE_PATH = Path(__file__).parent.parent / "data" / "cesym.db"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ─── Conexión SQLite ───────────────────────────────────────────────────────────

def _sqlite_conectar() -> sqlite3.Connection:
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(
            f"SQLite no encontrado en: {SQLITE_PATH}\n"
            "Asegúrate de ejecutar este script desde la raíz del proyecto."
        )
    conn = sqlite3.connect(SQLITE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _contar_sqlite(conn: sqlite3.Connection) -> dict[str, int]:
    tablas = ["clientes", "tecnicos", "facturas", "ordenes_compra", "trabajos"]
    conteos = {}
    for tabla in tablas:
        try:
            conteos[tabla] = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        except Exception:
            conteos[tabla] = 0
    return conteos


# ─── Pasos de migración ────────────────────────────────────────────────────────

def migrar_clientes(sqlite_conn, pg_engine) -> tuple[int, int]:
    """
    Inserta clientes preservando el ID del SQLite para mantener las FK de facturas/trabajos.
    ON CONFLICT (id) DO NOTHING garantiza idempotencia.
    Retorna (total_origen, insertadas_nuevas).
    """
    filas = sqlite_conn.execute(
        "SELECT id, nombre, nombre_raw, fuente FROM clientes"
    ).fetchall()
    if not filas:
        return 0, 0

    nuevas = 0
    with pg_engine.connect() as conn:
        for f in filas:
            resultado = conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.clientes (id, nombre, nombre_raw, fuente)
                    VALUES (:id, :nombre, :nombre_raw, :fuente)
                    ON CONFLICT (id)     DO NOTHING
                    """
                ),
                {"id": f["id"], "nombre": f["nombre"],
                 "nombre_raw": f["nombre_raw"], "fuente": f["fuente"]},
            )
            nuevas += resultado.rowcount
        conn.commit()
    return len(filas), nuevas


def migrar_tecnicos(sqlite_conn, pg_engine) -> tuple[int, int]:
    """Inserta técnicos preservando el ID. Idempotente por ON CONFLICT (id)."""
    filas = sqlite_conn.execute(
        "SELECT id, nombre FROM tecnicos"
    ).fetchall()
    if not filas:
        return 0, 0

    nuevas = 0
    with pg_engine.connect() as conn:
        for f in filas:
            resultado = conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.tecnicos (id, nombre)
                    VALUES (:id, :nombre)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": f["id"], "nombre": f["nombre"]},
            )
            nuevas += resultado.rowcount
        conn.commit()
    return len(filas), nuevas


def migrar_facturas(sqlite_conn, pg_engine) -> tuple[int, int]:
    """
    Inserta/actualiza facturas (UPSERT por folio).
    El folio es la clave de negocio única, así que ON CONFLICT (folio) DO UPDATE
    propaga los cambios de registros ya migrados (p.ej. una fecha_pago nueva) al
    re-correr el ETL. Los IDs de cliente apuntan a los mismos IDs ya migrados.

    NOTA: Las fechas en SQLite son TEXT ('YYYY-MM-DD'); Postgres las acepta
    directamente en columnas DATE si tienen ese formato.
    """
    filas = sqlite_conn.execute(
        """
        SELECT id, folio, cliente_id, fecha_emision, concepto,
               total, fecha_pago, cancelada
        FROM facturas
        """
    ).fetchall()
    if not filas:
        return 0, 0

    nuevas = 0
    with pg_engine.connect() as conn:
        for f in filas:
            resultado = conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.facturas
                        (id, folio, cliente_id, fecha_emision, concepto,
                         total, fecha_pago, cancelada)
                    VALUES
                        (:id, :folio, :cliente_id, CAST(:fecha_emision AS DATE),
                         :concepto, :total, CAST(:fecha_pago AS DATE), :cancelada)
                    ON CONFLICT (folio) DO UPDATE SET
                        cliente_id    = EXCLUDED.cliente_id,
                        fecha_emision = EXCLUDED.fecha_emision,
                        concepto      = EXCLUDED.concepto,
                        total         = EXCLUDED.total,
                        fecha_pago    = EXCLUDED.fecha_pago,
                        cancelada     = EXCLUDED.cancelada
                    """
                ),
                {
                    "id":            f["id"],
                    "folio":         f["folio"],
                    "cliente_id":    f["cliente_id"],
                    "fecha_emision": f["fecha_emision"],
                    "concepto":      f["concepto"],
                    "total":         f["total"],
                    "fecha_pago":    f["fecha_pago"],
                    "cancelada":     f["cancelada"],
                },
            )
            nuevas += resultado.rowcount
        conn.commit()
    return len(filas), nuevas


def migrar_ordenes_compra(sqlite_conn, pg_engine) -> tuple[int, int]:
    """
    Inserta órdenes de compra preservando el ID.
    ordenes_compra no tiene clave de negocio única, por eso usamos ON CONFLICT (id).
    Si el ID ya existe en Postgres (de una ejecución anterior), se omite.
    """
    filas = sqlite_conn.execute(
        """
        SELECT id, tipo, numero_oc, folio_factura, monto, prioridad,
               estado, fecha, num_cotizacion, sucursal, concepto
        FROM ordenes_compra
        """
    ).fetchall()
    if not filas:
        return 0, 0

    nuevas = 0
    with pg_engine.connect() as conn:
        for f in filas:
            resultado = conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.ordenes_compra
                        (id, tipo, numero_oc, folio_factura, monto, prioridad,
                         estado, fecha, num_cotizacion, sucursal, concepto)
                    VALUES
                        (:id, :tipo, :numero_oc, :folio_factura, :monto, :prioridad,
                         :estado, CAST(:fecha AS DATE), :num_cotizacion, :sucursal, :concepto)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id":             f["id"],
                    "tipo":           f["tipo"],
                    "numero_oc":      f["numero_oc"],
                    "folio_factura":  f["folio_factura"],
                    "monto":          f["monto"],
                    "prioridad":      f["prioridad"],
                    "estado":         f["estado"],
                    "fecha":          f["fecha"],
                    "num_cotizacion": f["num_cotizacion"],
                    "sucursal":       f["sucursal"],
                    "concepto":       f["concepto"],
                },
            )
            nuevas += resultado.rowcount
        conn.commit()
    return len(filas), nuevas


def migrar_trabajos(sqlite_conn, pg_engine) -> tuple[int, int]:
    """
    Inserta trabajos preservando el ID.
    Los IDs de técnico y cliente apuntan a los mismos que ya migramos.
    trabajos tampoco tiene clave de negocio única → ON CONFLICT (id).
    """
    filas = sqlite_conn.execute(
        """
        SELECT id, mes, tecnico_id, cliente_id, rep_num, domicilio,
               telefono, tipo_trabajo, pagado, recibe
        FROM trabajos
        """
    ).fetchall()
    if not filas:
        return 0, 0

    nuevas = 0
    with pg_engine.connect() as conn:
        for f in filas:
            resultado = conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.trabajos
                        (id, mes, tecnico_id, cliente_id, rep_num, domicilio,
                         telefono, tipo_trabajo, pagado, recibe)
                    VALUES
                        (:id, :mes, :tecnico_id, :cliente_id, :rep_num, :domicilio,
                         :telefono, :tipo_trabajo, :pagado, :recibe)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id":          f["id"],
                    "mes":         f["mes"],
                    "tecnico_id":  f["tecnico_id"],
                    "cliente_id":  f["cliente_id"],
                    "rep_num":     f["rep_num"],
                    "domicilio":   f["domicilio"],
                    "telefono":    f["telefono"],
                    "tipo_trabajo":f["tipo_trabajo"],
                    "pagado":      f["pagado"],
                    "recibe":      f["recibe"],
                },
            )
            nuevas += resultado.rowcount
        conn.commit()
    return len(filas), nuevas


# ─── Reporte de verificación ───────────────────────────────────────────────────

def imprimir_reporte(
    conteos_sqlite: dict[str, int],
    conteos_pg: dict[str, int],
    resultados: dict[str, tuple[int, int]],
    duracion_seg: float,
) -> bool:
    """
    Imprime el cuadro de verificación. Retorna True si todo coincide.
    """
    sep = "─" * 62
    print()
    print("=" * 62)
    print("  VERIFICACIÓN DE MIGRACIÓN — CESYM CHATBOT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)
    print()
    print(f"  {'Tabla':<20} {'SQLite':>8} {'Postgres':>9} {'Nuevas':>7}  {'Estado':>6}")
    print(f"  {sep}")

    todo_ok = True
    tablas = ["clientes", "tecnicos", "facturas", "ordenes_compra", "trabajos"]
    for tabla in tablas:
        orig = conteos_sqlite.get(tabla, 0)
        dest = conteos_pg.get(tabla, 0)
        nuevas = resultados.get(tabla, (0, 0))[1]
        estado = "OK" if orig == dest else "DIFF"
        if estado != "OK":
            todo_ok = False
        print(f"  {tabla:<20} {orig:>8} {dest:>9} {nuevas:>7}  {estado:>6}")

    print()
    print(sep)
    if todo_ok:
        print("  Todos los conteos coinciden. Migración exitosa.")
    else:
        print("  ADVERTENCIA: algunos conteos no coinciden.")
        print("  Revisa los errores arriba e investiga antes de continuar.")
    print(f"  Tiempo total: {duracion_seg:.1f}s")
    print()
    return todo_ok


# ─── Pipeline principal ────────────────────────────────────────────────────────

def main():
    inicio = datetime.now()

    print()
    print("=" * 62)
    print("  MIGRACIÓN SQLite → PostgreSQL — CESYM CHATBOT")
    print("  NO se modifica ni borra el SQLite original.")
    print("=" * 62)

    # ── Paso 1: Conectar a SQLite ────────────────────────────────
    print()
    print("[1/5] Conectando a SQLite...")
    sqlite_conn = _sqlite_conectar()
    conteos_sqlite = _contar_sqlite(sqlite_conn)
    for tabla, n in conteos_sqlite.items():
        print(f"  {tabla:<20}: {n} filas en SQLite")

    # ── Paso 2: Crear schema en Postgres ─────────────────────────
    print()
    print("[2/5] Verificando schema 'chatbot' en Postgres...")
    pg_engine = get_migration_engine()
    crear_schema(pg_engine)

    # ── Paso 3: Migrar tablas ─────────────────────────────────────
    print()
    print("[3/5] Migrando tablas (orden respeta FK)...")
    resultados: dict[str, tuple[int, int]] = {}

    print("  → clientes...")
    resultados["clientes"] = migrar_clientes(sqlite_conn, pg_engine)
    print(f"     {resultados['clientes'][0]} origen | {resultados['clientes'][1]} nuevas")

    print("  → tecnicos...")
    resultados["tecnicos"] = migrar_tecnicos(sqlite_conn, pg_engine)
    print(f"     {resultados['tecnicos'][0]} origen | {resultados['tecnicos'][1]} nuevas")

    print("  → facturas...")
    resultados["facturas"] = migrar_facturas(sqlite_conn, pg_engine)
    print(f"     {resultados['facturas'][0]} origen | {resultados['facturas'][1]} nuevas")

    print("  → ordenes_compra...")
    resultados["ordenes_compra"] = migrar_ordenes_compra(sqlite_conn, pg_engine)
    print(f"     {resultados['ordenes_compra'][0]} origen | {resultados['ordenes_compra'][1]} nuevas")

    print("  → trabajos...")
    resultados["trabajos"] = migrar_trabajos(sqlite_conn, pg_engine)
    print(f"     {resultados['trabajos'][0]} origen | {resultados['trabajos'][1]} nuevas")

    # ── Paso 4: Resetear secuencias SERIAL ───────────────────────
    print()
    print("[4/5] Reseteando secuencias SERIAL...")
    resetear_secuencias(pg_engine)

    # ── Paso 5: Verificar conteos ─────────────────────────────────
    print()
    print("[5/5] Verificando conteos...")
    conteos_pg = contar_filas(pg_engine)
    sqlite_conn.close()

    duracion = (datetime.now() - inicio).total_seconds()
    ok = imprimir_reporte(conteos_sqlite, conteos_pg, resultados, duracion)

    if not ok:
        print("  PRÓXIMOS PASOS: investiga las diferencias antes de activar Postgres.")
    else:
        print("  PRÓXIMOS PASOS:")
        print("  1. Configura DATABASE_URL en Railway con la URL de Supabase/Railway Postgres.")
        print("  2. Agrega USE_POSTGRES_SESSIONS=1 cuando estés listo para migrar sesiones.")
        print("  3. El ETL y el bot siguen usando SQLite hasta que conectes el resto de módulos.")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
