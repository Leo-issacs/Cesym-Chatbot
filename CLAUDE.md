# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Cesym Chatbot** — proyecto en Python para construir un agente interno que pueda consultar y, en versiones futuras, modificar archivos Excel relacionados con cartera, facturas, órdenes de compra, cotizaciones pendientes y trabajos realizados.

El objetivo final es que el agente pueda responder consultas desde WhatsApp, pero la primera versión debe funcionar de forma local desde consola, sin conectarse todavía a WhatsApp ni modificar archivos originales.

> **Estado actual (no el de este "Project Overview" original).** El proyecto ya
> superó la primera versión local: hoy corre un webhook **FastAPI desplegado en
> Railway** que responde por **WhatsApp vía Twilio**, sincroniza Excel desde
> Google Drive, genera reportes y tiene una **capa PostgreSQL** a medio migrar
> (apagada por flags). El detalle real del sistema está en
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) y
> [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md). Las secciones de "Contexto" y
> "Objetivo inicial" de abajo se conservan como contexto histórico de la visión
> original.

## Contexto del proyecto

Este proyecto busca crear un chatbot/agente para automatizar consultas sobre archivos Excel usados manualmente en la empresa.

El primer Excel conocido es `CARTERA AL 11032026.xlsx`. Este archivo contiene información relacionada con:
- Facturas.
- Órdenes de compra.
- Montos facturados.
- Fechas.
- Estados como aceptada, prioridad o pendiente.
- Cotizaciones pendientes de orden de compra.

El archivo tiene hojas como:
- `OC FACTURADO`: contiene facturas, órdenes de compra, montos, fechas y observaciones.
- `PTE OC 25-26`: contiene cotizaciones pendientes de OC, sucursal, importe y concepto.
- `Hoja1`: aparentemente vacía.

El segundo Excel todavía no está disponible, pero probablemente contendrá información de trabajos realizados por tienda o sucursal. Más adelante se deberá cruzar la información de ambos archivos.

## Objetivo inicial

Construir primero una versión local que pueda:

1. Leer el Excel.
2. Limpiar y normalizar los datos.
3. Ignorar filas vacías, encabezados manuales y filas de totales.
4. Convertir fechas de Excel a fechas legibles.
5. Permitir consultas desde consola.
6. Generar resúmenes.
7. Detectar errores o inconsistencias.
8. No modificar el archivo original.

## Reglas importantes

- No modificar ningún archivo Excel original sin confirmación explícita.
- Antes de cualquier modificación futura, crear un backup automático.
- No borrar registros desde el chatbot.
- Separar claramente la lectura de Excel, limpieza de datos, consultas, validaciones, chatbot y logs.
- Trabajar por versiones pequeñas.
- Priorizar código claro, modular y fácil de entender.
- Documentar en español.
- Explicar qué archivo se va a crear o modificar antes de hacer cambios grandes.
- No crear una arquitectura demasiado compleja al inicio.
- Mantener actualizado el archivo `README.md`.

## Environment

- Python 3.11.9
- Virtual environment: `venv_Cesym_Chatbot/`
- Activate venv: `.\venv_Cesym_Chatbot\Scripts\Activate.ps1` PowerShell
- Operating system: Windows
- Editor: VS Code

## Setup

```powershell
# Activate the virtual environment
.\venv_Cesym_Chatbot\Scripts\Activate.ps1

# Install dependencies once a requirements.txt exists
pip install -r requirements.txt
```

> `requirements.txt` está pineado con `==` (builds reproducibles en Railway).
> `requirements.in` documenta las deps directas y su intención. Las deps **solo
> de ETL** (`fuzzywuzzy`, `python-Levenshtein`) NO están en `requirements.txt`;
> viven pineadas en **`requirements-etl.txt`**. Instálalas solo si vas a correr el
> ETL: `pip install -r requirements-etl.txt`. Ver
> [docs/DATA_FLOW.md → §3](docs/DATA_FLOW.md) para refrescar Postgres.

## Cómo correr

Activa el venv primero (`.\venv_Cesym_Chatbot\Scripts\Activate.ps1`).

### Webhook (lo que corre en Railway)

```powershell
# Desarrollo local con autoreload (expón con ngrok para que Twilio llegue):
uvicorn src.webhook:app --reload --port 8000

# Igual que producción (Procfile):
uvicorn src.webhook:app --host 0.0.0.0 --port $env:PORT
```
Health check: `GET /` devuelve `{status, registros, ia}`. Webhook de Twilio: `POST /webhook`.

### CLI local (consola interactiva)

```powershell
python main.py
```
Abre el REPL `cartera>`. Escribe `ayuda` para ver comandos, `salir` para cerrar,
`actualizar` para bajar los Excel de Drive.

### Tests

```powershell
pytest                       # corre toda la suite
pytest tests/test_seguridad.py   # único test hermético (no necesita Excel)
```

⚠ **Estado real de los tests (ver Deuda documentada):**
- `tests/test_loader.py` rompe la **colección** de pytest: importa `EXCEL_PATH`,
  que ya no existe en `loader.py`. Hasta arreglarlo, corre con
  `pytest --ignore=tests/test_loader.py` o deselecciónalo.
- `test_cleaner`, `test_queries`, `test_validator` **no son herméticos**: sus
  fixtures (`conftest.py`) leen un `CARTERA*.xlsx` real de `data/raw/` (gitignored).
  Sin ese Excel, fallan. Consigue el archivo (Drive / `actualizar`) antes de correrlos.

## Convenciones

- **Commits**: Conventional Commits **en español**. Formato
  `tipo: descripción` (ej. `feat: lectura de datos desde Postgres`,
  `fix: búsqueda de cliente con fallback fuzzy`, `chore: pin de dependencias`,
  `docs: arquitectura y flujo de datos`). Tipos en uso: `feat`, `fix`, `chore`,
  `docs`. El cuerpo y la documentación también van en español.
- **Tamaño de PR**: ≤ **400 líneas de código de producción** por PR. La
  documentación, los tests y los archivos generados no cuentan contra ese límite,
  pero mantén el PR enfocado en un solo cambio.
- **Tests en el mismo PR**: todo cambio de comportamiento entra **con sus tests**
  en el mismo PR. No se separan en un PR posterior.
- **Reglas de datos** (del proyecto, siguen vigentes): no modificar Excel
  originales sin confirmación, backup automático antes de cualquier escritura, el
  bot no borra registros sin confirmación del usuario, documentar en español.

## Variables de entorno

Plantilla completa en `.env.example`. En local se cargan desde `.env`
(`cli._cargar_dotenv()`); en Railway se definen en el panel. Tabla de lo que el
**código realmente lee**:

| Variable | Default | Usada por | Para qué |
|---|---|---|---|
| `DATABASE_URL` | — | `db_postgres.py` | Conexión runtime a Postgres (Supabase: pooler 6543). |
| `DATABASE_MIGRATION_URL` | = `DATABASE_URL` | `db_postgres.py` | DDL/migraciones (Supabase: directo 5432). |
| `USE_POSTGRES_READS` | `0` | `cli.py` | `1` = lee datos de Postgres en vez de Excel. |
| `USE_POSTGRES_SESSIONS` | `0` | `sesiones.py` | `1` = sesiones en `chatbot.sesiones_bot` en vez de JSON. |
| `DRIVE_FOLDER_ID` | — | `cli`, `webhook`, `escritor`, `logger`, `sesiones` | Carpeta de Drive con los Excel. Sin esto, no hay sync. |
| `DRIVE_BACKUPS_FOLDER_ID` | — | `escritor.py` | Carpeta de Drive para backups de Excel. |
| `DRIVE_REPORTS_FOLDER_ID` | — | `webhook.py` | Carpeta de Drive para reportes generados. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | `drive.py` | JSON de Service Account (auth preferida en cloud). |
| `GOOGLE_CREDENTIALS_JSON` / `GOOGLE_TOKEN_JSON` | — | `drive.py` | OAuth en base64 (fallback cloud). |
| `GOOGLE_CREDENTIALS_PATH` | `.credentials/credentials.json` | `drive.py` | Ruta al OAuth `credentials.json` (fallback local). |
| `ANTHROPIC_API_KEY` | — | `cli`, `webhook` | Habilita el fallback de lenguaje natural (Claude Haiku). |
| `TWILIO_AUTH_TOKEN` | — | `seguridad.py` | Valida la firma `X-Twilio-Signature`. |
| `NUMEROS_AUTORIZADOS` | vacío (no filtra) | `seguridad.py` | Whitelist de números, separados por coma. |
| `ENFORCE_TWILIO_SIGNATURE` | `0` | `seguridad.py` | `1` = bloquea (403) firmas inválidas. |
| `ENFORCE_WHITELIST` | `0` | `seguridad.py` | `1` = bloquea números fuera de la whitelist. |
| `SYNC_INTERVALO_HORAS` | `6` | `webhook.py` | Cada cuántas horas re-sincroniza Drive en background. |
| `RAILWAY_PUBLIC_DOMAIN` | `localhost:8000` | `seguridad`, `webhook` | Dominio público (lo inyecta Railway). URL de firma y de reportes. |
| `PORT` | — | `Procfile`/uvicorn | Puerto (lo inyecta Railway). |
| `CARTERA_PATH` / `FACTURAS_PATH` / `TRABAJOS_PATH` | autodetección en `data/raw/` | `loader.py` | Fuerza la ruta de cada Excel (no está en `.env.example`). |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `REPORT_RECIPIENTS` | — | `reporte.py` | Envío de reportes por email (no lo dispara el comando `reporte` del webhook). |

> `.env.example` también lista `TWILIO_ACCOUNT_SID` y `TWILIO_WHATSAPP_NUMBER`,
> pero el código **no los lee** (son referencia para configurar Twilio).