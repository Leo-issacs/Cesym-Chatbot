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


def run_query(
    cmd: str,
    facturado: pd.DataFrame,
    pendiente: pd.DataFrame,
    facturas: pd.DataFrame,
    trabajos: pd.DataFrame = None,
) -> str:
    """
    Punto de entrada principal. Recibe el texto del usuario y despacha
    al comando correspondiente.
    """
    if trabajos is None:
        trabajos = pd.DataFrame()

    partes = cmd.strip().lower().split()
    if not partes:
        return "Escribe un comando. Usa 'ayuda' para ver las opciones disponibles."

    verbo = partes[0]

    if verbo == "ayuda":
        return _ayuda()

    if verbo == "resumen":
        return _resumen(facturado, pendiente, facturas, trabajos)

    if verbo == "total":
        alcance = " ".join(partes[1:]) if len(partes) > 1 else "general"
        return _total(alcance, facturado, pendiente, facturas, trabajos)

    if verbo == "trabajos":
        filtro_mes = " ".join(partes[1:]).upper() if len(partes) > 1 else None
        return _listar_trabajos(filtro_mes, trabajos)

    if verbo == "facturas":
        return _listar_facturas(facturado)

    if verbo == "pendientes":
        filtro_suc = partes[1] if len(partes) > 1 else None
        return _listar_pendientes(filtro_suc, pendiente)

    if verbo == "cobradas":
        return _cobradas(facturas)

    if verbo in ("sin cobrar", "sincobrar") or (verbo == "sin" and len(partes) > 1 and partes[1] == "cobrar"):
        return _sin_cobrar(facturas)

    if verbo == "cruce":
        return _cruce(facturado, facturas)

    if verbo == "buscar" and len(partes) >= 3:
        campo = partes[1]
        valor = " ".join(partes[2:])
        return _buscar(campo, valor, facturado, pendiente, facturas, trabajos)

    if verbo == "estado" and len(partes) >= 2:
        texto = " ".join(partes[1:])
        return _por_estado(texto, facturado)

    if verbo == "errores":
        return _errores(facturado, pendiente)

    # "concepto PALABRAS" → busca en la descripción de facturas y en las OC
    if verbo == "concepto" and len(partes) >= 2:
        return _buscar_concepto(" ".join(partes[1:]), facturado, facturas)

    # "debe CLIENTE" → facturas pendientes de ese cliente
    if verbo == "debe" and len(partes) >= 2:
        return _deuda_cliente(" ".join(partes[1:]), facturas)

    # "pagos CLIENTE" o "pagos CLIENTE N" (N = meses, default 1)
    if verbo == "pagos" and len(partes) >= 2:
        if partes[-1].isdigit():
            meses, cliente = int(partes[-1]), " ".join(partes[1:-1])
        else:
            meses, cliente = 1, " ".join(partes[1:])
        if cliente:
            return _pagos_cliente(cliente, meses, facturas)

    # Alias naturales: "cuánto debe X" / "cuánto nos debe X" / "cuánto pagó X N"
    if verbo in ("cuánto", "cuanto") and len(partes) >= 3:
        if "debe" in partes[1:3]:
            cliente = " ".join(partes[partes.index("debe") + 1:])
            if cliente:
                return _deuda_cliente(cliente, facturas)
        if partes[1] in ("pagó", "pago", "ha"):
            _RELLENO = ("ha", "pagado", "pagó", "pago", "en", "meses", "mes")
            toks = [t for t in partes[2:] if t not in _RELLENO]
            nums = [t for t in toks if t.isdigit()]
            meses = int(nums[-1]) if nums else 1
            cliente = " ".join(t for t in toks if not t.isdigit())
            if cliente:
                return _pagos_cliente(cliente, meses, facturas)

    return (
        f"Comando no reconocido: '{cmd}'.\n"
        "Escribe 'ayuda' para ver los comandos disponibles."
    )


def _mask_cliente(col: pd.Series, q: str) -> pd.Series:
    """
    Máscara de búsqueda de cliente en dos pasos (q ya en MAYÚSCULAS):
      1. Substring case-insensitive.
      2. Fuzzy fallback con difflib si el paso 1 no encontró nada
         (el ETL normaliza nombres; el usuario puede escribir una variante).
    """
    from difflib import get_close_matches
    mask = col.str.upper().str.contains(q, na=False)
    if mask.any():
        return mask
    unicos = [c for c in col.str.upper().dropna().unique() if c]
    cercanos = get_close_matches(q, unicos, n=5, cutoff=0.75)
    return col.str.upper().isin(cercanos)


# ─── Comandos ─────────────────────────────────────────────────────────────────

def _total(alcance: str, facturado: pd.DataFrame, pendiente: pd.DataFrame, facturas: pd.DataFrame, trabajos: pd.DataFrame) -> str:
    if alcance in ("facturado", "oc", "facturas"):
        t = facturado["monto_actual"].sum()
        return f"Total OC Facturado: ${t:,.2f}"

    if alcance in ("pendiente", "pte", "pendientes", "cotizado"):
        t = pendiente["importe"].sum()
        return f"Total Pendiente (PTE OC): ${t:,.2f}"

    if alcance in ("mensual", "reporte", "mensual reporte"):
        if facturas.empty:
            return "El reporte mensual de facturas no está cargado."
        t = facturas["total"].sum()
        cobradas = facturas[facturas["fecha_pago"].notna()]["total"].sum()
        sin_pago = facturas[facturas["fecha_pago"].isna()]["total"].sum()
        linea = "─" * 36
        return (
            f"Total Reporte Mensual  : ${t:>14,.2f}\n"
            f"  Con fecha de pago    : ${cobradas:>14,.2f}\n"
            f"  Sin fecha de pago    : ${sin_pago:>14,.2f}\n"
            f"{linea}\n"
            f"Facturas: {len(facturas)}  |  Cobradas: {facturas['fecha_pago'].notna().sum()}  |  Pendientes: {facturas['fecha_pago'].isna().sum()}"
        )

    if alcance in ("trabajos", "servicios", "casual", "casuales"):
        if trabajos.empty:
            return "El control de trabajos no está cargado."
        cobrado = trabajos["pagado"].sum()
        sin_cobrar = trabajos[trabajos["pagado"].isna()]
        return (
            f"Total trabajos: {len(trabajos)}\n"
            f"  Cobrado      : ${cobrado:>12,.2f}\n"
            f"  Sin cobrar   : {len(sin_cobrar)} trabajo(s)"
        )

    # General: cartera (facturado + pendiente)
    t_fac = facturado["monto_actual"].sum()
    t_pte = pendiente["importe"].sum()
    linea = "─" * 32
    return (
        f"Total OC Facturado : ${t_fac:>14,.2f}\n"
        f"Total PTE OC       : ${t_pte:>14,.2f}\n"
        f"{linea}\n"
        f"TOTAL CARTERA      : ${t_fac + t_pte:>14,.2f}"
    )


def _resumen(facturado: pd.DataFrame, pendiente: pd.DataFrame, facturas: pd.DataFrame, trabajos: pd.DataFrame) -> str:
    t_fac = facturado["monto_actual"].sum()
    t_pte = pendiente["importe"].sum()

    estados = (
        facturado["estado"]
        .replace("", "Sin estado")
        .value_counts()
    )
    estados_str = "\n".join(f"    {k}: {v}" for k, v in estados.items())
    prioridades = facturado[facturado["prioridad"] == "PRIORIDAD"]

    bloque_mensual = ""
    if not facturas.empty:
        t_mensual = facturas["total"].sum()
        n_cobradas = int(facturas["fecha_pago"].notna().sum())
        n_sin_pago = int(facturas["fecha_pago"].isna().sum())
        bloque_mensual = (
            f"\n"
            f"  ─── Reporte Mensual ───────────────\n"
            f"  Facturas emitidas: {len(facturas):>4}   ${t_mensual:>12,.2f}\n"
            f"    Con fecha pago : {n_cobradas:>4}\n"
            f"    Sin fecha pago : {n_sin_pago:>4}\n"
        )

    bloque_trabajos = ""
    if not trabajos.empty:
        t_cobrado = trabajos["pagado"].sum()
        n_sin_cobrar = int(trabajos["pagado"].isna().sum())
        bloque_trabajos = (
            f"\n"
            f"  ─── Trabajos Casuales ─────────────\n"
            f"  Trabajos registrados: {len(trabajos):>3}\n"
            f"    Cobrado    : ${t_cobrado:>12,.2f}\n"
            f"    Sin cobrar : {n_sin_cobrar:>3} trabajo(s)\n"
        )

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
        f"{bloque_mensual}"
        f"{bloque_trabajos}"
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


def _listar_trabajos(filtro_mes: str | None, trabajos: pd.DataFrame) -> str:
    if trabajos.empty:
        return "El control de trabajos no está cargado."

    df = trabajos.copy()
    if filtro_mes:
        df = df[df["mes"].str.upper().str.contains(filtro_mes, na=False)]
        if df.empty:
            return f"No hay trabajos registrados para '{filtro_mes}'."

    if df.empty:
        return "No hay trabajos registrados."

    resultado = _formato_trabajos(df)
    cobrado = df["pagado"].sum()
    sin_cobrar = df["pagado"].isna().sum()
    return (
        resultado
        + f"\n{'─'*60}\n"
        + f"Total: {len(df)} trabajos  |  Cobrado: ${cobrado:,.2f}  |  Sin cobrar: {sin_cobrar}"
    )


def _buscar(campo: str, valor: str, facturado: pd.DataFrame, pendiente: pd.DataFrame, facturas: pd.DataFrame, trabajos: pd.DataFrame) -> str:
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

    # Buscar por fecha (YYYY-MM o YYYY-MM-DD) en cartera y reporte mensual
    if campo in ("fecha", "date"):
        try:
            lineas = []
            if len(valor) == 7:
                target = pd.Period(valor, freq="M")
                if not facturado.empty:
                    res = facturado[facturado["fecha"].dt.to_period("M") == target]
                    if not res.empty:
                        lineas.append(f"OC Facturadas ({len(res)}) — {valor}:")
                        lineas.append(_formato_facturado(res))
                        lineas.append(f"Subtotal: ${res['monto_actual'].sum():,.2f}\n")
                if not facturas.empty:
                    res = facturas[facturas["fecha"].dt.to_period("M") == target]
                    if not res.empty:
                        lineas.append(f"Reporte Mensual ({len(res)}) — {valor}:")
                        lineas.append(_formato_facturas_mensual(res))
                        lineas.append(f"Subtotal: ${res['total'].sum():,.2f}")
            else:
                fecha = pd.to_datetime(valor)
                if not facturado.empty:
                    res = facturado[facturado["fecha"].dt.date == fecha.date()]
                    if not res.empty:
                        lineas.append(f"OC Facturadas ({len(res)}):")
                        lineas.append(_formato_facturado(res))
                        lineas.append(f"Subtotal: ${res['monto_actual'].sum():,.2f}")
            if not lineas:
                return f"No se encontraron registros para la fecha '{valor}'."
            return "\n".join(lineas)
        except (ValueError, AttributeError):
            return (
                f"Fecha no reconocida: '{valor}'.\n"
                "Usa YYYY-MM (ej: 2026-03) o YYYY-MM-DD (ej: 2026-03-15)."
            )

    # Buscar por cliente en reporte mensual y/o trabajos
    if campo in ("cliente", "client"):
        lineas = []
        q = valor.upper()

        if not facturas.empty:
            res = facturas[_mask_cliente(facturas["cliente"], q)]
            if not res.empty:
                lineas.append(f"Reporte Mensual ({len(res)} facturas):")
                lineas.append(_formato_facturas_mensual(res))
                lineas.append(f"Subtotal: ${res['total'].sum():,.2f}\n")
        if not trabajos.empty:
            res = trabajos[_mask_cliente(trabajos["cliente"], q)]
            if not res.empty:
                lineas.append(f"Trabajos ({len(res)}):")
                lineas.append(_formato_trabajos(res))
                lineas.append(f"Subtotal cobrado: ${res['pagado'].sum():,.2f}")
        if not lineas:
            return f"No se encontró ningún registro para el cliente '{valor}'."
        return "\n".join(lineas)

    # Buscar por técnico en trabajos
    if campo in ("tecnico", "técnico"):
        if trabajos.empty:
            return "El control de trabajos no está cargado."
        mask = trabajos["tecnico"].str.upper().str.contains(valor.upper(), na=False)
        resultado = trabajos[mask]
        if resultado.empty:
            return f"No se encontraron trabajos para el técnico '{valor}'."
        cobrado = resultado["pagado"].sum()
        return (
            _formato_trabajos(resultado)
            + f"\n{'─'*60}\n"
            + f"Total: {len(resultado)} trabajos  |  Cobrado: ${cobrado:,.2f}"
        )

    return (
        f"Campo de búsqueda desconocido: '{campo}'.\n"
        "Campos válidos: oc, factura, cot, suc, cliente, tecnico"
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

    dup_facturas = facturado[facturado.duplicated("factura", keep=False)]
    if not dup_facturas.empty:
        problemas.append(f"Números de factura duplicados: {dup_facturas['factura'].unique().tolist()}")

    ocs_validas = facturado[~facturado["oc"].isin(["nan", "", "NaN"])]
    dup_oc = ocs_validas[ocs_validas.duplicated("oc", keep=False)]
    if not dup_oc.empty:
        problemas.append(f"OC repetidas en más de una factura: {dup_oc['oc'].unique().tolist()}")

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


def _cobradas(facturas: pd.DataFrame) -> str:
    if facturas.empty:
        return "El reporte mensual de facturas no está cargado."
    df = facturas[facturas["fecha_pago"].notna()]
    if df.empty:
        return "No hay facturas con fecha de pago registrada en el reporte mensual."
    total = df["total"].sum()
    return (
        _formato_facturas_mensual(df)
        + f"\n{'─'*52}\nTotal cobrado: ${total:,.2f}  ({len(df)} facturas)"
    )


def _sin_cobrar(facturas: pd.DataFrame) -> str:
    if facturas.empty:
        return "El reporte mensual de facturas no está cargado."
    df = facturas[facturas["fecha_pago"].isna()]
    if df.empty:
        return "Todas las facturas del reporte mensual tienen fecha de pago."
    total = df["total"].sum()
    return (
        _formato_facturas_mensual(df)
        + f"\n{'─'*52}\nTotal sin cobrar: ${total:,.2f}  ({len(df)} facturas)"
    )


def _cruce(facturado: pd.DataFrame, facturas: pd.DataFrame) -> str:
    """Cruza los folios de cartera con el reporte mensual para detectar inconsistencias."""
    if facturas.empty:
        return "El reporte mensual de facturas no está cargado."

    folios_cartera = set(facturado["factura"].dropna().astype(int))
    en_ambos = facturas[facturas["folio"].isin(folios_cartera)]

    if en_ambos.empty:
        return (
            "No se encontraron folios comunes entre cartera y el reporte mensual.\n"
            f"  Cartera tiene {len(folios_cartera)} facturas.\n"
            f"  Reporte mensual tiene {len(facturas)} facturas (folios {int(facturas['folio'].min())}–{int(facturas['folio'].max())})."
        )

    cobradas = en_ambos[en_ambos["fecha_pago"].notna()]
    sin_pago = en_ambos[en_ambos["fecha_pago"].isna()]
    lineas = []

    if not cobradas.empty:
        lineas.append("=== FACTURAS EN CARTERA CON PAGO YA REGISTRADO ===")
        lineas.append(f"({len(cobradas)} facturas aparecen como pendientes en cartera pero tienen fecha de pago en el reporte mensual)")
        lineas.append("")
        for _, fila in cobradas.iterrows():
            fecha_pago = fila["fecha_pago"].strftime("%Y-%m-%d")
            lineas.append(
                f"  Fac {fila['folio']} | {fila['cliente']:<20} | ${fila['total']:>12,.2f} | Pago: {fecha_pago}"
            )
        lineas.append(f"{'─'*52}")
        lineas.append(f"Subtotal: ${cobradas['total'].sum():,.2f}")
        lineas.append("")

    if not sin_pago.empty:
        lineas.append("=== FACTURAS EN CARTERA SIN PAGO EN EL REPORTE MENSUAL ===")
        lineas.append(f"({len(sin_pago)} facturas que coinciden en ambos archivos y siguen sin fecha de pago)")
        lineas.append("")
        for _, fila in sin_pago.iterrows():
            fecha = fila["fecha"].strftime("%Y-%m-%d") if pd.notna(fila["fecha"]) else "sin fecha"
            lineas.append(
                f"  Fac {fila['folio']} | {fila['cliente']:<20} | ${fila['total']:>12,.2f} | Emisión: {fecha}"
            )

    if not lineas:
        lineas.append("No se encontraron coincidencias relevantes en el cruce.")

    return "\n".join(lineas)


def _buscar_concepto(termino: str, facturado: pd.DataFrame, facturas: pd.DataFrame) -> str:
    """Busca `termino` (contains, case-insensitive) en la descripción de las
    facturas del reporte mensual (columna concepto) y en las OC de la cartera
    (columna oc). Nota: facturado no tiene columna cliente, así que la OC se
    muestra como oc | monto | estado."""
    q = termino.upper()
    linea = "─" * 36
    lineas = []

    if not facturas.empty and "concepto" in facturas.columns:
        res = facturas[facturas["concepto"].astype(str).str.upper().str.contains(q, na=False)]
        if not res.empty:
            lineas.append(f'Facturas con "{termino}":')
            for _, f in res.iterrows():
                pago = "✓ cobrada" if pd.notna(f["fecha_pago"]) else "✗ pendiente"
                lineas.append(f"  Fac {f['folio']} | {str(f['cliente']):<14} | ${f['total']:>10,.2f}  | {pago}")

    if not facturado.empty and "oc" in facturado.columns:
        res = facturado[facturado["oc"].astype(str).str.upper().str.contains(q, na=False)]
        if not res.empty:
            if lineas:
                lineas.append(linea)
            lineas.append(f'OC con "{termino}":')
            for _, f in res.iterrows():
                estado = f["estado"] if f["estado"] else "—"
                lineas.append(f"  {str(f['oc']):<10} | ${f['monto_actual']:>10,.2f} | {estado}")

    if not lineas:
        return f"No se encontraron registros con '{termino}' en la descripción."
    return "\n".join(lineas)


def _deuda_cliente(cliente: str, facturas: pd.DataFrame) -> str:
    """Facturas pendientes (sin fecha_pago) de un cliente y su total adeudado."""
    if facturas.empty:
        return "El reporte mensual de facturas no está cargado."
    pendientes = facturas[facturas["fecha_pago"].isna()]
    res = pendientes[_mask_cliente(pendientes["cliente"], cliente.upper())]
    if res.empty:
        return f"No se encontraron facturas pendientes para '{cliente}'."

    nombre = res.iloc[0]["cliente"]
    linea = "─" * 36
    filas = []
    for _, f in res.iterrows():
        concepto = str(f["concepto"])
        concepto = concepto[:22] + "..." if len(concepto) > 25 else concepto
        filas.append(f"  Fac {f['folio']} | {concepto:<25} | ${f['total']:>12,.2f}")
    total = res["total"].sum()
    return (
        f"Facturas pendientes — {nombre}\n{linea}\n"
        + "\n".join(filas)
        + f"\n{linea}\nTotal pendiente: ${total:,.2f}  ({len(res)} facturas)"
    )


def _pagos_cliente(cliente: str, meses: int, facturas: pd.DataFrame) -> str:
    """Pagos (facturas con fecha_pago) de un cliente en los últimos N meses."""
    if facturas.empty:
        return "El reporte mensual de facturas no está cargado."
    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    limite = datetime.now() - relativedelta(months=meses)
    pagadas = facturas[facturas["fecha_pago"].notna() & (facturas["fecha_pago"] >= limite)]
    res = pagadas[_mask_cliente(pagadas["cliente"], cliente.upper())]
    unidad = "mes" if meses == 1 else "meses"
    if res.empty:
        return f"No se registraron pagos de '{cliente}' en los últimos {meses} {unidad}."

    nombre = res.iloc[0]["cliente"]
    res = res.sort_values("fecha_pago")
    linea = "─" * 36
    filas = [
        f"  Fac {f['folio']} | {f['fecha_pago'].strftime('%d/%m/%Y')} | ${f['total']:>12,.2f}"
        for _, f in res.iterrows()
    ]
    total = res["total"].sum()
    return (
        f"Pagos de {nombre} — últimos {meses} {unidad}\n{linea}\n"
        + "\n".join(filas)
        + f"\n{linea}\nTotal cobrado: ${total:,.2f}  ({len(res)} pagos)"
    )


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


def _formato_facturas_mensual(df: pd.DataFrame) -> str:
    """Devuelve una tabla de texto para el reporte mensual de facturas."""
    lineas = []
    for _, fila in df.iterrows():
        fecha = fila["fecha"].strftime("%Y-%m-%d") if pd.notna(fila["fecha"]) else "sin fecha"
        fecha_pago = fila["fecha_pago"].strftime("%Y-%m-%d") if pd.notna(fila["fecha_pago"]) else "sin pago "
        lineas.append(
            f"  Fac {fila['folio']} | {str(fila['cliente']):<18} | ${fila['total']:>12,.2f} | {fecha} | Pago: {fecha_pago}"
        )
    return "\n".join(lineas)


def _formato_trabajos(df: pd.DataFrame) -> str:
    """Devuelve una tabla de texto para trabajos a clientes casuales."""
    lineas = []
    for _, fila in df.iterrows():
        pagado = f"${fila['pagado']:,.2f}" if pd.notna(fila["pagado"]) else "sin cobrar"
        rep = f"Rep {fila['rep_num']}  " if fila["rep_num"] else ""
        lineas.append(
            f"  {rep}{fila['mes']:<8} | {str(fila['cliente']):<20} | {str(fila['tipo_trabajo']):<25} | {pagado}"
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
  total mensual            → Reporte mensual: cobrado vs sin cobrar
  resumen                  → Vista general con conteos y estados

  CARTERA (Excel)
  ───────────────
  facturas                 → Todas las OC facturadas
  pendientes               → Todas las cotizaciones pendientes
  pendientes [suc]         → Pendientes de una sucursal especifica
  estado [texto]           → Filtrar por estado (ej: estado aceptada)
  estado prioridad         → Solo las facturas marcadas como prioridad

  REPORTE MENSUAL
  ───────────────
  cobradas                 → Facturas con fecha de pago
  sin cobrar               → Facturas sin fecha de pago
  buscar cliente [nombre]  → Facturas de un cliente
  concepto [palabras]      → Busca en descripción de facturas y OC
  debe [cliente]           → Facturas pendientes de ese cliente
  pagos [cliente]          → Últimos 5 pagos del cliente con detalle
  pagos [cliente] N        → Pagos del cliente en últimos N meses

  CRUCE
  ─────
  cruce                    → Facturas en cartera ya pagadas en el reporte

  BUSCAR
  ──────
  buscar oc [texto]        → Por numero de OC
  buscar factura [num]     → Por numero de factura
  buscar cot [num]         → Por cotizacion pendiente
  buscar suc [num]         → Pendientes de una sucursal
  buscar cliente [nombre]  → Facturas y trabajos de un cliente
  buscar tecnico [nombre]  → Trabajos de un tecnico
  buscar fecha [YYYY-MM]   → Registros de un mes (ej: 2026-03)
  buscar fecha [YYYY-MM-DD]→ Registros de una fecha exacta

  TRABAJOS CASUALES
  ─────────────────
  trabajos                 → Todos los trabajos
  trabajos [mes]           → Trabajos de un mes (ej: enero)
  total trabajos           → Total cobrado y pendiente

  OTROS
  ─────
  errores | actualizar | ayuda
  reporte          → Genera y envía PDF mensual por email
  reporte semanal  → Genera y envía PDF semanal por email
""".strip()
