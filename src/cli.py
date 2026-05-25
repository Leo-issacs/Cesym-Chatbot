"""
cli.py
------
Responsabilidad única: manejar la interacción con el usuario en consola.

Flujo:
  1. Carga el Excel usando loader.py
  2. Limpia los datos usando cleaner.py
  3. Muestra un resumen de carga (cuántos registros, advertencias)
  4. Entra en un bucle donde el usuario escribe comandos
  5. Cada comando pasa por query_engine.py y se imprime la respuesta
  6. El bucle termina cuando el usuario escribe 'salir'
"""

import sys
from src.loader import load_facturado, load_pendiente
from src.cleaner import clean_facturado, clean_pendiente
from src.query_engine import run_query


def run():
    """Inicia la sesión interactiva del chatbot de cartera."""

    print()
    print("╔══════════════════════════════════════════════╗")
    print("         CESYM CHATBOT — Consulta de Cartera    ")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("Cargando datos del Excel...")

    # --- Carga ---
    try:
        raw_facturado = load_facturado()
        raw_pendiente = load_pendiente()
    except FileNotFoundError:
        print()
        print("ERROR: No se encontró el archivo Excel.")
        print("Asegúrate de que el archivo esté en: data/raw/CARTERA AL 11032026.xlsx")
        sys.exit(1)
    except ValueError as e:
        print(f"\nERROR al leer el Excel: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR inesperado al cargar el archivo: {e}")
        sys.exit(1)

    # --- Limpieza ---
    facturado, adv_fac = clean_facturado(raw_facturado)
    pendiente, adv_pte = clean_pendiente(raw_pendiente)

    # --- Reporte de carga ---
    print(f"  ✓ OC Facturado : {len(facturado)} registros cargados")
    print(f"  ✓ OC Pendiente : {len(pendiente)} registros cargados")

    todas_advertencias = adv_fac + adv_pte
    if todas_advertencias:
        print()
        print("  Advertencias de calidad de datos:")
        for adv in todas_advertencias:
            print(f"    ⚠ {adv}")

    print()
    print("Escribe 'ayuda' para ver los comandos disponibles.")
    print("Escribe 'salir' para cerrar.")
    print()

    # --- Bucle principal ---
    while True:
        try:
            entrada = input("cartera> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCerrando sesión...")
            break

        if not entrada:
            continue

        if entrada.lower() in ("salir", "exit", "quit", "q"):
            print("Hasta luego.")
            break

        respuesta = run_query(entrada, facturado, pendiente)
        print()
        print(respuesta)
        print()
