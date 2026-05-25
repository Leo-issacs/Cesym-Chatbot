"""
query_engine.py
---------------
Responsabilidad única: recibir el texto escrito por el usuario en consola,
interpretarlo con lógica de reglas simples (sin IA por ahora) y devolver
una respuesta en texto legible.

Cómo funciona:
  1. El usuario escribe un comando, ej: "buscar oc O01-507749"
  2. run_query() divide el texto en palabras y detecta el verbo principal.
  3. Llama a la función correspondiente que filtra/agrega los DataFrames.
  4. Devuelve un string con el resultado formateado.

No modifica los DataFrames. Solo los lee.
"""

import pandas as pd


def run_query(cmd: str, facturado: pd.DataFrame, pendiente: pd.DataFrame) -> str:
    """
    Punto de entrada principal. Recibe el texto del usuario y despacha
    al comando correspondiente.
    """
    partes = cmd.strip().lower().split()
    if not partes:
        return "Escribe un comando. Usa 'ayuda' para ver las opciones disponibles."

    verbo = partes[0]

    if verbo == "ayuda":
        return _ayuda()

    if verbo == "resumen":
        return _resumen(facturado, pendiente)

    if verbo == "total":
        alcance = partes[1] if len(partes) > 1 else "general"
        return _total(alcance, facturado, pendiente)

    if verbo == "facturas":
        return _listar_facturas(facturado)

    if verbo == "pendientes":
        filtro_suc = partes[1] if len(partes) > 1 else None
        return _listar_pendientes(filtro_suc, pendiente)

    if verbo == "buscar" and len(partes) >= 3:
        campo = partes[1]
        valor = partes[2]
        return _buscar(campo, valor, facturado, pendiente)

    if verbo == "estado" and len(partes) >= 2:
        texto = " ".join(partes[1:])
        return _por_estado(texto, facturado)

    if verbo == "errores":
        return _errores(facturado, pendiente)

    return (
        f"Comando no reconocido: '{cmd}'.\n"
        "Escribe 'ayuda' para ver los comandos disponibles."
    )


# ─── Comandos ─────────────────────────────────────────────────────────────────

def _total(alcance: str, facturado: pd.DataFrame, pendiente: pd.DataFrame) -> str:
    if alcance in ("facturado", "oc", "facturas"):
        t = facturado["monto_actual"].sum()
        return f"Total OC Facturado: ${t:,.2f}"

    if alcance in ("pendiente", "pte", "pendientes", "cotizado"):
        t = pendiente["importe"].sum()
        return f"Total Pendiente (PTE OC): ${t:,.2f}"

    # General: ambos
    t_fac = facturado["monto_actual"].sum()
    t_pte = pendiente["importe"].sum()
    linea = "─" * 32
    return (
        f"Total OC Facturado : ${t_fac:>14,.2f}\n"
        f"Total PTE OC       : ${t_pte:>14,.2f}\n"
        f"{linea}\n"
        f"TOTAL CARTERA      : ${t_fac + t_pte:>14,.2f}"
    )


def _resumen(facturado: pd.DataFrame, pendiente: pd.DataFrame) -> str:
    t_fac = facturado["monto_actual"].sum()
    t_pte = pendiente["importe"].sum()

    # Contar por estado (columna 'estado' + 'prioridad')
    estados = (
        facturado["estado"]
        .replace("", "Sin estado")
        .value_counts()
    )
    estados_str = "\n".join(f"    {k}: {v}" for k, v in estados.items())

    prioridades = facturado[facturado["prioridad"] == "PRIORIDAD"]

    return (
        f"╔══════════════════════════════════╗\n"
        f"       RESUMEN DE CARTERA\n"
        f"╚══════════════════════════════════╝\n"
        f"  OC Facturadas  : {len(facturado):>4} registros   ${t_fac:>12,.2f}\n"
        f"  OC Pendientes  : {len(pendiente):>4} registros   ${t_pte:>12,.2f}\n"
        f"  Con prioridad  : {len(prioridades):>4} factura(s)\n"
        f"\n"
        f"  Estados (OC Facturado):\n"
        f"{estados_str}"
    )


def _listar_facturas(facturado: pd.DataFrame) -> str:
    if facturado.empty:
        return "No hay facturas cargadas."
    resultado = _formato_facturado(facturado)
    return resultado + f"\n{'─'*52}\nTotal: ${facturado['monto_actual'].sum():,.2f}"


def _listar_pendientes(filtro_suc, pendiente: pd.DataFrame) -> str:
    df = pendiente.copy()

    if filtro_suc is not None:
        try:
            suc = int(filtro_suc)
            df = df[df["suc"] == suc]
            if df.empty:
                return f"No hay cotizaciones pendientes para la sucursal {suc}."
        except ValueError:
            return f"'{filtro_suc}' no es un número de sucursal válido."

    if df.empty:
        return "No hay cotizaciones pendientes."

    resultado = _formato_pendiente(df)
    return resultado + f"\n{'─'*52}\nTotal: ${df['importe'].sum():,.2f}"


def _buscar(campo: str, valor: str, facturado: pd.DataFrame, pendiente: pd.DataFrame) -> str:
    # Buscar por número de OC (búsqueda parcial)
    if campo == "oc":
        mask = facturado["oc"].str.upper().str.contains(valor.upper(), na=False)
        resultado = facturado[mask]
        if resultado.empty:
            return f"No se encontró ninguna OC que contenga '{valor}'."
        total = resultado["monto_actual"].sum()
        return _formato_facturado(resultado) + f"\n{'─'*52}\nSubtotal: ${total:,.2f}"

    # Buscar por número de factura (exacto)
    if campo in ("factura", "fac"):
        try:
            num = int(valor)
        except ValueError:
            return f"'{valor}' no es un número de factura válido."
        resultado = facturado[facturado["factura"] == num]
        if resultado.empty:
            return f"No se encontró la factura {num}."
        return _formato_facturado(resultado)

    # Buscar por número de cotización (exacto)
    if campo in ("cot", "cotizacion", "cotización"):
        try:
            num = int(valor)
        except ValueError:
            return f"'{valor}' no es un número de cotización válido."
        resultado = pendiente[pendiente["cot"] == num]
        if resultado.empty:
            return f"No se encontró la cotización {num}."
        return _formato_pendiente(resultado)

    # Buscar por sucursal en pendientes
    if campo in ("suc", "sucursal"):
        try:
            num = int(valor)
        except ValueError:
            return f"'{valor}' no es un número de sucursal válido."
        resultado = pendiente[pendiente["suc"] == num]
        if resultado.empty:
            return f"No hay cotizaciones pendientes para la sucursal {num}."
        total = resultado["importe"].sum()
        return _formato_pendiente(resultado) + f"\n{'─'*52}\nSubtotal: ${total:,.2f}"

    return (
        f"Campo de búsqueda desconocido: '{campo}'.\n"
        "Campos válidos: oc, factura, cot, suc"
    )


def _por_estado(texto: str, facturado: pd.DataFrame) -> str:
    mask_estado = facturado["estado"].str.upper().str.contains(texto.upper(), na=False)
    mask_prio = facturado["prioridad"].str.upper().str.contains(texto.upper(), na=False)
    resultado = facturado[mask_estado | mask_prio]

    if resultado.empty:
        return f"No se encontraron registros con estado/prioridad '{texto}'."

    total = resultado["monto_actual"].sum()
    return _formato_facturado(resultado) + f"\n{'─'*52}\nSubtotal: ${total:,.2f}"


def _errores(facturado: pd.DataFrame, pendiente: pd.DataFrame) -> str:
    problemas = []

    # OC Facturado
    montos_malos = facturado[facturado["monto_actual"].isna() | (facturado["monto_actual"] <= 0)]
    if not montos_malos.empty:
        problemas.append(f"Facturas con monto inválido (<= 0 o vacío): {montos_malos['factura'].tolist()}")

    sin_fecha = facturado[facturado["fecha"].isna()]
    if not sin_fecha.empty:
        problemas.append(f"Facturas sin fecha: {sin_fecha['factura'].tolist()}")

    sin_oc = facturado[facturado["oc"].isin(["nan", "", "NaN"])]
    if not sin_oc.empty:
        problemas.append(f"Facturas sin OC asignada: {sin_oc['factura'].tolist()}")

    # Pendientes
    imp_malos = pendiente[pendiente["importe"].isna() | (pendiente["importe"] <= 0)]
    if not imp_malos.empty:
        problemas.append(f"Cotizaciones con importe inválido: {imp_malos['cot'].tolist()}")

    duplicadas = pendiente[pendiente.duplicated("cot", keep=False)]
    if not duplicadas.empty:
        problemas.append(f"Cotizaciones con número duplicado: {duplicadas['cot'].unique().tolist()}")

    if not problemas:
        return "No se detectaron errores ni inconsistencias en los datos."

    lineas = "\n".join(f"  • {p}" for p in problemas)
    return f"=== INCONSISTENCIAS DETECTADAS ===\n{lineas}"


# ─── Formateadores de salida ──────────────────────────────────────────────────

def _formato_facturado(df: pd.DataFrame) -> str:
    """Devuelve una tabla de texto para facturas."""
    lineas = []
    for _, fila in df.iterrows():
        fecha = fila["fecha"].strftime("%Y-%m-%d") if pd.notna(fila["fecha"]) else "sin fecha"
        estado = f"  [{fila['estado']}]" if fila["estado"] else ""
        prio = f"  [{fila['prioridad']}]" if fila["prioridad"] else ""
        lineas.append(
            f"  Fac {fila['factura']} | {fila['oc']:<16} | ${fila['monto_actual']:>12,.2f} | {fecha}{estado}{prio}"
        )
    return "\n".join(lineas)


def _formato_pendiente(df: pd.DataFrame) -> str:
    """Devuelve una tabla de texto para cotizaciones pendientes."""
    lineas = []
    for _, fila in df.iterrows():
        concepto = f"  {fila['concepto']}" if fila["concepto"] else ""
        lineas.append(
            f"  Cot {fila['cot']} | Suc {fila['suc']} | ${fila['importe']:>12,.2f}{concepto}"
        )
    return "\n".join(lineas)


# ─── Ayuda ────────────────────────────────────────────────────────────────────

def _ayuda() -> str:
    return """
╔══════════════════════════════════════════════════════╗
              COMANDOS DISPONIBLES
╚══════════════════════════════════════════════════════╝

  TOTALES Y RESUMEN
  ─────────────────
  total                    → Total general de cartera
  total facturado          → Solo OC facturadas
  total pendiente          → Solo cotizaciones pendientes
  resumen                  → Vista general con conteos y estados

  LISTADOS
  ────────
  facturas                 → Todas las OC facturadas
  pendientes               → Todas las cotizaciones pendientes
  pendientes [suc]         → Pendientes de una sucursal específica

  BÚSQUEDAS
  ─────────
  buscar oc [texto]        → Buscar por número de OC (ej: buscar oc O01-507749)
  buscar factura [número]  → Buscar por número de factura
  buscar cot [número]      → Buscar cotización pendiente por número
  buscar suc [número]      → Pendientes de una sucursal

  FILTROS
  ───────
  estado [texto]           → Filtrar por estado (ej: estado aceptada)
  estado prioridad         → Ver solo las facturas marcadas como prioridad

  VALIDACIONES
  ────────────
  errores                  → Detectar inconsistencias en los datos

  OTROS
  ─────
  ayuda                    → Mostrar este menú
  salir                    → Cerrar el sistema
""".strip()
