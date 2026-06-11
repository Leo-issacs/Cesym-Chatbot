# Flujo de datos — Cesym Chatbot

> Documento de **ingeniería inversa**. Describe el flujo real de los datos hoy.
> La asimetría entre lectura y escritura es el corazón de este documento.

Ver también [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## 0. El resumen que importa

El flujo de datos es **asimétrico**:

- La **lectura** tiene dos fuentes posibles (Excel o Postgres), conmutables por flag.
- La **escritura** tiene una sola ruta: el bot escribe a **Excel → Drive**. No
  existe ningún camino de escritura del bot hacia Postgres en runtime.
- La única forma de poblar/refrescar Postgres es un **pipeline offline**
  (`cargar_bd.py` → `migrar_sqlite_a_postgres.py`) que hoy está **roto**.

Consecuencia: si algún día se activa `USE_POSTGRES_READS=1`, los trabajos que el
bot agregue (que van a Excel) **no aparecerán** en Postgres hasta correr un ETL
manual que, además, actualmente no funciona.

```
                    ┌──────────────────────────────────────┐
   LECTURA (hoy)    │  Excel (data/raw/) → loader → cleaner │──► 4 DataFrames ──► query_engine
                    └──────────────────────────────────────┘        en memoria
                    ┌──────────────────────────────────────┐
   LECTURA (flag)   │  Postgres chatbot.* → datos_postgres │──► 4 DataFrames ──► query_engine
                    └──────────────────────────────────────┘   (mismas columnas)

   ESCRITURA        escritor.py ──► Excel local ──► backup ──► Google Drive
   (única ruta)     (NO hay camino a Postgres)

   REFRESCO PG      Excel ──► cargar_bd.py ──► SQLite ──► migrar_sqlite_a_postgres.py ──► Postgres
   (offline, ROTO)            └─ ✗ fuzzywuzzy no instalada ─┘
```

---

## 1. LECTURA

### 1.1 Camino por defecto: Excel → memoria

`USE_POSTGRES_READS=0` (default). En `src/cli.py:_cargar_datos()`:

1. `loader.py` abre los Excel de `data/raw/` **sin modificarlos** y devuelve RAW:
   - `load_facturado()` → hoja `OC FACTURADO` (detecta encabezado buscando `FACTURA`).
   - `load_pendiente()` → hoja `PTE OC 25-26` (busca `COT`).
   - `load_facturas_mensual()` → `reporteMensual_*.xlsx/.csv`.
   - `load_trabajos()` → `CONTROL*.xlsx`.
2. `cleaner.py` limpia cada uno: recorta a las columnas útiles, descarta filas de
   totales (donde la clave no es numérica), convierte tipos (`Int64`, `float`,
   `datetime`), normaliza `"nan"` → `""`, y emite advertencias de calidad.
3. El resultado son **4 DataFrames** que viven en el estado global de `webhook.py`
   (`_datos`) o en variables locales del REPL (`cli.run()`).

La fuente de verdad en este modo son los **archivos Excel** (sincronizados desde
Drive). Todo se recalcula en memoria en cada `actualizar`/sync; no hay BD.

### 1.2 Camino alternativo: Postgres → memoria (apagado)

`USE_POSTGRES_READS=1`. `_cargar_datos()` delega en
`datos_postgres.cargar_datos_desde_postgres()`, que ejecuta 4 SELECT sobre el
schema `chatbot` y devuelve los DataFrames. Si algo falla, **cae a Excel**.

El objetivo de diseño es que el switch sea **transparente**: los DataFrames de
Postgres tienen exactamente las mismas columnas que produce `cleaner.py`, para que
`query_engine.py` no note la diferencia.

### 1.3 El contrato de columnas (lo que `query_engine.py` exige)

`query_engine.py` accede a columnas por nombre (`facturado["monto_actual"]`,
`facturas["fecha_pago"]`, etc.). Por eso ambas fuentes DEBEN producir exactamente
estas columnas. El contrato está documentado en
**`src/datos_postgres.py:13-21`** y se replica aquí:

| DataFrame | Columnas exactas | Producido por (Excel) | Producido por (Postgres) |
|---|---|---|---|
| `facturado` | `factura, oc, monto_actual, prioridad, fecha, estado` | `clean_facturado()` | `_SQL_FACTURADO` (tabla `ordenes_compra` WHERE `tipo='OC_EMITIDA'`) |
| `pendiente` | `cot, suc, importe, concepto` | `clean_pendiente()` | `_SQL_PENDIENTE` (`ordenes_compra` WHERE `tipo='COT_PENDIENTE'`) |
| `facturas_mensual` | `folio, cliente, fecha, concepto, total, fecha_pago` | `clean_facturas_mensual()` | `_SQL_FACTURAS_MENSUAL` (`facturas` JOIN `clientes`) |
| `trabajos` | `mes, tecnico, cliente, rep_num, domicilio, telefono, tipo_trabajo, pagado, recibe` | `clean_trabajos()` | `_SQL_TRABAJOS` (`trabajos` JOIN `clientes`, `tecnicos`) |

**Sutilezas que el lado Postgres replica a mano** para honrar el contrato:
- `COALESCE(col, '')` en SQL replica el `astype(str).replace('nan','')` del cleaner:
  los `NULL` deben llegar como string vacío, no como `None`/`NaN`, o los filtros y
  agrupaciones del query engine se comportan distinto.
- Tras los SELECT, `datos_postgres.py` además reemplaza el **string literal**
  `"nan"` por `""` (el ETL insertó `str(float('nan'))` = `"nan"` para celdas vacías).

> Si se agrega/renombra una columna en `cleaner.py`, hay que tocar también las
> queries de `datos_postgres.py`, o el modo Postgres romperá silenciosamente.

---

## 2. ESCRITURA

### 2.1 Única ruta: bot → Excel → Drive

Las operaciones de escritura del bot (agregar/editar/borrar trabajo) las maneja
**`src/escritor.py`**, disparado desde el webhook tras completarse una sesión
(`sesiones.py`). El flujo de `agregar_trabajo()` / `editar_trabajo()` /
`borrar_trabajo()`:

1. Resuelve (o crea) el Excel de trabajos `CONTROL*.xlsx` en `data/raw/`.
2. **Backup** con timestamp a `data/backups/` (y a Drive si `DRIVE_BACKUPS_FOLDER_ID`).
3. Lee el Excel, filtra filas sin cliente/tipo, aplica el cambio, reescribe el Excel.
4. **Sube el Excel modificado a Drive** (`DRIVE_FOLDER_ID`). Si falla, avisa al
   usuario que quedó solo local.
5. El webhook llama a `_recargar_datos()` para refrescar los DataFrames en memoria.

Cumple las reglas del proyecto: nunca borra registros sin confirmación (flujo de
sesión con "si/no"), siempre hace backup antes, y no toca el Excel original *in
place* sin respaldo.

### 2.2 No hay escritura a Postgres en runtime

`escritor.py` solo conoce Excel y Drive. **Ningún módulo del runtime escribe
datos de negocio a Postgres.** Lo único que el bot escribe a Postgres es el
**estado de sesiones** (`sesiones_pg.py`, si `USE_POSTGRES_SESSIONS=1`) — y eso
no son datos de cartera/trabajos, es estado conversacional efímero.

Por tanto Postgres, en lo que respecta a datos de negocio, es **solo de lectura**
desde la perspectiva del bot. Se puebla exclusivamente por el pipeline offline.

---

## 3. REFRESCO DE POSTGRES (pipeline offline) — y por qué está ROTO

Para que el modo `USE_POSTGRES_READS=1` tenga datos al día, hay que correr a mano:

```
Excel (data/raw/)
   │  scripts/cargar_bd.py          (Extract→Transform→Normalize→Load)
   ▼
SQLite (data/cesym.db)
   │  scripts/migrar_sqlite_a_postgres.py   (idempotente, preserva IDs)
   ▼
PostgreSQL (schema chatbot)
```

### 3.1 El hallazgo de PR-01: la cadena está rota

**`scripts/cargar_bd.py` no puede ni importarse.** En `cargar_bd.py:46`:

```python
from fuzzywuzzy import fuzz, process
```

es un import a nivel de módulo, y **`fuzzywuzzy` no está instalada** (ni ella ni
`python-Levenshtein`). En el trabajo de pin de dependencias se confirmó que esas
libs no estaban en el venv y se movieron a `requirements.in` como **deps solo-ETL**
(fuera de `requirements.txt`), porque el runtime no las necesita —
`query_engine.py` hace su fuzzy matching con `difflib` de la stdlib.

Efecto en cadena:

- `cargar_bd.py` aborta con `ModuleNotFoundError` antes de hacer nada.
- Sin `cargar_bd.py`, no hay forma de **regenerar `data/cesym.db`** desde los Excel.
- `migrar_sqlite_a_postgres.py` lee precisamente de `data/cesym.db`. Puede correr,
  pero solo migraría datos viejos/stale (o nada si el `.db` no existe).

**Conclusión:** la **única vía de refrescar Postgres a partir de los Excel actuales
no funciona**. Postgres solo podría contener lo que se haya cargado en el pasado,
cuando `fuzzywuzzy` sí estaba disponible en alguna máquina.

### 3.2 Por qué esto importa para la migración

El modo Postgres (`USE_POSTGRES_READS=1`) se diseñó como el futuro "fuente de
verdad". Pero hoy:

- Activarlo serviría datos potencialmente desactualizados (no hay refresco).
- Cualquier trabajo que el bot agregue va a **Excel**, no a Postgres → divergencia
  inmediata entre lo que el bot escribe y lo que leería en modo Postgres.

Por eso los flags están en `0`: la migración está **incompleta y bloqueada** por
este ETL roto, no solo "apagada por precaución".

### 3.3 Qué haría falta para desbloquearlo (no ejecutado aquí)

1. Instalar las deps de ETL en la máquina local:
   `pip install fuzzywuzzy python-Levenshtein` (declaradas en `requirements.in`).
2. Correr `python -X utf8 scripts/cargar_bd.py --limpiar` para reconstruir
   `data/cesym.db` desde los Excel.
3. Correr `python -X utf8 scripts/migrar_sqlite_a_postgres.py` para migrar a Postgres.
4. Recién entonces tendría sentido evaluar `USE_POSTGRES_READS=1`.
5. Pendiente de diseño aparte: una ruta de escritura bot→Postgres, o un job que
   reejecute el ETL tras cada cambio en Excel, para cerrar la asimetría de la §2.2.

> Esto está documentado como pendiente; **no se corrigió ni se ejecutó** nada de
> esto en este trabajo de documentación.

---

## 4. Persistencia auxiliar (no son datos de negocio)

| Qué | Dónde (default) | Dónde (con flag/cloud) | Notas |
|---|---|---|---|
| Sesiones multi-turno | `data/sesiones.json` | `chatbot.sesiones_bot` (`USE_POSTGRES_SESSIONS=1`) | En Railway el archivo es efímero; se respalda a Drive y se restaura al arrancar. |
| Log de consultas | `data/logs/queries.log` | se sube a Drive cada 20 entradas | Números enmascarados, retención 30 días. |
| Backups de Excel | `data/backups/` | `DRIVE_BACKUPS_FOLDER_ID` | Antes de cada escritura. |
| Reportes | `data/reportes/` | `DRIVE_REPORTS_FOLDER_ID`; servidos en `/reportes/{file}` | HTML (webhook) o PDF (email, no usado por el comando `reporte`). |

---

## Deuda documentada

La lista completa de divergencias código↔docs está en
[ARCHITECTURE.md → Deuda documentada](./ARCHITECTURE.md#deuda-documentada).
Las directamente relevantes al flujo de datos:

- **El refresco de Postgres está roto** (`cargar_bd.py` importa `fuzzywuzzy`
  ausente) — desarrollado en la §3.1 de este documento.
- **Asimetría lectura/escritura**: el bot lee de Excel *o* Postgres pero solo
  escribe a Excel; no hay camino de escritura bot→Postgres (§2.2).
- **El contrato de columnas se mantiene a mano** en dos lugares (`cleaner.py` y
  `datos_postgres.py`); cambiarlo en uno sin el otro rompe el modo Postgres en
  silencio (§1.3).
