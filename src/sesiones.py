"""
sesiones.py
-----------
Maneja el estado de conversaciones multi-turno por número de teléfono.
Actualmente solo soporta el flujo de registro de trabajos.

El estado se persiste en data/sesiones.json para sobrevivir reinicios del servidor.
"""

import json
from pathlib import Path

_SESIONES_PATH = Path(__file__).parent.parent / "data" / "sesiones.json"

_sesiones: dict = {}

_PASOS = ["mes", "tecnico", "cliente", "domicilio", "telefono", "tipo_trabajo", "pagado", "recibe"]

_PREGUNTAS = {
    "mes":          "Mes del trabajo (ej: ENERO, MAYO, DICIEMBRE):",
    "tecnico":      "Tecnico que realizo el trabajo:",
    "cliente":      "Nombre del cliente:",
    "domicilio":    "Domicilio del cliente:",
    "telefono":     "Telefono del cliente (o 'sin' si no hay):",
    "tipo_trabajo": "Tipo de trabajo realizado:",
    "pagado":       "Monto cobrado (numero, ej: 1500) o 'sin cobrar':",
    "recibe":       "Quien recibe o firma el trabajo:",
}


def _cargar():
    global _sesiones
    try:
        if _SESIONES_PATH.exists():
            _sesiones = json.loads(_SESIONES_PATH.read_text(encoding="utf-8"))
    except Exception:
        _sesiones = {}


def _guardar():
    try:
        _SESIONES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SESIONES_PATH.write_text(json.dumps(_sesiones, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


_cargar()


def iniciar(numero: str) -> str:
    """Inicia el flujo de registro. Retorna la primera pregunta."""
    _sesiones[numero] = {"paso": 0, "datos": {}, "confirmando": False}
    _guardar()
    return (
        "Registrando nuevo trabajo.\n"
        "Escribe 'cancelar' en cualquier momento para salir.\n\n"
        + _PREGUNTAS[_PASOS[0]]
    )


def tiene_sesion(numero: str) -> bool:
    return numero in _sesiones


def cancelar(numero: str) -> str:
    _sesiones.pop(numero, None)
    _guardar()
    return "Registro cancelado."


def procesar(numero: str, texto: str) -> tuple[str, dict | None]:
    """
    Procesa la respuesta del usuario en el paso actual.
    Retorna (mensaje_para_enviar, datos_completos_o_None).
    datos_completos_o_None es el dict con los datos solo cuando el usuario confirma.
    """
    if texto.strip().lower() == "cancelar":
        return cancelar(numero), None

    sesion = _sesiones[numero]

    # --- Paso de confirmación ---
    if sesion["confirmando"]:
        if texto.strip().lower() in ("si", "sí", "s", "yes", "y", "1"):
            datos = sesion["datos"].copy()
            _sesiones.pop(numero)
            _guardar()
            return "Guardando...", datos
        else:
            _sesiones.pop(numero)
            _guardar()
            return "Registro cancelado.", None

    # --- Recolección de datos ---
    paso = sesion["paso"]
    campo = _PASOS[paso]
    valor = texto.strip()

    # Normalización por campo
    if campo == "mes":
        valor = valor.upper()
    elif campo == "telefono" and valor.lower() == "sin":
        valor = ""
    elif campo == "pagado":
        if valor.lower() in ("sin cobrar", "sin", "no", "0", ""):
            valor = ""
        else:
            valor = valor.replace("$", "").replace(",", "").strip()

    sesion["datos"][campo] = valor
    sesion["paso"] += 1
    _guardar()

    # ¿Terminó la recolección?
    if sesion["paso"] >= len(_PASOS):
        datos = sesion["datos"]
        pago_str = f"${float(datos['pagado']):,.2f}" if datos.get("pagado") else "sin cobrar"
        sesion["confirmando"] = True
        _guardar()

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

    # Siguiente pregunta
    return _PREGUNTAS[_PASOS[sesion["paso"]]], None
