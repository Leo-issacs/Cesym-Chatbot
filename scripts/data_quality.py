"""
data_quality.py
---------------
Reporte de calidad sobre los datos REALES de data/raw/. Aquí viven los chequeos
que dependen del contenido del Excel del mes (conteos, % de facturas sin fecha de
pago, hojas presentes), que ANTES estaban como tests de pytest y se rompían solos
cuando cambiaban los datos.

Esto NO es un test de pytest: es un script ejecutable que se corre a demanda.

Uso:
    python -X utf8 scripts/data_quality.py

Salida: un reporte por consola. Código de salida 0 si pudo leer la cartera,
1 si no encontró el Excel real (descárgalo con 'actualizar' o súbelo a data/raw/).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # tildes en Windows

from src.loader import (
    _resolver_ruta_cartera,
    load_facturado,
    load_pendiente,
    load_facturas_mensual,
    load_trabajos,
)
from src.cleaner import (
    clean_facturado,
    clean_pendiente,
    clean_facturas_mensual,
    clean_trabajos,
)

LINEA = "─" * 56


def _verificar_hojas(path: Path) -> None:
    """Chequeo estructural del Excel real: hojas esperadas (antes en test_loader)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    hojas = wb.sheetnames
    wb.close()
    print(f"Hojas: {hojas}")
    for esperada in ("OC FACTURADO", "PTE OC 25-26"):
        marca = "OK" if esperada in hojas else "FALTA"
        print(f"  [{marca}] {esperada}")


def main() -> int:
    print(LINEA)
    print("  REPORTE DE CALIDAD DE DATOS — CESYM")
    print(LINEA)

    try:
        cartera = _resolver_ruta_cartera()
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        print("Sin Excel real no hay nada que medir. Usa 'actualizar' o copia el "
              "archivo a data/raw/.")
        return 1

    print(f"Archivo de cartera: {cartera.name}\n")
    _verificar_hojas(cartera)

    # ── Cartera (OC FACTURADO + PTE OC) ──────────────────────────────
    facturado, adv_fac = clean_facturado(load_facturado())
    pendiente, adv_pte = clean_pendiente(load_pendiente())

    print(f"\n{LINEA}\nCONTEOS\n{LINEA}")
    print(f"  OC facturadas : {len(facturado)}")
    print(f"  Cotiz. pend.  : {len(pendiente)}")

    # ── Reporte mensual (opcional) ───────────────────────────────────
    advertencias = list(adv_fac) + list(adv_pte)
    try:
        mensual, adv_men = clean_facturas_mensual(load_facturas_mensual())
        advertencias += adv_men
        print(f"  Facturas mes  : {len(mensual)}")
        if len(mensual) > 0:
            pct_sin_pago = 100.0 * mensual["fecha_pago"].isna().mean()
            total = mensual["total"].sum()
            print(f"\n  Facturas sin fecha de pago : {pct_sin_pago:.1f}%")
            print(f"  Monto total facturado      : ${total:,.2f}")
    except FileNotFoundError:
        print("  Facturas mes  : (sin archivo reporteMensual en data/raw/)")

    # ── Trabajos (opcional) ──────────────────────────────────────────
    try:
        trabajos, adv_tra = clean_trabajos(load_trabajos())
        advertencias += adv_tra
        print(f"  Trabajos      : {len(trabajos)}")
    except FileNotFoundError:
        print("  Trabajos      : (sin archivo CONTROL en data/raw/)")

    # ── Advertencias de calidad ──────────────────────────────────────
    print(f"\n{LINEA}\nADVERTENCIAS DE CALIDAD ({len(advertencias)})\n{LINEA}")
    if advertencias:
        for adv in advertencias:
            print(f"  ! {adv}")
    else:
        print("  Sin advertencias.")

    print(f"\n{LINEA}\n  OK — reporte generado.\n{LINEA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
