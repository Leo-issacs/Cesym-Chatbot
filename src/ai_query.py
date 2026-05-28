"""
ai_query.py
-----------
Fallback de lenguaje natural usando la API de Claude (Haiku).

Solo se invoca cuando el parser de reglas no reconoce el comando.
Claude recibe el texto del usuario y devuelve el comando equivalente.
Si no puede traducir, retorna "" para que el caller muestre el error original.

El system prompt se envía con cache_control ephemeral para que Anthropic
lo almacene en caché y no se reprocese en cada llamada.
"""

import anthropic

_LISTA_COMANDOS = """
total
total facturado
total pendiente
total mensual
resumen
facturas
pendientes
pendientes [número de sucursal]
cobradas
sin cobrar
cruce
buscar oc [texto]
buscar factura [número]
buscar cot [número]
buscar suc [número]
buscar cliente [nombre]
estado [texto]
estado prioridad
errores
actualizar
ayuda
salir
""".strip()

_SYSTEM_PROMPT = (
    "Eres un asistente que traduce consultas en lenguaje natural al comando exacto "
    "de un sistema de chatbot para consultas de cartera de facturas empresariales.\n\n"
    "Tu ÚNICA tarea: devolver el comando más apropiado de la lista de abajo. "
    "Responde SOLO con el comando, sin explicaciones ni texto adicional. "
    "Si no existe un comando que corresponda, responde exactamente con la palabra: irreconocible\n\n"
    "Comandos disponibles:\n"
    + _LISTA_COMANDOS
)


def traducir_a_comando(texto: str, client: anthropic.Anthropic) -> str:
    """
    Traduce texto en lenguaje natural al comando reconocido más cercano.
    Retorna el comando (string), o "" si no puede traducir.
    """
    try:
        respuesta = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=64,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": texto}],
        )
        resultado = respuesta.content[0].text.strip().lower()
        if resultado == "irreconocible":
            return ""
        return resultado
    except Exception:
        return ""
