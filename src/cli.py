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

import os
import sys
from pathlib import Path
import pandas as pd
from src.loader import load_facturado, load_pendiente, load_facturas_mensual
from src.cleaner import clean_facturado, clean_pendiente, clean_facturas_mensual
from src.query_engine import run_query


def _cargar_dotenv():
    """Carga variables desde .env si existe (sin dependencia externa)."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for linea in env_path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


def _cargar_datos() -> tuple:
    """Carga y limpia todos los datos. Retorna (facturado, pendiente, facturas_mensual, advertencias)."""
    raw_facturado = load_facturado()
    raw_pendiente = load_pendiente()
    facturado, adv_fac = clean_facturado(raw_facturado)
    pendiente, adv_pte = clean_pendiente(raw_pendiente)

    facturas_mensual = pd.DataFrame()
    adv_mensual = []
    try:
        raw_mensual = load_facturas_mensual()
        facturas_mensual, adv_mensual = clean_facturas_mensual(raw_mensual)
    except FileNotFoundError:
        pass

    return facturado, pendiente, facturas_mensual, adv_fac + adv_pte + adv_mensual


def _sincronizar_drive() -> list[str]:
    """
    Descarga los Excels desde Google Drive.
    Retorna la lista de archivos descargados.
    Lanza ValueError si no está configurado DRIVE_FOLDER_ID.
    """
    from src.drive import sincronizar_desde_drive

    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if not folder_id:
        raise ValueError(
            "No está configurado DRIVE_FOLDER_ID en el archivo .env.\n"
            "Agregá la línea: DRIVE_FOLDER_ID=<id-de-tu-carpeta-de-drive>"
        )
    return sincronizar_desde_drive(folder_id)


def run():
    """Inicia la sesión interactiva del chatbot de cartera."""

    # Cargar variables de entorno desde .env si existe
    _cargar_dotenv()

    print()
    print("╔══════════════════════════════════════════════╗")
    print("         CESYM CHATBOT — Consulta de Cartera    ")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("Cargando datos del Excel...")

    # --- Carga ---
    try:
        facturado, pendiente, facturas_mensual, todas_advertencias = _cargar_datos()
    except FileNotFoundError as e:
        print()
        print(f"ERROR: {e}")
        print("Tip: usá el comando 'actualizar' para descargar los archivos desde Drive.")
        sys.exit(1)
    except ValueError as e:
        print(f"\nERROR al leer el Excel: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR inesperado al cargar el archivo: {e}")
        sys.exit(1)

    # --- Reporte de carga ---
    print(f"  ✓ OC Facturado    : {len(facturado)} registros cargados")
    print(f"  ✓ OC Pendiente    : {len(pendiente)} registros cargados")
    if not facturas_mensual.empty:
        print(f"  ✓ Reporte Mensual : {len(facturas_mensual)} facturas cargadas")

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

        if entrada.lower() == "actualizar":
            print()
            print("Conectando con Google Drive...")
            try:
                descargados = _sincronizar_drive()
                print(f"  ✓ Archivos descargados: {', '.join(descargados)}")
                print()
                print("Recargando datos...")
                facturado, pendiente, facturas_mensual, advertencias = _cargar_datos()
                print(f"  ✓ OC Facturado    : {len(facturado)} registros")
                print(f"  ✓ OC Pendiente    : {len(pendiente)} registros")
                if not facturas_mensual.empty:
                    print(f"  ✓ Reporte Mensual : {len(facturas_mensual)} facturas")
                if advertencias:
                    for adv in advertencias:
                        print(f"    ⚠ {adv}")
            except ValueError as e:
                print(f"  ERROR: {e}")
            except Exception as e:
                print(f"  ERROR al sincronizar con Drive: {e}")
            print()
            continue

        respuesta = run_query(entrada, facturado, pendiente, facturas_mensual)
        print()
        print(respuesta)
        print()
