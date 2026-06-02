"""
cargar_bd.py
------------
Pipeline ETL completo que carga los 3 archivos Excel en la BD SQLite central.

ETL significa Extract → Transform → Load (Extraer → Transformar → Cargar).
Cada etapa tiene una responsabilidad clara para que sea fácil de depurar.

Flujo completo:
  1. EXTRAER   → leer los Excel RAW con loader.py (sin modificarlos)
  2. TRANSFORMAR → limpiar y normalizar con cleaner.py
  3. NORMALIZAR → agrupar nombres de clientes similares con fuzzy matching
  4. CARGAR    → insertar en SQLite en el orden correcto (respetar FKs)
  5. REPORTAR  → mostrar conteos, fusiones y advertencias en consola

Uso:
    python -X utf8 scripts/cargar_bd.py            # carga incremental
    python -X utf8 scripts/cargar_bd.py --limpiar  # borra todo y recarga

La base de datos se guarda en: data/cesym.db
"""

import sys
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

# El flag -X utf8 (o esta línea) evita errores de codificación en Windows
# cuando se imprime con tildes y caracteres especiales.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Permitir importar desde la raíz del proyecto aunque ejecutemos desde scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Módulos propios del proyecto
from src.loader import load_facturado, load_pendiente, load_facturas_mensual, load_trabajos
from src.cleaner import clean_facturado, clean_pendiente, clean_facturas_mensual, clean_trabajos
from src.db import conectar, crear_schema, limpiar_tablas

# fuzzywuzzy para normalizar nombres de clientes
# "process" tiene las funciones de alto nivel (buscar el más similar, deduplicar)
# "fuzz" tiene las funciones de bajo nivel (calcular el % de similitud entre dos strings)
from fuzzywuzzy import fuzz, process


# ══════════════════════════════════════════════════════════════════════════════
# PASO 1 — EXTRACCIÓN
# Lee cada Excel sin tocarlo. Los datos llegan "sucios" (espacios, fechas raras,
# filas vacías). Eso se resuelve en el paso siguiente.
# ══════════════════════════════════════════════════════════════════════════════

def extraer() -> tuple[dict, list[str]]:
    """
    Carga los 3 archivos Excel y devuelve los DataFrames RAW.

    Retorna:
        raw   : dict con claves 'facturado', 'pendiente', 'facturas', 'trabajos'
        errores: lista de mensajes de error (archivos no encontrados, etc.)
    """
    raw = {}
    errores = []

    # Los try/except individuales permiten continuar aunque falte un archivo.
    # Así el pipeline no falla si, por ejemplo, el CONTROL sigue vacío.

    try:
        raw["facturado"] = load_facturado()
    except FileNotFoundError as e:
        errores.append(f"CARTERA no encontrado: {e}")
        raw["facturado"] = pd.DataFrame()

    try:
        raw["pendiente"] = load_pendiente()
    except FileNotFoundError as e:
        errores.append(f"PTE OC no encontrado: {e}")
        raw["pendiente"] = pd.DataFrame()

    try:
        raw["facturas"] = load_facturas_mensual()
    except FileNotFoundError as e:
        errores.append(f"FACTURAS no encontrado: {e}")
        raw["facturas"] = pd.DataFrame()

    try:
        raw["trabajos"] = load_trabajos()
    except FileNotFoundError as e:
        errores.append(f"CONTROL no encontrado (se omite): {e}")
        raw["trabajos"] = pd.DataFrame()

    return raw, errores


# ══════════════════════════════════════════════════════════════════════════════
# PASO 2 — TRANSFORMACIÓN
# Llama a cleaner.py para normalizar tipos, fechas, montos y eliminar
# filas inválidas. Los DataFrames resultantes ya tienen columnas con nombres
# consistentes y tipos correctos (float, datetime, int...).
# ══════════════════════════════════════════════════════════════════════════════

def transformar(raw: dict) -> tuple[dict, list[str]]:
    """
    Limpia cada dataset crudo y acumula advertencias de calidad.

    Retorna:
        limpio     : dict con los mismos datasets pero ya limpios
        advertencias: lista de mensajes sobre inconsistencias encontradas
    """
    limpio = {}
    advertencias = []

    # Cada función de cleaner retorna (DataFrame, [advertencias])
    if not raw["facturado"].empty:
        df, adv = clean_facturado(raw["facturado"])
        limpio["facturado"] = df
        advertencias.extend(f"[CARTERA-OC] {a}" for a in adv)
    else:
        limpio["facturado"] = pd.DataFrame()

    if not raw["pendiente"].empty:
        df, adv = clean_pendiente(raw["pendiente"])
        limpio["pendiente"] = df
        advertencias.extend(f"[CARTERA-PTE] {a}" for a in adv)
    else:
        limpio["pendiente"] = pd.DataFrame()

    if not raw["facturas"].empty:
        df, adv = clean_facturas_mensual(raw["facturas"])
        limpio["facturas"] = df
        advertencias.extend(f"[FACTURAS] {a}" for a in adv)
    else:
        limpio["facturas"] = pd.DataFrame()

    if not raw["trabajos"].empty:
        df, adv = clean_trabajos(raw["trabajos"])
        limpio["trabajos"] = df
        advertencias.extend(f"[CONTROL] {a}" for a in adv)
    else:
        limpio["trabajos"] = pd.DataFrame()

    return limpio, advertencias


# ══════════════════════════════════════════════════════════════════════════════
# PASO 3 — NORMALIZACIÓN DE CLIENTES (fuzzy matching)
# El problema: el mismo cliente puede aparecer escrito de formas distintas
# en distintos archivos (o incluso en el mismo archivo):
#   "TEC Y DISEÑO"  vs  "TEC Y DISEÑOS"  → son el mismo cliente
#   "WALDOS"        vs  "WALDOS"          → igual, sin problema
#
# Solución: comparamos todos los nombres entre sí usando fuzz.token_sort_ratio,
# que divide el string en palabras, las ordena alfabéticamente y luego calcula
# qué tan similares son. Así "DISEÑO TEC Y" == "TEC Y DISEÑO".
#
# Si la similitud >= umbral (85%), los agrupamos y elegimos el canónico
# (el nombre más frecuente del grupo, que asumimos el "correcto").
# ══════════════════════════════════════════════════════════════════════════════

def construir_mapa_clientes(
    nombres: list[str],
    umbral: int = 85,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """
    Agrupa nombres de clientes similares y elige un nombre canónico por grupo.

    Parámetros:
        nombres : lista con todos los nombres (puede tener duplicados)
        umbral  : similitud mínima (0-100) para considerar dos nombres iguales

    Retorna:
        mapa    : dict {nombre_original_upper: nombre_canonico}
        fusiones: lista de (variante_eliminada, nombre_canonico) para el reporte

    Ejemplo de resultado:
        mapa = {
            "TEC Y DISEÑO": "TEC Y DISEÑOS",
            "TEC Y DISEÑOS": "TEC Y DISEÑOS",
            "WALDOS": "WALDOS",
        }
    """
    # Contar frecuencias: el nombre más frecuente gana como canónico
    contador = Counter(
        n.strip().upper()
        for n in nombres
        if isinstance(n, str) and n.strip()
    )
    # Ordenamos para que el algoritmo sea determinista entre ejecuciones
    unicos = sorted(contador.keys())

    mapa: dict[str, str] = {}
    fusiones: list[tuple[str, str]] = []
    ya_asignados: set[str] = set()

    for nombre in unicos:
        if nombre in ya_asignados:
            continue

        # process.extractBests devuelve todos los nombres con similitud >= score_cutoff.
        # Retorna lista de (string_encontrado, score).
        similares_con_score = process.extractBests(
            nombre,
            unicos,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=umbral,
        )
        grupo = [s[0] for s in similares_con_score]

        # Elegir canónico: el que aparece más veces en los datos originales.
        # En caso de empate en frecuencia, el nombre más corto (suele ser el oficial).
        canonico = max(grupo, key=lambda n: (contador[n], -len(n)))

        for variante in grupo:
            mapa[variante] = canonico
            ya_asignados.add(variante)
            if variante != canonico:
                fusiones.append((variante, canonico))

    return mapa, fusiones


# ══════════════════════════════════════════════════════════════════════════════
# PASO 4 — CARGA EN SQLITE
# Insertamos en el orden que respeta las claves foráneas:
#   1. tecnicos   (no depende de nada)
#   2. clientes   (no depende de nada)
#   3. facturas   (depende de clientes)
#   4. ordenes_compra (depende de facturas.folio para el link)
#   5. trabajos   (depende de clientes y tecnicos)
# ══════════════════════════════════════════════════════════════════════════════

def _fecha_a_str(fecha) -> str | None:
    """
    Convierte una fecha (pandas Timestamp, datetime, string o NaT) a 'YYYY-MM-DD'.
    Retorna None si el valor está vacío o no es válido.

    SQLite almacena fechas como TEXT en este formato. Esto permite comparar
    fechas como strings ('2026-01' < '2026-12') y convierte bien a SQL DATE.
    """
    if fecha is None or (isinstance(fecha, float) and pd.isna(fecha)):
        return None
    try:
        ts = pd.Timestamp(fecha)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return None


def cargar_tecnicos(conn, trabajos: pd.DataFrame) -> dict[str, int]:
    """
    Inserta los técnicos únicos y retorna {nombre: id} para usarlos en trabajos.

    INSERT OR IGNORE: si el técnico ya existe (misma clave UNIQUE), lo omite
    sin fallar. Así es seguro correr el ETL varias veces.
    """
    mapa_id: dict[str, int] = {}

    if trabajos.empty:
        return mapa_id

    nombres_unicos = (
        trabajos["tecnico"]
        .dropna()
        .str.strip()
        .str.upper()
        .unique()
    )

    for nombre in nombres_unicos:
        if not nombre or nombre in ("NAN", ""):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO tecnicos (nombre) VALUES (?)",
            (nombre,),
        )

    conn.commit()

    # Leer los IDs que quedaron en la BD (incluye los que ya existían)
    for row in conn.execute("SELECT id, nombre FROM tecnicos"):
        mapa_id[row["nombre"]] = row["id"]

    return mapa_id


def cargar_clientes(
    conn,
    facturas: pd.DataFrame,
    trabajos: pd.DataFrame,
    umbral_fuzzy: int = 85,
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """
    Normaliza y carga los clientes de todas las fuentes.

    Proceso:
      1. Recopilar todos los nombres de todas las fuentes
      2. Aplicar fuzzy matching para agrupar variantes
      3. Insertar el nombre canónico en la tabla clientes
      4. Retornar {nombre_upper: cliente_id} para usarlo en facturas y trabajos

    Retorna:
        mapa_id  : {nombre_original_upper: id_en_bd}
        fusiones : lista de (variante, canonico) para el reporte
    """
    todos_los_nombres: list[str] = []

    if not facturas.empty:
        todos_los_nombres.extend(facturas["cliente"].dropna().tolist())

    if not trabajos.empty:
        todos_los_nombres.extend(trabajos["cliente"].dropna().tolist())

    if not todos_los_nombres:
        return {}, []

    # Construir el mapa: variante → canónico
    mapa_canonico, fusiones = construir_mapa_clientes(todos_los_nombres, umbral_fuzzy)

    # Insertar solo los nombres canónicos (uno por cliente real)
    canonicos_unicos = set(mapa_canonico.values())
    for canonico in sorted(canonicos_unicos):
        # nombre_raw: guardar todas las variantes que se fusionaron en este canónico
        variantes = [v for v, c in mapa_canonico.items() if c == canonico and v != canonico]
        nombre_raw = canonico if not variantes else f"{canonico} ({', '.join(variantes)})"
        conn.execute(
            "INSERT OR IGNORE INTO clientes (nombre, nombre_raw, fuente) VALUES (?, ?, ?)",
            (canonico, nombre_raw, "FACTURAS"),
        )

    conn.commit()

    # Leer IDs de la BD
    mapa_id: dict[str, int] = {}
    for row in conn.execute("SELECT id, nombre FROM clientes"):
        mapa_id[row["nombre"]] = row["id"]

    # El mapa_id necesita mapear el nombre ORIGINAL (variante) → id del canónico
    # Ej: "TEC Y DISEÑO" → id del canónico "TEC Y DISEÑOS"
    mapa_variante_a_id: dict[str, int] = {}
    for variante_upper, canonico in mapa_canonico.items():
        if canonico in mapa_id:
            mapa_variante_a_id[variante_upper] = mapa_id[canonico]

    return mapa_variante_a_id, fusiones


def cargar_facturas(
    conn,
    facturas: pd.DataFrame,
    mapa_clientes: dict[str, int],
) -> tuple[int, list[str]]:
    """
    Inserta las facturas del reporte mensual.

    Busca el cliente_id usando el nombre normalizado (upper + strip).
    Si el cliente no se encuentra en el mapa, inserta la factura con cliente_id = NULL
    y registra una advertencia (así no perdemos datos).

    Retorna:
        insertadas : cantidad de filas insertadas
        errores    : lista de mensajes de error por fila
    """
    insertadas = 0
    errores: list[str] = []

    for _, fila in facturas.iterrows():
        cliente_key = str(fila.get("cliente", "")).strip().upper()
        cliente_id = mapa_clientes.get(cliente_key)

        if not cliente_id and cliente_key:
            errores.append(f"Factura {fila['folio']}: cliente '{cliente_key}' no encontrado en mapa")

        try:
            conn.execute(
                """INSERT OR IGNORE INTO facturas
                   (folio, cliente_id, fecha_emision, concepto, total, fecha_pago, cancelada)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    int(fila["folio"]),
                    cliente_id,
                    _fecha_a_str(fila.get("fecha")),
                    str(fila.get("concepto", "")).strip() or None,
                    float(fila["total"]) if pd.notna(fila.get("total")) else None,
                    _fecha_a_str(fila.get("fecha_pago")),
                ),
            )
            insertadas += 1
        except Exception as e:
            errores.append(f"Factura {fila.get('folio', '?')}: {e}")

    conn.commit()
    return insertadas, errores


def cargar_ordenes_compra(
    conn,
    facturado: pd.DataFrame,
    pendiente: pd.DataFrame,
) -> tuple[int, int, list[str]]:
    """
    Inserta las órdenes de compra de ambas hojas del Excel de cartera.

    Hoja OC FACTURADO → tipo = 'OC_EMITIDA'
    Hoja PTE OC       → tipo = 'COT_PENDIENTE'

    Retorna:
        n_emitidas   : cantidad de OC emitidas insertadas
        n_pendientes : cantidad de cotizaciones pendientes insertadas
        errores      : lista de mensajes de error
    """
    n_emitidas = 0
    n_pendientes = 0
    errores: list[str] = []

    # OC EMITIDAS (hoja OC FACTURADO)
    for _, fila in facturado.iterrows():
        try:
            conn.execute(
                """INSERT INTO ordenes_compra
                   (tipo, numero_oc, folio_factura, monto, prioridad, estado, fecha)
                   VALUES ('OC_EMITIDA', ?, ?, ?, ?, ?, ?)""",
                (
                    str(fila.get("oc", "")).strip() or None,
                    int(fila["factura"]) if pd.notna(fila.get("factura")) else None,
                    float(fila["monto_actual"]) if pd.notna(fila.get("monto_actual")) else None,
                    str(fila.get("prioridad", "")).strip() or None,
                    str(fila.get("estado", "")).strip() or None,
                    _fecha_a_str(fila.get("fecha")),
                ),
            )
            n_emitidas += 1
        except Exception as e:
            errores.append(f"OC {fila.get('oc', '?')}: {e}")

    # COTIZACIONES PENDIENTES (hoja PTE OC 25-26)
    for _, fila in pendiente.iterrows():
        try:
            conn.execute(
                """INSERT INTO ordenes_compra
                   (tipo, num_cotizacion, sucursal, monto, concepto)
                   VALUES ('COT_PENDIENTE', ?, ?, ?, ?)""",
                (
                    int(fila["cot"]) if pd.notna(fila.get("cot")) else None,
                    int(fila["suc"]) if pd.notna(fila.get("suc")) else None,
                    float(fila["importe"]) if pd.notna(fila.get("importe")) else None,
                    str(fila.get("concepto", "")).strip() or None,
                ),
            )
            n_pendientes += 1
        except Exception as e:
            errores.append(f"COT {fila.get('cot', '?')}: {e}")

    conn.commit()
    return n_emitidas, n_pendientes, errores


def cargar_trabajos(
    conn,
    trabajos: pd.DataFrame,
    mapa_clientes: dict[str, int],
    mapa_tecnicos: dict[str, int],
) -> tuple[int, list[str]]:
    """
    Inserta los trabajos del control de instalaciones.

    Busca los IDs de cliente y técnico en sus respectivos mapas.
    Si no se encuentra alguno, inserta con NULL y registra advertencia.

    Retorna:
        insertados : cantidad de filas insertadas
        errores    : lista de mensajes de error
    """
    insertados = 0
    errores: list[str] = []

    if trabajos.empty:
        return 0, []

    for _, fila in trabajos.iterrows():
        tecnico_key = str(fila.get("tecnico", "")).strip().upper()
        cliente_key = str(fila.get("cliente", "")).strip().upper()

        tecnico_id = mapa_tecnicos.get(tecnico_key)
        cliente_id = mapa_clientes.get(cliente_key)

        if not tecnico_id and tecnico_key:
            errores.append(f"Trabajo rep {fila.get('rep_num','?')}: técnico '{tecnico_key}' no encontrado")
        if not cliente_id and cliente_key:
            errores.append(f"Trabajo rep {fila.get('rep_num','?')}: cliente '{cliente_key}' no encontrado")

        try:
            conn.execute(
                """INSERT INTO trabajos
                   (mes, tecnico_id, cliente_id, rep_num, domicilio, telefono,
                    tipo_trabajo, pagado, recibe)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(fila.get("mes", "")).strip() or None,
                    tecnico_id,
                    cliente_id,
                    str(fila.get("rep_num", "")).strip() or None,
                    str(fila.get("domicilio", "")).strip() or None,
                    str(fila.get("telefono", "")).strip() or None,
                    str(fila.get("tipo_trabajo", "")).strip() or None,
                    float(fila["pagado"]) if pd.notna(fila.get("pagado")) else None,
                    str(fila.get("recibe", "")).strip() or None,
                ),
            )
            insertados += 1
        except Exception as e:
            errores.append(f"Trabajo rep {fila.get('rep_num','?')}: {e}")

    conn.commit()
    return insertados, errores


# ══════════════════════════════════════════════════════════════════════════════
# PASO 5 — REPORTE EN CONSOLA
# ══════════════════════════════════════════════════════════════════════════════

def imprimir_reporte(
    conteos: dict,
    fusiones: list[tuple[str, str]],
    advertencias: list[str],
    errores_etl: list[str],
    errores_extraccion: list[str],
    duracion_seg: float,
) -> None:
    """
    Imprime un resumen estructurado de la ejecución del ETL.
    """
    sep = "─" * 52

    print()
    print("=" * 52)
    print("  REPORTE DE CARGA — CESYM BD")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 52)

    # ── Registros por tabla ──────────────────────────────
    print()
    print("REGISTROS CARGADOS POR TABLA")
    print(sep)
    print(f"  {'clientes':<20}: {conteos.get('clientes', 0):>5} registros")
    print(f"  {'tecnicos':<20}: {conteos.get('tecnicos', 0):>5} registros")
    print(f"  {'facturas':<20}: {conteos.get('facturas', 0):>5} registros")
    print(f"  {'ordenes_compra':<20}: {conteos.get('oc_emitidas', 0) + conteos.get('oc_pendientes', 0):>5} registros")
    print(f"    {'→ OC emitidas':<18}: {conteos.get('oc_emitidas', 0):>5}")
    print(f"    {'→ Cot. pendientes':<18}: {conteos.get('oc_pendientes', 0):>5}")
    print(f"  {'trabajos':<20}: {conteos.get('trabajos', 0):>5} registros")

    # ── Normalización fuzzy ──────────────────────────────
    print()
    print("NORMALIZACION DE CLIENTES (fuzzy matching)")
    print(sep)
    n_fusiones = len(fusiones)
    n_total = conteos.get("clientes", 0) + n_fusiones
    print(f"  Nombres únicos detectados: {n_total}")
    print(f"  Clientes normalizados    : {conteos.get('clientes', 0)}")
    print(f"  Fusiones aplicadas       : {n_fusiones}")
    if fusiones:
        for variante, canonico in fusiones:
            print(f"    \"{variante}\"  →  \"{canonico}\"")
    else:
        print("    (ninguna — todos los nombres eran únicos)")

    # ── Advertencias de calidad de datos ────────────────
    if advertencias:
        print()
        print(f"ADVERTENCIAS DE CALIDAD DE DATOS ({len(advertencias)})")
        print(sep)
        for adv in advertencias:
            print(f"  ! {adv}")

    # ── Errores de extracción ────────────────────────────
    if errores_extraccion:
        print()
        print(f"ERRORES DE EXTRACCION ({len(errores_extraccion)})")
        print(sep)
        for err in errores_extraccion:
            print(f"  X {err}")

    # ── Errores durante la carga ─────────────────────────
    todos_errores_etl = [e for grupo in errores_etl for e in (grupo if isinstance(grupo, list) else [grupo])]
    if todos_errores_etl:
        print()
        print(f"ERRORES DURANTE LA CARGA ({len(todos_errores_etl)})")
        print(sep)
        for err in todos_errores_etl[:20]:   # limitar a 20 para no saturar la consola
            print(f"  X {err}")
        if len(todos_errores_etl) > 20:
            print(f"  ... y {len(todos_errores_etl) - 20} error(es) más.")

    # ── Resumen final ────────────────────────────────────
    print()
    print(sep)
    total_errores = len(todos_errores_etl) + len(errores_extraccion)
    estado = "OK" if total_errores == 0 else f"CON {total_errores} ERROR(ES)"
    print(f"  ETL completado en {duracion_seg:.1f}s — {estado}")
    print(f"  Base de datos: data/cesym.db")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# Orquesta todos los pasos en orden y recopila las métricas para el reporte.
# ══════════════════════════════════════════════════════════════════════════════

def main():
    inicio = datetime.now()

    # ── Argumentos de línea de comandos ─────────────────
    parser = argparse.ArgumentParser(description="ETL: carga los Excel en la BD SQLite.")
    parser.add_argument(
        "--limpiar",
        action="store_true",
        help="Borra todos los datos existentes antes de cargar (recarga completa).",
    )
    parser.add_argument(
        "--umbral-fuzzy",
        type=int,
        default=85,
        help="Similitud mínima (0-100) para fusionar nombres de clientes. Default: 85.",
    )
    args = parser.parse_args()

    print()
    print("=" * 52)
    print("  PIPELINE ETL — CESYM HVAC")
    print("  Cargando Excel → SQLite")
    print("=" * 52)

    # ── Conectar y preparar la BD ────────────────────────
    print()
    print("[BD] Conectando a data/cesym.db...")
    conn = conectar()
    crear_schema(conn)

    if args.limpiar:
        print("[BD] --limpiar: borrando datos anteriores...")
        limpiar_tablas(conn)

    # ── Paso 1: Extracción ───────────────────────────────
    print()
    print("[1/4] EXTRACCION (leyendo archivos Excel)...")
    raw, errores_extraccion = extraer()
    for nombre, df in raw.items():
        estado = f"{len(df)} filas" if not df.empty else "sin datos"
        print(f"  {nombre:<12}: {estado}")

    # ── Paso 2: Transformación ───────────────────────────
    print()
    print("[2/4] TRANSFORMACION (limpiando y normalizando)...")
    limpio, advertencias = transformar(raw)
    for nombre, df in limpio.items():
        print(f"  {nombre:<12}: {len(df)} filas limpias")

    # ── Paso 3: Normalización de clientes ───────────────
    print()
    print(f"[3/4] NORMALIZACION DE CLIENTES (umbral fuzzy={args.umbral_fuzzy}%)...")

    # Primero los técnicos (son más simples, no necesitan fuzzy)
    mapa_tecnicos = cargar_tecnicos(conn, limpio["trabajos"])
    print(f"  tecnicos cargados   : {len(mapa_tecnicos)}")

    # Luego clientes con fuzzy matching
    mapa_clientes, fusiones = cargar_clientes(
        conn, limpio["facturas"], limpio["trabajos"], args.umbral_fuzzy
    )
    n_clientes = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    print(f"  clientes cargados   : {n_clientes}")
    if fusiones:
        print(f"  fusiones aplicadas  : {len(fusiones)}")
        for variante, canonico in fusiones:
            print(f"    \"{variante}\"  →  \"{canonico}\"")

    # ── Paso 4: Carga en SQLite ──────────────────────────
    print()
    print("[4/4] CARGA EN SQLITE...")

    n_facturas, err_facturas = cargar_facturas(conn, limpio["facturas"], mapa_clientes)
    print(f"  facturas cargadas   : {n_facturas}")

    n_emitidas, n_pendientes, err_oc = cargar_ordenes_compra(
        conn, limpio["facturado"], limpio["pendiente"]
    )
    print(f"  ordenes_compra      : {n_emitidas + n_pendientes}  ({n_emitidas} OC + {n_pendientes} cotizaciones)")

    n_trabajos, err_trabajos = cargar_trabajos(
        conn, limpio["trabajos"], mapa_clientes, mapa_tecnicos
    )
    print(f"  trabajos cargados   : {n_trabajos}")

    # ── Cerrar conexión ──────────────────────────────────
    conn.close()

    # ── Paso 5: Reporte ──────────────────────────────────
    duracion = (datetime.now() - inicio).total_seconds()

    conteos = {
        "clientes": n_clientes,
        "tecnicos": len(mapa_tecnicos),
        "facturas": n_facturas,
        "oc_emitidas": n_emitidas,
        "oc_pendientes": n_pendientes,
        "trabajos": n_trabajos,
    }

    imprimir_reporte(
        conteos=conteos,
        fusiones=fusiones,
        advertencias=advertencias,
        errores_etl=[err_facturas, err_oc, err_trabajos],
        errores_extraccion=errores_extraccion,
        duracion_seg=duracion,
    )


if __name__ == "__main__":
    main()
