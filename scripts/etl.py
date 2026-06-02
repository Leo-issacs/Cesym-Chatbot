"""
etl.py
------
Pipeline ETL completo: extrae los 3 archivos Excel de la empresa,
los limpia y los unifica en datasets exportables.

Uso:
    python scripts/etl.py

Salida (en data/reportes/etl_YYYYMMDD/):
    cartera_oc_facturado.csv  → OC facturadas limpias
    cartera_oc_pendiente.csv  → Cotizaciones pendientes de OC
    facturas.csv              → Reporte mensual de facturas limpio
    cartera_unificada.csv     → JOIN de CARTERA + FACTURAS (dataset principal)
    facturas_sin_oc.csv       → Facturas sin respaldo en cartera (para auditoría)
    etl_resumen.txt           → Resumen de ejecución con advertencias
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Permite ejecutar desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.loader import load_facturado, load_pendiente, load_facturas_mensual, load_trabajos
from src.cleaner import clean_facturado, clean_pendiente, clean_facturas_mensual, clean_trabajos


# ─── Configuración ────────────────────────────────────────────────────────────

REPORTES_DIR = Path(__file__).parent.parent / "data" / "reportes"


# ─── Extracción ───────────────────────────────────────────────────────────────

def extraer() -> dict:
    """
    Paso E: carga los datos RAW sin modificar.
    Retorna un dict con los DataFrames crudos.
    """
    print("  Extrayendo CARTERA (OC Facturado)...")
    raw_facturado = load_facturado()

    print("  Extrayendo CARTERA (PTE OC Pendiente)...")
    raw_pendiente = load_pendiente()

    print("  Extrayendo FACTURAS (Reporte Mensual)...")
    raw_facturas = load_facturas_mensual()

    raw_trabajos = pd.DataFrame()
    try:
        print("  Extrayendo CONTROL DE INSTALACIONES...")
        raw_trabajos = load_trabajos()
    except FileNotFoundError:
        print("  [!] CONTROL DE INSTALACIONES no encontrado — se omite.")

    return {
        "facturado": raw_facturado,
        "pendiente": raw_pendiente,
        "facturas": raw_facturas,
        "trabajos": raw_trabajos,
    }


# ─── Transformación ───────────────────────────────────────────────────────────

def transformar(raw: dict) -> tuple[dict, list[str]]:
    """
    Paso T: limpia y transforma cada dataset.
    Retorna (dict de DataFrames limpios, lista de advertencias acumuladas).
    """
    advertencias = []

    print("  Limpiando CARTERA (OC Facturado)...")
    facturado, adv = clean_facturado(raw["facturado"])
    advertencias.extend(f"[CARTERA-OC] {a}" for a in adv)

    print("  Limpiando CARTERA (PTE OC Pendiente)...")
    pendiente, adv = clean_pendiente(raw["pendiente"])
    advertencias.extend(f"[CARTERA-PTE] {a}" for a in adv)

    print("  Limpiando FACTURAS (Reporte Mensual)...")
    facturas, adv = clean_facturas_mensual(raw["facturas"])
    advertencias.extend(f"[FACTURAS] {a}" for a in adv)

    trabajos = pd.DataFrame()
    if not raw["trabajos"].empty:
        print("  Limpiando CONTROL DE INSTALACIONES...")
        trabajos, adv = clean_trabajos(raw["trabajos"])
        advertencias.extend(f"[CONTROL] {a}" for a in adv)

    limpio = {
        "facturado": facturado,
        "pendiente": pendiente,
        "facturas": facturas,
        "trabajos": trabajos,
    }
    return limpio, advertencias


# ─── Unificación ──────────────────────────────────────────────────────────────

def unificar(limpio: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Une CARTERA (OC Facturado) con FACTURAS usando el número de factura/folio.

    Retorna:
        cartera_unificada  → todas las OC de cartera enriquecidas con datos de factura
        facturas_sin_oc    → facturas del reporte mensual sin respaldo en cartera
    """
    facturado = limpio["facturado"]
    facturas = limpio["facturas"]

    # Left join: partimos de CARTERA y agregamos info de FACTURAS cuando coinciden
    merged = facturado.merge(
        facturas[["folio", "cliente", "concepto", "total", "fecha", "fecha_pago"]],
        left_on="factura",
        right_on="folio",
        how="left",
        suffixes=("_cartera", "_factura"),
    )

    cartera_unificada = pd.DataFrame({
        "factura":       merged["factura"],
        "oc":            merged["oc"],
        "monto_cartera": merged["monto_actual"],
        "prioridad":     merged["prioridad"],
        "estado_oc":     merged["estado"],
        "fecha_oc":      merged["fecha_cartera"],
        "cliente":       merged["cliente"],
        "concepto":      merged["concepto"],
        "total_factura": merged["total"],
        "fecha_emision": merged["fecha_factura"],
        "fecha_pago":    merged["fecha_pago"],
        "estado_pago":   merged["fecha_pago"].apply(
            lambda f: "COBRADA" if pd.notna(f) else "PENDIENTE"
        ),
    })

    # Diferencia: facturas que no están en cartera
    folios_cartera = set(facturado["factura"].dropna().astype(int))
    facturas_sin_oc = facturas[~facturas["folio"].isin(folios_cartera)].copy()
    facturas_sin_oc = facturas_sin_oc.rename(columns={"folio": "factura"})

    return cartera_unificada, facturas_sin_oc


# ─── Carga ────────────────────────────────────────────────────────────────────

def cargar(limpio: dict, cartera_unificada: pd.DataFrame, facturas_sin_oc: pd.DataFrame, advertencias: list[str]) -> Path:
    """
    Paso L: guarda todos los datasets limpios y el unificado en data/reportes/.
    Crea un subdirectorio con la fecha de ejecución.
    Retorna la ruta del directorio de salida.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    salida = REPORTES_DIR / f"etl_{timestamp}"
    salida.mkdir(parents=True, exist_ok=True)

    limpio["facturado"].to_csv(salida / "cartera_oc_facturado.csv", index=False, encoding="utf-8-sig")
    print(f"  → cartera_oc_facturado.csv  ({len(limpio['facturado'])} filas)")

    limpio["pendiente"].to_csv(salida / "cartera_oc_pendiente.csv", index=False, encoding="utf-8-sig")
    print(f"  → cartera_oc_pendiente.csv  ({len(limpio['pendiente'])} filas)")

    limpio["facturas"].to_csv(salida / "facturas.csv", index=False, encoding="utf-8-sig")
    print(f"  → facturas.csv              ({len(limpio['facturas'])} filas)")

    cartera_unificada.to_csv(salida / "cartera_unificada.csv", index=False, encoding="utf-8-sig")
    print(f"  → cartera_unificada.csv     ({len(cartera_unificada)} filas)")

    facturas_sin_oc.to_csv(salida / "facturas_sin_oc.csv", index=False, encoding="utf-8-sig")
    print(f"  → facturas_sin_oc.csv       ({len(facturas_sin_oc)} filas)")

    if not limpio["trabajos"].empty:
        limpio["trabajos"].to_csv(salida / "trabajos.csv", index=False, encoding="utf-8-sig")
        print(f"  → trabajos.csv              ({len(limpio['trabajos'])} filas)")

    _escribir_resumen(salida, limpio, cartera_unificada, facturas_sin_oc, advertencias)
    print(f"  → etl_resumen.txt")

    return salida


def _escribir_resumen(salida: Path, limpio: dict, cartera_unificada: pd.DataFrame, facturas_sin_oc: pd.DataFrame, advertencias: list[str]):
    """Genera el archivo de resumen de la ejecución ETL."""
    fac = limpio["facturado"]
    pte = limpio["pendiente"]
    fact = limpio["facturas"]
    trab = limpio["trabajos"]

    cobradas = cartera_unificada[cartera_unificada["estado_pago"] == "COBRADA"]
    pendientes_pago = cartera_unificada[cartera_unificada["estado_pago"] == "PENDIENTE"]

    lineas = [
        f"=== RESUMEN ETL — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===",
        "",
        "REGISTROS PROCESADOS",
        "─" * 40,
        f"  CARTERA OC Facturado : {len(fac):>5} registros  ${fac['monto_actual'].sum():>14,.2f}",
        f"  CARTERA OC Pendiente : {len(pte):>5} registros  ${pte['importe'].sum():>14,.2f}",
        f"  FACTURAS (mensual)   : {len(fact):>5} facturas   ${fact['total'].sum():>14,.2f}",
    ]
    if not trab.empty:
        lineas.append(f"  CONTROL Trabajos     : {len(trab):>5} registros")
    lineas += [
        "",
        "DATASET UNIFICADO (CARTERA + FACTURAS)",
        "─" * 40,
        f"  Total facturas en cartera  : {len(cartera_unificada)}",
        f"  Cobradas (con fecha pago)  : {len(cobradas)}  ${cobradas['total_factura'].sum():>14,.2f}",
        f"  Pendientes (sin pago)      : {len(pendientes_pago)}  ${pendientes_pago['monto_cartera'].sum():>14,.2f}",
        f"  Facturas sin OC en cartera : {len(facturas_sin_oc)}",
        "",
    ]

    if advertencias:
        lineas.append("ADVERTENCIAS DE CALIDAD")
        lineas.append("─" * 40)
        for adv in advertencias:
            lineas.append(f"  ⚠ {adv}")
    else:
        lineas.append("No se detectaron advertencias de calidad.")

    (salida / "etl_resumen.txt").write_text("\n".join(lineas), encoding="utf-8")


# ─── Pipeline principal ───────────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print()
    print("=" * 44)
    print("        PIPELINE ETL -- CESYM HVAC")
    print("=" * 44)

    print()
    print("[1/4] EXTRACCIÓN")
    raw = extraer()

    print()
    print("[2/4] TRANSFORMACIÓN")
    limpio, advertencias = transformar(raw)

    print()
    print("[3/4] UNIFICACIÓN")
    cartera_unificada, facturas_sin_oc = unificar(limpio)
    cobradas = (cartera_unificada["estado_pago"] == "COBRADA").sum()
    print(f"  Facturas en cartera cruzadas con reporte: {len(cartera_unificada)}")
    print(f"  Con fecha de pago registrada: {cobradas}")
    print(f"  Sin fecha de pago:            {len(cartera_unificada) - cobradas}")
    print(f"  Facturas sin OC en cartera:   {len(facturas_sin_oc)}")

    print()
    print("[4/4] CARGA")
    salida = cargar(limpio, cartera_unificada, facturas_sin_oc, advertencias)

    duracion = (datetime.now() - inicio).total_seconds()
    print()
    print(f"ETL completado en {duracion:.1f}s")
    print(f"Archivos guardados en: {salida}")

    if advertencias:
        print()
        print(f"  {len(advertencias)} advertencia(s) de calidad — ver etl_resumen.txt")
    print()


if __name__ == "__main__":
    main()
