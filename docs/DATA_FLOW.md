# Flujo de datos — Cesym Chatbot

> Documento de **ingeniería inversa**. Describe el flujo real de los datos hoy.
> La asimetría entre lectura y escritura es el corazón de este documento.

Ver también [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## 0. El resumen que importa

El flujo de datos es **asimétrico**:

- La **lectura** tiene dos fuentes posibles (Postgres o Excel), conmutables por flag.
  Desde PR-14 el default es **Postgres** (`USE_POSTGRES_READS=1`), con fallback a
  Excel si la BD falla.
- La **escritura** va siempre a **Excel → Drive**. Con `USE_POSTGRES_WRITES=1`
  (default `0`), agregar un trabajo nuevo además lo escribe en `chatbot.trabajos`
  (best-effort, Excel siempre). El resto de escrituras no toca Postgres.
- La forma de poblar/refrescar el **grueso** de Postgres sigue siendo un **pipeline
  offline**
  (`cargar_bd.py` → `migrar_sqlite_a_postgres.py`). Funciona, pero requiere las
  deps de ETL (`requirements-etl.txt`) y correrse a mano.

Consecuencia (con `USE_POSTGRES_READS=1`, ya el default): los trabajos que el bot
agregue van a **Excel**, no a Postgres, así que **no se reflejan** en lo que el bot
lee hasta correr el ETL manual de refresco. La asimetría sigue (el bot escribe a
Excel, lee de Postgres). Mantén el ETL al día o un cambio reciente no se verá.

```
                    ┌──────────────────────────────────────┐
   LECTURA (default)│  Postgres chatbot.* → datos_postgres │──► 4 DataFrames ──► query_engine
                    └──────────────────────────────────────┘        en memoria
                    ┌──────────────────────────────────────┐
   LECTURA (flag=0  │  Excel (data/raw/) → loader → cleaner │──► 4 DataFrames ──► query_engine
    o fallback)     └──────────────────────────────────────┘   (mismas columnas)

   ESCRITURA        escritor.py ──► Excel local ──► backup ──► Google Drive
   (única ruta)     (NO hay camino a Postgres)

   REFRESCO PG      Excel ──► cargar_bd.py ──► SQLite ──► migrar_sqlite_a_postgres.py ──► Postgres
   (offline, manual)          └─ requiere requirements-etl.txt (fuzzywuzzy) ─┘
```

---

## 1. LECTURA

### 1.1 Camino Excel → memoria (`USE_POSTGRES_READS=0`, o fallback)

Con `USE_POSTGRES_READS=0` (o cuando la lectura de Postgres falla, como fallback).
En `src/cli.py:_cargar_datos()`:

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

### 1.2 Camino Postgres → memoria (default desde PR-14)

`USE_POSTGRES_READS=1` (default). `_cargar_datos()` delega en
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

### 2.2 Escritura a Postgres en runtime (parcial, detrás de flag)

Por defecto, `escritor.py` solo escribe a Excel y Drive. Con
**`USE_POSTGRES_WRITES=1`** (default `0`), al registrar un **trabajo nuevo** el bot
lo escribe también en `chatbot.trabajos` (vía `escritor_pg.py`), **antes** que el
Excel y best-effort: si Postgres falla, sigue solo con Excel. Resuelve el
cliente/técnico a su id (creándolos si no existen).

Limitaciones actuales de esta ruta:
- Solo cubre **agregar** trabajo. `editar`/`borrar` siguen operando por índice
  posicional sobre el Excel (el fix por `pg_id` —que elimina el race condition—
  va en un PR siguiente, porque requiere que la lectura traiga `t.id`).
- Las **demás** escrituras (facturas, cartera) siguen sin camino a Postgres.
- El **estado de sesiones** va aparte (`sesiones_pg.py`, si `USE_POSTGRES_SESSIONS=1`).

Con el flag apagado, Postgres sigue siendo **solo de lectura** para datos de
negocio, poblado por el pipeline offline.

---

## 3. REFRESCO DE POSTGRES (pipeline offline)

Para que el modo `USE_POSTGRES_READS=1` tenga datos al día, se corre a mano:

```
Excel (data/raw/)
   │  scripts/cargar_bd.py          (Extract→Transform→Normalize→Load)
   ▼
SQLite (data/cesym.db)
   │  scripts/migrar_sqlite_a_postgres.py   (idempotente, preserva IDs)
   ▼
PostgreSQL (schema chatbot)
```

### 3.1 Historia: el hallazgo de PR-01 (ya resuelto)

Originalmente la cadena estaba **rota**: `cargar_bd.py:46` hace
`from fuzzywuzzy import fuzz, process` a nivel de módulo, y `fuzzywuzzy` no estaba
instalada (en el pin de dependencias se movió, junto con `python-Levenshtein`,
fuera de `requirements.txt` porque el runtime no las necesita —
`query_engine.py` hace su fuzzy matching con `difflib` de la stdlib). El
`ModuleNotFoundError` abortaba `cargar_bd.py` antes de hacer nada, dejando sin
forma de regenerar `data/cesym.db`.

**Arreglo (este PR):**

- Las deps de ETL se declaran y pinean en **`requirements-etl.txt`**
  (`fuzzywuzzy==0.18.0`, `python-Levenshtein==0.27.3`), instalables con
  `pip install -r requirements-etl.txt`.
- `cargar_bd.py` envuelve el import en un guard: si `fuzzywuzzy` falta, sale con un
  mensaje accionable (apunta a `requirements-etl.txt`) en vez de un traceback crudo.
- Verificado end-to-end: `cargar_bd.py --limpiar` reconstruye `data/cesym.db` desde
  los Excel (fuzzy matching activo, p.ej. `"TEC Y DISEÑOS" → "TEC Y DISEÑO"`), y la
  migración lee ese `.db`. Al verificar, Postgres ya estaba sincronizado con el
  SQLite (mismos conteos), así que `migrar_sqlite_a_postgres.py` sería un no-op.

### 3.2 Por qué esto importa para la migración

El modo Postgres (`USE_POSTGRES_READS=1`) es desde PR-14 la fuente de lectura por
defecto. Consideraciones que siguen vigentes y exigen disciplina operativa:

- El refresco es **manual**: hay que correr el ETL tras cambiar los Excel.
- `migrar_sqlite_a_postgres.py` usa `ON CONFLICT DO NOTHING`: **inserta** filas
  nuevas pero **no actualiza** las existentes. Un cambio de un valor en una factura
  ya migrada no se reflejaría con solo re-correr la migración (limitación conocida).
- Cualquier trabajo que el bot agregue va a **Excel**, no a Postgres → divergencia
  con lo que se leería en modo Postgres hasta el siguiente ETL.

Con Postgres ya como default de lectura, **la disciplina del ETL es crítica**: si
los Excel cambian y no se corre el refresco, el bot servirá datos viejos sin error
(el fallback a Excel solo cubre caídas de conexión, no datos stale). Cerrar esto a
cero-toque (escritura bot→Postgres o ETL automático) queda para más adelante.

### 3.3 Cómo refrescar Postgres hoy

1. `pip install -r requirements-etl.txt` (una vez por máquina).
2. `python -X utf8 scripts/cargar_bd.py --limpiar` — reconstruye `data/cesym.db`.
3. `python -X utf8 scripts/migrar_sqlite_a_postgres.py` — migra a Postgres
   (requiere `DATABASE_URL`/`DATABASE_MIGRATION_URL`).
4. Recién entonces tiene sentido evaluar `USE_POSTGRES_READS=1`.
5. Pendiente de diseño aparte: una ruta de escritura bot→Postgres, o un job que
   reejecute el ETL tras cada cambio en Excel, para cerrar la asimetría de la §2.2.

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

- ~~**El refresco de Postgres está roto** (`cargar_bd.py` importa `fuzzywuzzy`
  ausente)~~ — **RESUELTO**: deps en `requirements-etl.txt` + guard de import; ver §3.1.
- **Asimetría lectura/escritura**: el bot lee de Excel *o* Postgres pero solo
  escribe a Excel; no hay camino de escritura bot→Postgres (§2.2).
- **El contrato de columnas se mantiene a mano** en dos lugares (`cleaner.py` y
  `datos_postgres.py`); cambiarlo en uno sin el otro rompe el modo Postgres en
  silencio (§1.3).
