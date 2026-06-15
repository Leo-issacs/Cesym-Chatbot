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
from src.loader import load_facturado, load_pendiente, load_facturas_mensual, load_trabajos
from src.cleaner import clean_facturado, clean_pendiente, clean_facturas_mensual, clean_trabajos
from src.query_engine import run_query

try:
    import anthropic
    from src.ai_query import traducir_a_comando
    _ANTHROPIC_DISPONIBLE = True
except ImportError:
    _ANTHROPIC_DISPONIBLE = False


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


def _iniciar_cliente_ia():
    """
    Retorna un cliente Anthropic si el SDK está instalado y la clave está configurada.
    Retorna None en caso contrario.
    """
    if not _ANTHROPIC_DISPONIBLE:
        return None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _cargar_datos() -> tuple:
    """
    Carga y limpia todos los datos.
    Retorna (facturado, pendiente, facturas_mensual, trabajos, advertencias).

    USE_POSTGRES_READS=1 → lee desde las tablas de PostgreSQL (schema chatbot). DEFAULT.
    USE_POSTGRES_READS=0 → fuerza la lectura desde los archivos Excel.

    Si la lectura de Postgres falla (p.ej. sin DATABASE_URL o BD caída), cae a Excel.
    La equivalencia de salida entre ambas rutas está respaldada por el golden master
    (tests/test_equivalencia_postgres.py).
    """
    if os.getenv("USE_POSTGRES_READS", "1") == "1":
        try:
            from src.datos_postgres import cargar_datos_desde_postgres
            datos = cargar_datos_desde_postgres()
            if datos is not None:
                return datos
            # datos is None → la conexión a Postgres falló; cae a Excel abajo.
        except Exception as e:
            print(f"[datos_postgres] Error leyendo de Postgres, usando Excel como fallback: {e}")

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

    trabajos = pd.DataFrame()
    adv_trabajos = []
    try:
        raw_trabajos = load_trabajos()
        trabajos, adv_trabajos = clean_trabajos(raw_trabajos)
    except FileNotFoundError:
        pass

    return facturado, pendiente, facturas_mensual, trabajos, adv_fac + adv_pte + adv_mensual + adv_trabajos


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

    # Iniciar cliente de IA (opcional)
    cliente_ia = _iniciar_cliente_ia()

    print()
    print("╔══════════════════════════════════════════════╗")
    print("         CESYM CHATBOT — Consulta de Cartera    ")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("Cargando datos del Excel...")

    # --- Carga ---
    try:
        facturado, pendiente, facturas_mensual, trabajos, todas_advertencias = _cargar_datos()
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
    if not trabajos.empty:
        print(f"  ✓ Trabajos        : {len(trabajos)} registros cargados")

    if cliente_ia:
        print("  ✓ IA (Claude)     : habilitada — puedes escribir en lenguaje natural")
    else:
        print("  ~ IA (Claude)     : no configurada (agrega ANTHROPIC_API_KEY en .env)")

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
                facturado, pendiente, facturas_mensual, trabajos, advertencias = _cargar_datos()
                print(f"  ✓ OC Facturado    : {len(facturado)} registros")
                print(f"  ✓ OC Pendiente    : {len(pendiente)} registros")
                if not facturas_mensual.empty:
                    print(f"  ✓ Reporte Mensual : {len(facturas_mensual)} facturas")
                if not trabajos.empty:
                    print(f"  ✓ Trabajos        : {len(trabajos)} registros")
                if advertencias:
                    for adv in advertencias:
                        print(f"    ⚠ {adv}")
            except ValueError as e:
                print(f"  ERROR: {e}")
            except Exception as e:
                print(f"  ERROR al sincronizar con Drive: {e}")
            print()
            continue

        respuesta = run_query(entrada, facturado, pendiente, facturas_mensual, trabajos)

        # Si el parser de reglas no reconoció el comando, intentar con IA
        if respuesta.startswith("Comando no reconocido") and cliente_ia:
            comando_traducido = traducir_a_comando(entrada, cliente_ia)
            if comando_traducido:
                print()
                print(f"  [IA] → \"{comando_traducido}\"")
                respuesta = run_query(comando_traducido, facturado, pendiente, facturas_mensual, trabajos)

        print()
        print(respuesta)
        print()
