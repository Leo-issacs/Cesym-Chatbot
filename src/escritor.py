"""
escritor.py
-----------
Responsabilidad unica: escribir datos en los archivos Excel.

Reglas:
- Nunca modifica el Excel original (en Drive, carpeta 01_Excels_Originales).
- Siempre crea un backup en data/backups/ antes de escribir.
- Sube el archivo modificado de vuelta a Drive.
- No toca los DataFrames en memoria — eso es responsabilidad del caller.
"""

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.loader import _resolver_ruta_trabajos

DATA_BACKUPS_DIR = Path(__file__).parent.parent / "data" / "backups"


def _hacer_backup(ruta_original: Path) -> Path:
    """Copia el archivo a data/backups/ con timestamp antes de modificarlo."""
    DATA_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DATA_BACKUPS_DIR / f"{ruta_original.stem}_{timestamp}{ruta_original.suffix}"
    shutil.copy2(ruta_original, destino)
    import os
    folder_id = os.getenv("DRIVE_BACKUPS_FOLDER_ID")
    if folder_id:
        try:
            from src.drive import subir_excel
            subir_excel(destino, folder_id)
        except Exception:
            pass
    return destino


_CAMPO_A_COLUMNA_IDX = {
    "mes":          0,
    "tecnico":      1,
    "cliente":      2,
    "domicilio":    4,
    "telefono":     5,
    "tipo_trabajo": 6,
    "pagado":       8,
    "recibe":       9,
}

_COLUMNAS_TRABAJOS = [
    "ENERO", "TECNICO", "CLIENTE", "REP #",
    "DOMICILIO", "TELEFONO", "TIPO DE TRABAJO",
    "Unnamed: 7", "PAGADO", "RECIBE",
]

# Marcador para "pagado pero sin monto especificado" (algunos reportes solo
# indican que ya se pagó, sin el importe). En el Excel se guarda este texto en la
# columna PAGADO (igual que en los reportes reales). En Postgres, la columna es
# numérica (NULL = sin cobrar), así que el monto se guarda como NULL.
PAGADO_SIN_MONTO = "PAGADO"


def _es_pagado_sin_monto(pago) -> bool:
    return isinstance(pago, str) and pago.strip().upper() == PAGADO_SIN_MONTO


def pago_a_numero(pago):
    """Convierte el valor de 'pagado' a float, o None si es vacío o el marcador
    'PAGADO' (pagado sin monto). No lanza ante texto no numérico."""
    if pago in (None, "") or _es_pagado_sin_monto(pago):
        return None
    try:
        return float(pago)
    except (TypeError, ValueError):
        return None


def formato_monto_pagado(pago) -> str:
    """Texto del estado de pago para confirmaciones y resúmenes."""
    if pago in (None, ""):
        return "sin cobrar"
    if _es_pagado_sin_monto(pago):
        return "Pagado (sin monto)"
    try:
        return f"${float(pago):,.2f}"
    except (TypeError, ValueError):
        return str(pago)


def _obtener_o_crear_archivo_trabajos() -> Path:
    """
    Retorna la ruta del archivo de trabajos.
    Si no existe, lo crea con los headers correctos en data/raw/.
    """
    try:
        return _resolver_ruta_trabajos()
    except FileNotFoundError:
        from src.loader import DATA_RAW_DIR
        DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_RAW_DIR / "CONTROL DE INST. MINISPLIT 2026.xlsx"
        pd.DataFrame(columns=_COLUMNAS_TRABAJOS).to_excel(path, index=False)
        return path


# Mensaje (se manda por WhatsApp) cuando el guard de seguridad aborta la escritura.
_MSG_ABORTO_GUARDIA = (
    "No se guardó el cambio para no perder registros del archivo.\n"
    "El Excel quedó intacto. Intenta de nuevo o avisa a soporte."
)


def _cargar_trabajos(path: Path):
    """
    Lee el Excel COMPLETO (todas las filas, incluidas las parciales) y calcula
    qué filas ve el bot.

    El filtro "cliente Y tipo_trabajo no nulos" se usa SOLO para mapear el índice
    posicional que el bot muestra por WhatsApp a la fila real del archivo. NUNCA
    para decidir qué se escribe: las filas parciales (capturas a medias, notas)
    deben conservarse en su posición original.

    Retorna:
        df               : DataFrame con TODAS las filas del Excel.
        indices_visibles : etiquetas de índice de las filas visibles, en orden.
                           La posición i es el índice que expone el bot; su valor
                           es la etiqueta real en df.
        cliente_col      : nombre de la columna de cliente (posición 2).
        tipo_col         : nombre de la columna de tipo de trabajo (posición 6).
    """
    df = pd.read_excel(path, header=0, dtype=str)
    cliente_col = df.columns[2]
    tipo_col = df.columns[6]
    mask = df[cliente_col].notna() & df[tipo_col].notna()
    indices_visibles = list(df.index[mask])
    return df, indices_visibles, cliente_col, tipo_col


def _persistir_seguro(df: pd.DataFrame, path: Path, filas_esperadas: int) -> str | None:
    """
    Escribe df al Excel SOLO si conserva el número de filas esperado; respalda el
    archivo actual justo antes de sobrescribirlo.

    Es la red de seguridad del fix P0.2: si la operación fuera a perder filas que
    no se borraron a propósito (regresión), aborta sin tocar el Excel.

    Retorna None si se escribió correctamente, o un mensaje de error si se abortó.
    """
    if len(df) != filas_esperadas:
        return _MSG_ABORTO_GUARDIA
    try:
        _hacer_backup(path)
        df.to_excel(path, index=False)
    except PermissionError:
        return ("No se pudo guardar: el archivo Excel está abierto en otro "
                "programa. Ciérralo e intenta de nuevo.")
    return None


def _postgres_writes_activo() -> bool:
    """USE_POSTGRES_WRITES=1 → el bot escribe trabajos también en Postgres."""
    import os
    return os.getenv("USE_POSTGRES_WRITES", "0") == "1"


def _escribir_trabajo_postgres(datos: dict) -> None:
    """
    Dual write: si USE_POSTGRES_WRITES=1, escribe el trabajo en chatbot.trabajos.

    Best-effort: ante cualquier error (sin DATABASE_URL, BD caída, etc.) loguea y
    deja que el flujo siga — el Excel lo escribe SIEMPRE el caller, sea cual sea el
    resultado de esta función. Postgres se escribe ANTES que el Excel.

    Resuelve los nombres de cliente/técnico a sus ids (creándolos si no existen),
    porque chatbot.trabajos referencia por FK.
    """
    if not _postgres_writes_activo():
        return
    try:
        from sqlalchemy import text
        from src.db_postgres import get_engine, SCHEMA
        from src import escritor_pg

        pago = datos.get("pagado")
        engine = get_engine()
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text(f"SET search_path TO {SCHEMA}"))
            fila_pg = {
                "mes":          (datos.get("mes") or "").strip().upper() or None,
                "tecnico_id":   escritor_pg.resolver_o_crear_tecnico(conn, datos.get("tecnico", "")),
                "cliente_id":   escritor_pg.resolver_o_crear_cliente(conn, datos.get("cliente", "")),
                "rep_num":      (datos.get("rep_num") or "").strip() or None,
                "domicilio":    (datos.get("domicilio") or "").strip() or None,
                "telefono":     (datos.get("telefono") or "").strip() or None,
                "tipo_trabajo": (datos.get("tipo_trabajo") or "").strip() or None,
                "pagado":       pago_a_numero(pago),
                "recibe":       (datos.get("recibe") or "").strip() or None,
            }
            pg_id = escritor_pg.insertar_trabajo(conn, fila_pg)
        print(f"[escritor_pg] Trabajo escrito en Postgres (id={pg_id}).", flush=True)
    except Exception as e:
        print(f"[escritor_pg] INSERT en Postgres falló, solo Excel: {e}", flush=True)


def agregar_trabajo(datos: dict) -> str:
    """
    Agrega una fila al Excel de control de trabajos, hace backup y sube a Drive.

    datos: dict con claves mes, tecnico, cliente, domicilio, telefono,
                              tipo_trabajo, pagado, recibe

    Retorna mensaje de resultado (exito o error).
    """
    path = _obtener_o_crear_archivo_trabajos()

    # Leer el Excel COMPLETO. La nueva fila se agrega al final sin descartar las
    # filas parciales existentes (el bug P0.2 era escribir el DataFrame filtrado).
    df, _, _, _ = _cargar_trabajos(path)
    filas_originales = len(df)

    # Construir nueva fila usando los nombres de columna originales del Excel
    nueva_fila = {
        df.columns[0]: datos.get("mes", ""),        # ENERO (columna de mes)
        df.columns[1]: datos.get("tecnico", ""),     # TECNICO
        df.columns[2]: datos.get("cliente", ""),     # CLIENTE
        df.columns[3]: "",                            # REP # (auto-vacio, se llena manual)
        df.columns[4]: datos.get("domicilio", ""),   # DOMICILIO
        df.columns[5]: datos.get("telefono", ""),    # TELEFONO
        df.columns[6]: datos.get("tipo_trabajo", ""),# TIPO DE TRABAJO
        df.columns[7]: "",                            # columna vacía
        df.columns[8]: datos.get("pagado", ""),      # PAGADO
        df.columns[9]: datos.get("recibe", ""),      # RECIBE
    }

    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)

    # Dual write: Postgres primero (best-effort), Excel siempre.
    _escribir_trabajo_postgres(datos)

    error = _persistir_seguro(df, path, filas_originales + 1)
    if error:
        return error

    # Subir a Drive si está configurado
    import os
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id:
        try:
            from src.drive import subir_excel
            subir_excel(path, folder_id)
        except Exception as e:
            return (
                f"Trabajo guardado localmente, pero no se pudo subir a Drive: {e}\n"
                "Usa 'actualizar' para sincronizar manualmente."
            )

    pago_str = formato_monto_pagado(datos.get("pagado"))
    return (
        f"Trabajo registrado correctamente.\n"
        f"{datos['cliente']} | {datos['tipo_trabajo']} | {pago_str}"
    )


def _subir_a_drive(path: Path) -> str | None:
    """Sube el archivo a Drive. Retorna mensaje de error o None si todo bien."""
    import os
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if not folder_id:
        return None
    try:
        from src.drive import subir_excel
        subir_excel(path, folder_id)
        return None
    except Exception as e:
        return (
            f"Guardado localmente, pero no se pudo subir a Drive: {e}\n"
            "Usa 'actualizar' para sincronizar manualmente."
        )


# ─── Edición/borrado por pg_id (clave estable, elimina el race posicional) ────

def _conexion_pg(accion):
    """Abre una transacción Postgres con search_path al schema chatbot y ejecuta
    `accion(conn)`. Best-effort: loguea y traga cualquier error (Excel es la red).
    En SQLite (tests) no fija search_path: usa las tablas desnudas."""
    try:
        from sqlalchemy import text
        from src.db_postgres import get_engine, SCHEMA
        engine = get_engine()
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text(f"SET search_path TO {SCHEMA}"))
            accion(conn)
        return True
    except Exception as e:
        print(f"[escritor_pg] operación en Postgres falló: {e}", flush=True)
        return False


def _campo_a_columna_pg(conn, campo: str, valor: str) -> dict:
    """Traduce (campo del bot, valor) a la columna/valor de chatbot.trabajos.
    cliente/tecnico se resuelven a su id (creándolos); pagado a float; mes a upper."""
    from src import escritor_pg
    if campo == "cliente":
        return {"cliente_id": escritor_pg.resolver_o_crear_cliente(conn, valor)}
    if campo == "tecnico":
        return {"tecnico_id": escritor_pg.resolver_o_crear_tecnico(conn, valor)}
    if campo == "pagado":
        return {"pagado": pago_a_numero(valor)}
    if campo == "mes":
        return {"mes": (valor or "").strip().upper() or None}
    return {campo: valor or None}  # domicilio, telefono, tipo_trabajo, recibe


def _buscar_fila_por_clave(df, indices_visibles, clave: dict):
    """Ubica la fila del Excel por la clave natural (cliente+tipo_trabajo+mes,
    normalizados), sin depender de la posición. Devuelve la etiqueta si el match
    es ÚNICO; None si no hay match o es ambiguo."""
    def norm(v):
        return str(v or "").strip().upper()
    cli, tipo, mes = norm(clave.get("cliente")), norm(clave.get("tipo_trabajo")), norm(clave.get("mes"))
    col_mes, col_cli, col_tipo = df.columns[0], df.columns[2], df.columns[6]
    candidatos = [
        idx for idx in indices_visibles
        if norm(df.at[idx, col_cli]) == cli
        and norm(df.at[idx, col_tipo]) == tipo
        and norm(df.at[idx, col_mes]) == mes
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _localizar_idx_excel(df, indices_visibles, indice, clave, usar_pg):
    """Etiqueta de la fila del Excel a tocar: por clave natural si usamos pg_id,
    o por índice posicional (comportamiento histórico) si no. None si no se ubica."""
    if usar_pg and clave:
        return _buscar_fila_por_clave(df, indices_visibles, clave)
    if _postgres_writes_activo():  # flag activo pero sin pg_id → degradado, avisar
        print("[escritor] pg_id no disponible, usando índice posicional (fallback).", flush=True)
    if indice is None or indice < 0 or indice >= len(indices_visibles):
        return None
    return indices_visibles[indice]


def borrar_trabajo(indice: int, pg_id: int | None = None, clave: dict | None = None) -> str:
    """
    Elimina un trabajo. Con USE_POSTGRES_WRITES=1 y pg_id, borra en Postgres por id
    (clave estable, sin race) y luego ubica la fila del Excel por clave natural.
    Sin pg_id, cae al borrado por índice posicional (comportamiento histórico).
    """
    usar_pg = _postgres_writes_activo() and pg_id is not None
    if usar_pg:
        from src import escritor_pg
        _conexion_pg(lambda conn: escritor_pg.borrar_trabajo(conn, pg_id))

    path = _obtener_o_crear_archivo_trabajos()
    df, indices_visibles, cliente_col, _ = _cargar_trabajos(path)
    filas_originales = len(df)

    idx_real = _localizar_idx_excel(df, indices_visibles, indice, clave, usar_pg)
    if idx_real is None:
        if usar_pg:
            print("[escritor] Excel: fila no ubicada por clave; Postgres ya borró.", flush=True)
            return f"Trabajo de '{(clave or {}).get('cliente', '')}' eliminado correctamente."
        return "Error: trabajo no encontrado."

    cliente = df.at[idx_real, cliente_col]
    df = df.drop(index=idx_real)

    error = _persistir_seguro(df, path, filas_originales - 1)
    if error:
        return error

    error_drive = _subir_a_drive(path)
    if error_drive:
        return error_drive

    return f"Trabajo de '{cliente}' eliminado correctamente."


def editar_trabajo(indice: int, campo: str, valor: str,
                   pg_id: int | None = None, clave: dict | None = None) -> str:
    """
    Modifica un campo de un trabajo. Con USE_POSTGRES_WRITES=1 y pg_id, actualiza
    en Postgres por id (clave estable, sin race) y luego ubica la fila del Excel
    por clave natural. Sin pg_id, edita por índice posicional (histórico).

    campo: mes, tecnico, cliente, domicilio, telefono, tipo_trabajo, pagado, recibe
    valor: nuevo valor como string (vacío = borrar el campo)
    """
    col_idx = _CAMPO_A_COLUMNA_IDX.get(campo)
    if col_idx is None:
        return f"Campo '{campo}' no reconocido."

    usar_pg = _postgres_writes_activo() and pg_id is not None
    if usar_pg:
        from src import escritor_pg
        _conexion_pg(lambda conn: escritor_pg.actualizar_trabajo(
            conn, pg_id, _campo_a_columna_pg(conn, campo, valor)))

    path = _obtener_o_crear_archivo_trabajos()
    df, indices_visibles, _, _ = _cargar_trabajos(path)

    idx_real = _localizar_idx_excel(df, indices_visibles, indice, clave, usar_pg)
    if idx_real is None:
        if usar_pg:
            print("[escritor] Excel: fila no ubicada por clave; Postgres ya actualizó.", flush=True)
            return "Trabajo actualizado correctamente."
        return "Error: trabajo no encontrado."

    col_name = df.columns[col_idx]
    df.at[idx_real, col_name] = valor if valor else None

    error = _persistir_seguro(df, path, len(df))
    if error:
        return error

    error_drive = _subir_a_drive(path)
    if error_drive:
        return error_drive

    return "Trabajo actualizado correctamente."
