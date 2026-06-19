"""
sesiones.py
-----------
Maneja el estado de conversaciones multi-turno por número de teléfono.
Soporta tres flujos: registro de trabajo nuevo, edición y borrado.

PERSISTENCIA Y MÚLTIPLES WORKERS:
  El estado se guarda en un store compartido. Con USE_POSTGRES_SESSIONS=1 cada
  operación (leer/escribir/borrar) va a Postgres POR NÚMERO, en vivo. Esto es lo
  que permite correr uvicorn con varios workers: mensajes consecutivos de un mismo
  usuario pueden caer en workers distintos y todos ven el mismo estado.

  Sin Postgres (modo archivo) el estado vive en data/sesiones.json + un dict en
  memoria. En ese modo NO se debe correr con >1 worker, porque cada proceso tiene
  su propia copia en memoria y perdería el flujo entre mensajes.
"""

import json
import os
from difflib import get_close_matches
from pathlib import Path

_SESIONES_PATH = Path(__file__).parent.parent / "data" / "sesiones.json"

# USE_POSTGRES_SESSIONS=1 → usa chatbot.sesiones_bot en Postgres (ver sesiones_pg.py).
# Mantener en "0" (o no definida) hasta completar la migración a Postgres.
_USE_POSTGRES = os.getenv("USE_POSTGRES_SESSIONS", "0") == "1"

# Cache en memoria. En modo archivo es la fuente de verdad; en modo Postgres es
# solo un espejo dentro del request (las lecturas autoritativas van a la BD).
_sesiones: dict = {}

_PASOS_AGREGAR = ["mes", "tecnico", "cliente", "domicilio", "telefono", "tipo_trabajo", "pagado", "recibe"]

_PREGUNTAS_AGREGAR = {
    "mes":          "Mes del trabajo (ej: ENERO, MAYO, DICIEMBRE):",
    "tecnico":      "Tecnico que realizo el trabajo:",
    "cliente":      "Nombre del cliente:",
    "domicilio":    "Domicilio del cliente:",
    "telefono":     "Telefono del cliente (o 'sin' si no hay):",
    "tipo_trabajo": "Tipo de trabajo realizado:",
    "pagado":       "Monto cobrado (numero, ej: 1500) o 'sin cobrar':",
    "recibe":       "Quien recibe o firma el trabajo:",
}

_CAMPOS_EDITABLES = [
    ("mes",          "Mes"),
    ("tecnico",      "Tecnico"),
    ("cliente",      "Cliente"),
    ("domicilio",    "Domicilio"),
    ("telefono",     "Telefono"),
    ("tipo_trabajo", "Tipo de trabajo"),
    ("pagado",       "Monto pagado"),
    ("recibe",       "Recibe"),
]

_MESES = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]


def _normalizar_mes(texto: str) -> str | None:
    """Retorna el mes en mayúsculas si es válido (con tolerancia a typos), o None."""
    t = texto.strip().upper()
    if t in _MESES:
        return t
    matches = get_close_matches(t, _MESES, n=1, cutoff=0.7)
    return matches[0] if matches else None


# ─── Store: lectura/escritura/borrado POR NÚMERO ───────────────────────────────
#
# Toda la lógica de flujos pasa por estos tres helpers. En modo Postgres operan
# sobre la fila del número (en vivo); en modo archivo, sobre el dict + JSON local.

def _cargar() -> None:
    """Carga inicial de todas las sesiones al arranque (espejo en memoria).

    En modo Postgres esto es solo un calentamiento de cache; las lecturas reales
    de cada request usan _leer_sesion() (en vivo). En modo archivo es la fuente.
    """
    global _sesiones
    if _USE_POSTGRES:
        try:
            from src import sesiones_pg
            _sesiones = sesiones_pg.cargar_todas()
            return
        except Exception as e:
            print(f"[sesiones] Postgres no disponible, usando archivo: {e}")
    try:
        if _SESIONES_PATH.exists():
            _sesiones = json.loads(_SESIONES_PATH.read_text(encoding="utf-8"))
    except Exception:
        _sesiones = {}


def _guardar_archivo() -> None:
    """Persiste TODO el dict a data/sesiones.json y lo sube a Drive (modo archivo)."""
    try:
        _SESIONES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SESIONES_PATH.write_text(json.dumps(_sesiones, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id and _SESIONES_PATH.exists():
        try:
            from src.drive import subir_archivo
            subir_archivo(_SESIONES_PATH, folder_id, mime_type="application/json")
        except Exception:
            pass


def _leer_sesion(numero: str) -> dict | None:
    """Devuelve el estado de la sesión del número, o None. En modo Postgres lee
    en vivo de la BD (así lo ven todos los workers); en modo archivo, del dict."""
    if _USE_POSTGRES:
        try:
            from src import sesiones_pg
            return sesiones_pg.cargar_una(numero)
        except Exception as e:
            print(f"[sesiones] Postgres no disponible al leer, usando memoria: {e}")
    return _sesiones.get(numero)


def _escribir_sesion(numero: str, estado: dict) -> None:
    """Crea/actualiza la sesión del número en el store compartido."""
    _sesiones[numero] = estado  # mantiene el espejo coherente dentro del request
    if _USE_POSTGRES:
        try:
            from src import sesiones_pg
            sesiones_pg.guardar_una(numero, estado)
            return
        except Exception as e:
            print(f"[sesiones] Postgres no disponible al guardar, usando archivo: {e}")
    _guardar_archivo()


def _borrar_sesion(numero: str) -> None:
    """Elimina la sesión del número del store compartido (flujo terminado/cancelado)."""
    _sesiones.pop(numero, None)
    if _USE_POSTGRES:
        try:
            from src import sesiones_pg
            sesiones_pg.borrar(numero)
            return
        except Exception as e:
            print(f"[sesiones] Postgres no disponible al borrar, usando archivo: {e}")
    _guardar_archivo()


_cargar()


# ─── Flujo: agregar trabajo ────────────────────────────────────────────────────

def iniciar(numero: str) -> str:
    estado = {"tipo": "agregar", "paso": 0, "datos": {}, "confirmando": False}
    _escribir_sesion(numero, estado)
    return (
        "Registrando nuevo trabajo.\n"
        "Escribe 'cancelar' en cualquier momento para salir.\n\n"
        + _PREGUNTAS_AGREGAR[_PASOS_AGREGAR[0]]
    )


def _procesar_agregar(numero: str, texto: str, sesion: dict) -> tuple[str, dict | None]:
    if sesion["confirmando"]:
        if texto.strip().lower() in ("si", "sí", "s", "yes", "y", "1"):
            datos = sesion["datos"].copy()
            _borrar_sesion(numero)
            return "Guardando...", datos
        else:
            _borrar_sesion(numero)
            return "Registro cancelado.", None

    paso = sesion["paso"]
    campo = _PASOS_AGREGAR[paso]
    valor = texto.strip()

    if campo == "mes":
        mes = _normalizar_mes(valor)
        if mes is None:
            return (
                f"Mes no reconocido: '{valor.upper()}'.\n"
                "Escribe el nombre completo del mes (ej: ENERO, MAYO, DICIEMBRE):"
            ), None
        valor = mes
    elif campo == "telefono" and valor.lower() == "sin":
        valor = ""
    elif campo == "pagado":
        if valor.lower() in ("sin cobrar", "sin", "no", "0", ""):
            valor = ""
        else:
            valor = valor.replace("$", "").replace(",", "").strip()

    sesion["datos"][campo] = valor
    sesion["paso"] += 1

    if sesion["paso"] >= len(_PASOS_AGREGAR):
        datos = sesion["datos"]
        pago_str = f"${float(datos['pagado']):,.2f}" if datos.get("pagado") else "sin cobrar"
        sesion["confirmando"] = True
        _escribir_sesion(numero, sesion)
        return (
            "Confirma el registro:\n\n"
            f"Mes      : {datos['mes']}\n"
            f"Tecnico  : {datos['tecnico']}\n"
            f"Cliente  : {datos['cliente']}\n"
            f"Trabajo  : {datos['tipo_trabajo']}\n"
            f"Monto    : {pago_str}\n"
            f"Domicilio: {datos['domicilio']}\n"
            f"Tel      : {datos.get('telefono') or 'sin'}\n"
            f"Recibe   : {datos['recibe']}\n\n"
            "Escribe 'si' para guardar o 'no' para cancelar."
        ), None

    _escribir_sesion(numero, sesion)
    return _PREGUNTAS_AGREGAR[_PASOS_AGREGAR[sesion["paso"]]], None


# ─── Flujo: editar trabajo ─────────────────────────────────────────────────────

def iniciar_editar(numero: str, registros: list[dict]) -> str:
    if not registros:
        return "No hay trabajos registrados para editar."

    estado = {
        "tipo": "editar",
        "paso": "seleccionar",
        "registros": registros,
        "seleccionado": None,
        "campo": None,
        "valor_nuevo": None,
    }
    _escribir_sesion(numero, estado)

    lineas = ["Selecciona el trabajo a editar:\n"]
    for i, r in enumerate(registros, 1):
        pago = f"${float(r['pagado']):,.2f}" if r.get("pagado") else "sin cobrar"
        lineas.append(f"{i}. {r['cliente']} | {r['tipo_trabajo']} | {r['mes']} | {pago}")
    lineas.append("\nEscribe el número del trabajo o 'cancelar'.")
    return "\n".join(lineas)


def _procesar_editar(numero: str, texto: str, sesion: dict) -> tuple[str, dict | None]:
    paso = sesion["paso"]

    if paso == "seleccionar":
        try:
            n = int(texto.strip())
            registros = sesion["registros"]
            if n < 1 or n > len(registros):
                return f"Número inválido. Elige entre 1 y {len(registros)}.", None
            sesion["seleccionado"] = registros[n - 1]
            sesion["paso"] = "campo"
            _escribir_sesion(numero, sesion)

            r = sesion["seleccionado"]
            pago = f"${float(r['pagado']):,.2f}" if r.get("pagado") else "sin cobrar"
            lineas = [
                "Trabajo seleccionado:\n",
                f"Mes      : {r['mes']}",
                f"Tecnico  : {r['tecnico']}",
                f"Cliente  : {r['cliente']}",
                f"Trabajo  : {r['tipo_trabajo']}",
                f"Monto    : {pago}",
                f"Domicilio: {r['domicilio']}",
                f"Tel      : {r.get('telefono') or 'sin'}",
                f"Recibe   : {r['recibe']}",
                "\n¿Que campo quieres editar?",
            ]
            for i, (_, label) in enumerate(_CAMPOS_EDITABLES, 1):
                lineas.append(f"{i}. {label}")
            lineas.append("\nEscribe el número del campo.")
            return "\n".join(lineas), None
        except ValueError:
            return "Escribe el número del trabajo que quieres editar.", None

    if paso == "campo":
        try:
            n = int(texto.strip())
            if n < 1 or n > len(_CAMPOS_EDITABLES):
                return f"Número inválido. Elige entre 1 y {len(_CAMPOS_EDITABLES)}.", None
            campo, label = _CAMPOS_EDITABLES[n - 1]
            sesion["campo"] = campo
            sesion["paso"] = "valor"
            _escribir_sesion(numero, sesion)

            r = sesion["seleccionado"]
            valor_actual = r.get(campo) or "vacío"
            if campo == "pagado" and r.get("pagado"):
                try:
                    valor_actual = f"${float(r['pagado']):,.2f}"
                except ValueError:
                    pass
            return f"Campo: {label}\nValor actual: {valor_actual}\n\nEscribe el nuevo valor:", None
        except ValueError:
            return "Escribe el número del campo.", None

    if paso == "valor":
        valor = texto.strip()
        campo = sesion["campo"]
        if campo == "mes":
            mes = _normalizar_mes(valor)
            if mes is None:
                return (
                    f"Mes no reconocido: '{valor.upper()}'.\n"
                    "Escribe el nombre completo del mes (ej: ENERO, MAYO, DICIEMBRE):"
                ), None
            valor = mes
        elif campo == "telefono" and valor.lower() == "sin":
            valor = ""
        elif campo == "pagado":
            if valor.lower() in ("sin cobrar", "sin", "no", "0", ""):
                valor = ""
            else:
                valor = valor.replace("$", "").replace(",", "").strip()

        sesion["valor_nuevo"] = valor
        sesion["paso"] = "confirmando"
        _escribir_sesion(numero, sesion)

        _, label = _CAMPOS_EDITABLES[next(i for i, c in enumerate(_CAMPOS_EDITABLES) if c[0] == campo)]
        r = sesion["seleccionado"]
        valor_actual = r.get(campo) or "vacío"
        valor_mostrar = f"${float(valor):,.2f}" if campo == "pagado" and valor else valor or "vacío"
        return (
            f"Confirmar cambio:\n\n"
            f"Campo   : {label}\n"
            f"Antes   : {valor_actual}\n"
            f"Despues : {valor_mostrar}\n\n"
            "Escribe 'si' para guardar o 'no' para cancelar."
        ), None

    if paso == "confirmando":
        if texto.strip().lower() in ("si", "sí", "s", "yes", "y", "1"):
            sel = sesion["seleccionado"]
            datos = {
                "tipo": "editar",
                "indice": sel["indice_real"],
                "campo": sesion["campo"],
                "valor": sesion["valor_nuevo"],
                "pg_id": sel.get("pg_id"),
                "clave": {"cliente": sel.get("cliente", ""),
                          "tipo_trabajo": sel.get("tipo_trabajo", ""),
                          "mes": sel.get("mes", "")},
            }
            _borrar_sesion(numero)
            return "Guardando...", datos
        else:
            _borrar_sesion(numero)
            return "Edición cancelada.", None

    return "Error en el flujo. Escribe 'cancelar' e intenta de nuevo.", None


# ─── Flujo: borrar trabajo ─────────────────────────────────────────────────────

def iniciar_borrar(numero: str, registros: list[dict]) -> str:
    if not registros:
        return "No hay trabajos registrados para borrar."

    estado = {
        "tipo": "borrar",
        "paso": "seleccionar",
        "registros": registros,
        "seleccionado": None,
    }
    _escribir_sesion(numero, estado)

    lineas = ["Selecciona el trabajo a eliminar:\n"]
    for i, r in enumerate(registros, 1):
        pago = f"${float(r['pagado']):,.2f}" if r.get("pagado") else "sin cobrar"
        lineas.append(f"{i}. {r['cliente']} | {r['tipo_trabajo']} | {r['mes']} | {pago}")
    lineas.append("\nEscribe el número del trabajo o 'cancelar'.")
    return "\n".join(lineas)


def _procesar_borrar(numero: str, texto: str, sesion: dict) -> tuple[str, dict | None]:
    paso = sesion["paso"]

    if paso == "seleccionar":
        try:
            n = int(texto.strip())
            registros = sesion["registros"]
            if n < 1 or n > len(registros):
                return f"Número inválido. Elige entre 1 y {len(registros)}.", None
            sesion["seleccionado"] = registros[n - 1]
            sesion["paso"] = "confirmando"
            _escribir_sesion(numero, sesion)

            r = sesion["seleccionado"]
            pago = f"${float(r['pagado']):,.2f}" if r.get("pagado") else "sin cobrar"
            return (
                f"¿Eliminar este trabajo?\n\n"
                f"Mes      : {r['mes']}\n"
                f"Tecnico  : {r['tecnico']}\n"
                f"Cliente  : {r['cliente']}\n"
                f"Trabajo  : {r['tipo_trabajo']}\n"
                f"Monto    : {pago}\n\n"
                "Escribe 'si' para eliminar o 'no' para cancelar.\n"
                "ADVERTENCIA: Esta accion no se puede deshacer."
            ), None
        except ValueError:
            return "Escribe el número del trabajo que quieres eliminar.", None

    if paso == "confirmando":
        if texto.strip().lower() in ("si", "sí", "s", "yes", "y", "1"):
            sel = sesion["seleccionado"]
            datos = {
                "tipo": "borrar",
                "indice": sel["indice_real"],
                "cliente": sel["cliente"],
                "pg_id": sel.get("pg_id"),
                "clave": {"cliente": sel.get("cliente", ""),
                          "tipo_trabajo": sel.get("tipo_trabajo", ""),
                          "mes": sel.get("mes", "")},
            }
            _borrar_sesion(numero)
            return "Eliminando...", datos
        else:
            _borrar_sesion(numero)
            return "Eliminación cancelada.", None

    return "Error en el flujo. Escribe 'cancelar' e intenta de nuevo.", None


# ─── API pública ───────────────────────────────────────────────────────────────

def tiene_sesion(numero: str) -> bool:
    return _leer_sesion(numero) is not None


def cancelar(numero: str) -> str:
    _borrar_sesion(numero)
    return "Registro cancelado."


def procesar(numero: str, texto: str) -> tuple[str, dict | None]:
    if texto.strip().lower() == "cancelar":
        return cancelar(numero), None

    sesion = _leer_sesion(numero)
    if sesion is None:
        # Defensa: la sesión expiró o ya no existe en el store compartido.
        return "No hay un proceso activo. Escribe 'ayuda' para ver los comandos.", None

    tipo = sesion.get("tipo")

    if tipo == "editar":
        return _procesar_editar(numero, texto, sesion)
    if tipo == "borrar":
        return _procesar_borrar(numero, texto, sesion)
    return _procesar_agregar(numero, texto, sesion)
