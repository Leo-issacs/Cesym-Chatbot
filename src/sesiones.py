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
import re
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
    "pagado":       "Monto cobrado (ej: 1500), 'pagado' si no sabes el monto, o 'sin cobrar':",
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


# Frases que en el paso "monto cobrado" significan "pagado, monto no especificado".
_PAGADO_MARCADORES = {
    "pagado", "pagada", "ya pagado", "ya pagada", "ya pague", "ya pagué",
    "ya esta pagado", "ya está pagado", "si pagado", "sí pagado",
    "pagado sin monto", "ya quedo pagado", "ya quedó pagado",
}


def _normalizar_pagado(valor: str) -> str:
    """Normaliza la respuesta al monto cobrado:
      - "" (sin cobrar) para 'sin cobrar'/'sin'/'no'/'0'/vacío,
      - el marcador 'PAGADO' para 'pagado'/'ya pagado'/... (pagado sin monto),
      - el número como string (quitando $ y comas) en cualquier otro caso.
    """
    from src.escritor import PAGADO_SIN_MONTO
    v = valor.lower().strip()
    if v in ("sin cobrar", "sin", "no", "0", ""):
        return ""
    if v in _PAGADO_MARCADORES:
        return PAGADO_SIN_MONTO
    return valor.replace("$", "").replace(",", "").strip()


# ─── Validaciones del flujo de cotización ──────────────────────────────────────

_IVA_8 = {"", "8", "8%", "0.08", ".08", "frontera"}
_IVA_16 = {"16", "16%", "0.16", ".16"}
_RFC_RE = re.compile(r"^[A-ZÑ&0-9]{12,13}$")


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
        valor = _normalizar_pagado(valor)

    sesion["datos"][campo] = valor
    sesion["paso"] += 1

    if sesion["paso"] >= len(_PASOS_AGREGAR):
        from src.escritor import formato_monto_pagado
        datos = sesion["datos"]
        pago_str = formato_monto_pagado(datos.get("pagado"))
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
            valor = _normalizar_pagado(valor)

        sesion["valor_nuevo"] = valor
        sesion["paso"] = "confirmando"
        _escribir_sesion(numero, sesion)

        from src.escritor import formato_monto_pagado
        _, label = _CAMPOS_EDITABLES[next(i for i, c in enumerate(_CAMPOS_EDITABLES) if c[0] == campo)]
        r = sesion["seleccionado"]
        valor_actual = r.get(campo) or "vacío"
        valor_mostrar = formato_monto_pagado(valor) if campo == "pagado" else (valor or "vacío")
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


# ─── Flujo: cotización ──────────────────────────────────────────────────────────

def iniciar_cotizacion(numero: str) -> str:
    estado = {"tipo": "cotizacion", "paso": "cliente_buscar", "datos": {}}
    _escribir_sesion(numero, estado)
    return (
        "Nueva cotización.\n"
        "Escribe 'cancelar' en cualquier momento para salir.\n\n"
        "Cliente (nombre o RFC):"
    )


def _fijar_cliente(d: dict, c: dict) -> None:
    d["cliente_nuevo"] = False
    d["cliente_rfc"] = c["rfc"]
    d["nombre_fiscal"] = c.get("nombre_fiscal", "")
    d["nombre_comercial"] = c.get("nombre_comercial", "")
    d["nombre"] = c.get("nombre_comercial") or c.get("nombre_fiscal") or c["rfc"]


def _ir_a_sucursal(numero, sesion):
    sesion["paso"] = "sucursal"
    _escribir_sesion(numero, sesion)
    return "Sucursal (código) o 'sin':"


def _ir_a_confirmar(numero, sesion):
    d = sesion["datos"]
    sesion["paso"] = "confirmando"
    _escribir_sesion(numero, sesion)
    suc = d["sucursal_nombre"] if d.get("sucursal_nueva") else (d.get("suc_label") or "sin")
    total = d["importe"] * (1 + d["iva_tasa"])
    return (
        "Confirma la cotización:\n\n"
        f"Cliente : {d['nombre']} ({d['cliente_rfc']})\n"
        f"Sucursal: {suc}\n"
        f"Trabajo : {d['descripcion']}\n"
        f"Importe : ${d['importe']:,.2f}\n"
        f"IVA     : {int(d['iva_tasa'] * 100)}%\n"
        f"Total   : ${total:,.2f}\n\n"
        "Escribe 'si' para guardar o 'no' para cancelar."
    )


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
            return f"¿Es {c['nombre_comercial']} ({c['rfc']})? si/no", None
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
    if tipo == "cotizacion":
        return _procesar_cotizacion(numero, texto, sesion)
    return _procesar_agregar(numero, texto, sesion)
