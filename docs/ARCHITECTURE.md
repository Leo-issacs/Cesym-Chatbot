# Arquitectura — Cesym Chatbot

> Documento de **ingeniería inversa**: describe lo que el código HACE hoy, no lo
> ideal ni lo planeado. Si encuentras una diferencia con la realidad, corrígela
> aquí. Las divergencias conocidas entre código y documentación están en la
> sección [Deuda documentada](#deuda-documentada) al final.

Generado leyendo `src/`, `scripts/`, `tests/` y `Procfile`.

---

## 1. Visión de 30 segundos

Bot que responde consultas sobre cartera/facturas/trabajos por **WhatsApp**
(vía Twilio → FastAPI) y también desde una **CLI local**. Los datos viven en
archivos **Excel** en Google Drive; se descargan, se limpian en memoria con
pandas y se consultan con un motor de reglas (`query_engine.py`), con un
fallback opcional a Claude para lenguaje natural.

Hay una **migración a PostgreSQL a medio camino**: existe toda la capa de
lectura desde Postgres y de sesiones en Postgres, pero está **apagada por flags**
(`USE_POSTGRES_READS`, `USE_POSTGRES_SESSIONS`) y el camino para *refrescar* esos
datos en Postgres está roto (ver [DATA_FLOW.md](./DATA_FLOW.md) y Deuda).

---

## 2. Qué arranca en cada entorno

| Entorno | Entrypoint | Qué corre |
|---|---|---|
| **Railway (cloud)** | `Procfile` → `uvicorn src.webhook:app` | Servidor FastAPI. Único proceso en producción. |
| **Local (consola)** | `python main.py` → `src.cli.run()` | REPL interactivo `cartera>`. |
| **Local (scripts)** | `python scripts/<x>.py` | ETL, migración, sync, utilidades. Nunca corren en Railway. |

`Procfile`:
```
web: uvicorn src.webhook:app --host 0.0.0.0 --port $PORT
```

**Implicación clave:** todo lo que NO esté en la cadena de import de
`src/webhook.py` no se ejecuta en producción. Eso incluye **todo `scripts/`**,
`main.py` y `src/cli.py:run()` (la función `run()` del REPL; el módulo `cli` sí
se importa en producción por sus helpers — ver abajo).

---

## 3. Módulos y responsabilidades

### 3.1 Runtime de producción (importados por `webhook.py`)

| Módulo | Responsabilidad |
|---|---|
| `src/webhook.py` | Servidor FastAPI. Endpoints `/` (health), `/webhook` (Twilio), `/reportes/{file}`. Mantiene los 4 DataFrames en estado global, enruta comandos, maneja sesiones, dispara sync periódico de Drive. |
| `src/cli.py` | El REPL `run()` es solo local, pero `webhook.py` **reutiliza** sus helpers: `_cargar_dotenv`, `_cargar_datos` (decide Excel vs Postgres según flag), `_sincronizar_drive`. |
| `src/query_engine.py` | Motor de consultas por reglas. `run_query()` parsea el texto y despacha (`total`, `resumen`, `buscar`, `cruce`, `errores`…). Solo lee DataFrames, no los modifica. |
| `src/loader.py` | Lectura RAW de Excel (sin limpiar). Resuelve qué archivo usar (env var o el más reciente en `data/raw/`). Detecta encabezados dinámicos. |
| `src/cleaner.py` | Limpieza/normalización de los DataFrames RAW: tipos, fechas, descarte de filas de totales, advertencias de calidad. |
| `src/datos_postgres.py` | Alternativa a loader+cleaner: lee los 4 DataFrames desde Postgres con las **mismas columnas** que produce `cleaner.py`. Solo se usa con `USE_POSTGRES_READS=1`. |
| `src/db_postgres.py` | Conexión SQLAlchemy a Postgres, DDL del schema `chatbot`, engines de runtime vs migración, reset de secuencias. |
| `src/sesiones.py` | Máquina de estados de conversaciones multi-turno (agregar/editar/borrar trabajo). Persiste en `data/sesiones.json` o en Postgres según `USE_POSTGRES_SESSIONS`. |
| `src/sesiones_pg.py` | Backend Postgres de sesiones (tabla `chatbot.sesiones_bot`, JSONB). Inactivo por defecto. |
| `src/escritor.py` | **Única** ruta de escritura de datos del bot: modifica el Excel de trabajos, hace backup y sube a Drive. No escribe a Postgres. |
| `src/seguridad.py` | Validación de firma Twilio + whitelist de números. Modo log-only por defecto (ver flags). |
| `src/logger.py` | Log de consultas en `data/logs/queries.log` (enmascara números, retención 30 días, sube a Drive). |
| `src/ai_query.py` | Fallback de lenguaje natural con Claude Haiku. Traduce texto libre → comando. Solo se invoca si el parser de reglas no reconoció el comando y hay `ANTHROPIC_API_KEY`. |
| `src/drive.py` | Toda la comunicación con Google Drive: auth (Service Account o OAuth), listar/descargar/subir. |
| `src/reporte.py` | Genera reporte HTML/PDF con métricas y gráficas (matplotlib/reportlab). Incluye envío por email (Gmail). El webhook usa solo `generar_html`. |

### 3.2 Solo local — `scripts/` (nunca en Railway)

| Script | Qué hace | Estado |
|---|---|---|
| `scripts/cargar_bd.py` | **ETL Excel → SQLite** (`data/cesym.db`). Normaliza clientes con fuzzy matching. | OK — requiere `requirements-etl.txt` (fuzzywuzzy); guard con mensaje claro si falta. |
| `scripts/migrar_sqlite_a_postgres.py` | Migración idempotente SQLite → Postgres. Preserva IDs, resetea secuencias. | OK — lee `cesym.db` (lo produce `cargar_bd.py`). Requiere `DATABASE_URL`. |
| `scripts/etl.py` | ETL alternativo Excel → CSVs en `data/reportes/`. No toca BD. | OK (usa loader/cleaner). |
| `scripts/sync_drive.py` | Descarga los Excel de Drive a `data/raw/`. | OK. |
| `scripts/clasificador_conceptos.py` | Clasificador NLP (scikit-learn) de la columna CONCEPTO en 5 categorías HVAC. | Standalone. |
| `scripts/check_drive.py` | Smoke test de sincronización con Drive. | OK. |
| `scripts/export_credenciales.py` | Genera los base64 de credenciales Google para pegar en Railway. | OK. |
| `scripts/run_manual_tests.py` | Pruebas manuales + reporte de calidad sin pytest. | ⚠ **ROTO** — importa `EXCEL_PATH` inexistente. Ver Deuda. |
| `autenticar_drive.py` (raíz) | Auth OAuth de un solo uso (abre navegador). | Local. |

### 3.3 `src/db.py` (SQLite) — fuera del runtime del bot

Define el esquema SQLite y utilidades de conexión. Lo usa solo `scripts/cargar_bd.py`.
El bot en runtime **no** toca SQLite: lee de Excel (default) o de Postgres (flag).
SQLite es únicamente un paso intermedio del ETL y la red de seguridad de la migración.

---

## 4. Estado de los flags

Los cuatro flags se leen como booleanos de entorno. Para los de seguridad, solo
`1`/`true`/`yes`/`on` activan; los de datos comparan estrictamente contra `"1"`.

| Flag | Default | Leído en | Efecto cuando = 1 |
|---|---|---|---|
| `USE_POSTGRES_READS` | `0` (Excel) | `src/cli.py:65` | `_cargar_datos()` lee los 4 DataFrames desde Postgres (`datos_postgres.py`) en vez de Excel. Si falla, cae a Excel como fallback. |
| `USE_POSTGRES_SESSIONS` | `0` (archivo) | `src/sesiones.py:19` | Las sesiones multi-turno se guardan/leen en `chatbot.sesiones_bot` (Postgres) en vez de `data/sesiones.json`. Sobrevive redeploys de Railway. |
| `ENFORCE_TWILIO_SIGNATURE` | `0` (log-only) | `src/seguridad.py:44` | Bloquea con 403 las peticiones cuya firma `X-Twilio-Signature` no valida. Con 0 solo registra que *bloquearía*. |
| `ENFORCE_WHITELIST` | `0` (log-only) | `src/seguridad.py:48` | Bloquea con 403 los números fuera de `NUMEROS_AUTORIZADOS`. Con 0 solo registra. Si la whitelist está vacía, no filtra a nadie aunque el flag esté en 1. |

**Diseño "log-only":** ambas capas de seguridad SIEMPRE se evalúan y registran en
stdout (logs de Railway) cuando algo no pasaría, pero no bloquean hasta activar su
flag. Permite observar durante días que no se rechazan mensajes legítimos antes de
prender el enforcement real.

**Postura actual (lo que está prendido en producción):** los cuatro están en su
default (`0`). El bot lee de Excel, guarda sesiones en archivo y la seguridad está
en observación. La capa Postgres existe pero está dormida.

---

## 5. Diagrama de arranque (lifespan de FastAPI)

`src/webhook.py:lifespan()` al arrancar:

1. `_cargar_dotenv()` — carga `.env` si existe.
2. `init_credenciales_desde_env()` — escribe credenciales Google desde env (cloud).
3. Si hay `DRIVE_FOLDER_ID`: `_sincronizar_drive()` — baja los Excel de Drive.
4. Restaura `sesiones.json` y `queries.log` desde Drive (sobreviven redeploys).
5. `_recargar_datos()` — carga los 4 DataFrames (Excel o Postgres según flag).
6. `_init_ia()` — inicializa cliente Claude si hay `ANTHROPIC_API_KEY`.
7. Lanza tarea en background: sync de Drive cada `SYNC_INTERVALO_HORAS` (default 6).

Cada paso 2-7 está envuelto en `try/except` que traga errores: el servidor
**arranca aunque no haya datos ni Drive** (el usuario puede mandar `actualizar`).

---

## 6. Variables de entorno

Ver la tabla completa en [CLAUDE.md](../CLAUDE.md#variables-de-entorno).
Plantilla en `.env.example`.

---

## Deuda documentada

Divergencias detectadas entre lo que el código hace y lo que dicen docstrings,
CLAUDE.md o el propio código. **No se corrigió código** en este trabajo de docs.

1. ~~**`scripts/cargar_bd.py` está roto (rompe la actualización de Postgres).**~~
   **RESUELTO.** Antes importaba `fuzzywuzzy` (ausente del venv) a nivel de módulo
   y abortaba, dejando sin forma de regenerar `data/cesym.db`. Ahora las deps de
   ETL están en `requirements-etl.txt` (pineadas) y el import tiene un guard con
   mensaje accionable. Verificado: `cargar_bd.py --limpiar` reconstruye el SQLite
   y la migración lee de ahí. Detalle en [DATA_FLOW.md → §3](./DATA_FLOW.md).

2. **`scripts/run_manual_tests.py` está roto.** `run_manual_tests.py:23` hace
   `from src.loader import ..., EXCEL_PATH`, pero `loader.py` ya no define
   `EXCEL_PATH` (hoy usa `DATA_RAW_DIR` y `_resolver_ruta_cartera()`). ImportError
   al ejecutarlo.

3. **`tests/test_loader.py` rompe la colección de pytest.** Mismo import muerto
   `EXCEL_PATH` (`test_loader.py:18`). `pytest` falla al *recolectar* ese archivo,
   no solo al correrlo. Ver [CLAUDE.md → Tests](../CLAUDE.md#correr-los-tests).

4. **Los tests no son herméticos.** `tests/conftest.py` define fixtures
   (`facturado`, `pendiente`, …) que llaman a `load_facturado()`/`load_pendiente()`,
   leyendo un `CARTERA*.xlsx` real de `data/raw/` (gitignored, no está en el repo).
   Sin ese Excel, `test_cleaner`, `test_queries` y `test_validator` fallan o
   erroran. Solo `tests/test_seguridad.py` es autocontenido.

5. **CLAUDE.md describe una versión anterior del proyecto.** Dice que el objetivo
   es "una versión local desde consola, sin conectarse todavía a WhatsApp". El
   proyecto ya tiene webhook FastAPI desplegado en Railway, integración Twilio
   WhatsApp, capa Postgres, sync con Drive y generación de reportes. El "Project
   Overview" / "Objetivo inicial" de CLAUDE.md reflejan la visión original, no el
   estado actual.

6. **`src/ai_query.py`: docstring vs código.** El docstring afirma que el system
   prompt se envía con `cache_control` ephemeral para que Anthropic lo cachee,
   pero `traducir_a_comando()` llama a `messages.create(... system=_SYSTEM_PROMPT)`
   sin ningún `cache_control`. No hay caching real.

7. **Texto de ayuda vs comportamiento de `reporte`.** `_ayuda()` en
   `query_engine.py` dice `reporte → Genera y envía PDF mensual por email`. Pero el
   handler de `reporte` en `webhook.py` llama a `generar_html()` y devuelve una
   **URL** (`/reportes/...`); no envía email. Las funciones de email
   (`enviar_reporte_email`, `enviar_reporte_html_email`) existen en `reporte.py`
   pero no están conectadas al comando del webhook.

8. **Variables Twilio informativas.** `.env.example` lista `TWILIO_ACCOUNT_SID` y
   `TWILIO_WHATSAPP_NUMBER`, pero el código nunca los lee (solo usa
   `TWILIO_AUTH_TOKEN`). Son referencia para configurar Twilio, no los consume la app.

9. **Overrides de ruta no documentados en `.env.example`.** `loader.py` acepta
   `CARTERA_PATH`, `FACTURAS_PATH` y `TRABAJOS_PATH` para forzar la ruta de cada
   Excel, pero no aparecen en `.env.example`.
