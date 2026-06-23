# Captura de cotizaciones por WhatsApp → cesym_db (Fase 3)

- **Fecha:** 2026-06-22
- **Repo:** cesym-chatbot · **Rama:** `feat/captura-cotizaciones`
- **Objetivo:** parar la acumulación capturando **cotizaciones nuevas** por WhatsApp,
  limpias y validadas, directo en `cesym_db.cotizaciones` (esquema Fase 1 ya aplicado).
- **Reglas:** rama + PR, CI verde, no mergear sin revisión. `chatbot_db` solo lectura
  (de hecho, este flujo no la toca). Seed/rol se aplican a `cesym_db` tras revisión.

## Principios

1. **Escrituras diferidas al confirmar.** Durante la conversación solo hay LECTURAS.
   Crear cliente/sucursal nuevos y la cotización ocurre en **una sola transacción**
   al confirmar. Si el usuario abandona, no quedan filas huérfanas.
2. **Conexión aparte.** `CESYM_DB_URL` es independiente de `DATABASE_URL`. No se
   reemplaza ni se toca la conexión a `chatbot_db`.
3. **Nada de basura.** Validación estricta de importe, IVA, RFC y descripción antes
   de escribir.
4. **Reuso de patrones.** Sesiones compartidas entre workers (el fix de los 2
   workers), capa de escritura que recibe `conn` (como `escritor_pg`), tests
   herméticos con `monkeypatch`.

## Componentes

| Módulo | Rol |
|---|---|
| `src/cesym_db.py` | `get_cesym_engine()` (lee `CESYM_DB_URL`, normaliza `postgres://`); LECTURAS de catálogo: `buscar_clientes(texto) -> list[dict]`, `listar_sucursales(cliente_rfc) -> list[dict]`. |
| `src/cotizaciones_pg.py` | ESCRITURAS que reciben `conn` (sin manejar transacción): `crear_cliente`, `crear_sucursal`, `insertar_cotizacion`. Orquestador `guardar_cotizacion(datos) -> str` con un solo `engine.begin()`. |
| `src/sesiones.py` | Nuevo flujo `cotizacion` (máquina de estados), junto a `agregar`/`editar`/`borrar`. |
| `src/webhook.py` | `_es_cotizar()` + ruteo a `iniciar_cotizacion`; en sesión activa, `tipo=='cotizacion'` → `guardar_cotizacion`. |
| `scripts/seed_clientes_cesym.py` | Seed idempotente del catálogo (lista editable arriba). |
| `docs/ops/cesym_app_role.sql` | Rol `cesym_app` least-privilege (se aplica tras revisión). |

Tablas en `public`, **nombres desnudos** (`clientes`, `sucursales`, `cotizaciones`)
para que el mismo SQL corra en Postgres y en SQLite (tests).

## Flujo conversacional

Dispara con `nueva cotizacion` / `nueva cotización` / `cotizar` / `cotizacion`
(+ tolerancia a typos vía `get_close_matches`, como los triggers de trabajo).

Estado de sesión: `{"tipo": "cotizacion", "paso": <str>, "datos": {...}}`.
Pasos (máquina de estados, no lista lineal, por las ramas de cliente/sucursal):

1. **cliente_buscar** — pide nombre o RFC → `buscar_clientes`:
   - 1 resultado → **cliente_confirma**: "¿Es <nombre_comercial> (<rfc>)? si/no".
   - varios → **cliente_elegir**: lista numerada.
   - 0 → **cliente_crear_rfc** → **cliente_crear_nombre** (tipo='empresa').
     Solo guarda en `datos` (`cliente_nuevo=True`, rfc, nombre_fiscal); NO escribe aún.
2. **sucursal** — pide código o 'sin':
   - 'sin' → `sucursal_id=None`.
   - existe en `listar_sucursales(rfc)` → liga ese `id`.
   - no existe → **sucursal_crear_nombre** (`sucursal_nueva=True`, suc, nombre). No escribe aún.
3. **descripcion** — texto no vacío.
4. **importe** — subtotal; quita `$`/comas; numérico y > 0.
5. **iva** — `8/8%/frontera/vacío` → `0.08`; `16/16%` → `0.16`; otro → re-pregunta.
6. **confirmando** — resumen (cliente, sucursal, descripción, importe, IVA, total =
   `importe*(1+iva)`); 'si' → devuelve `datos` con `tipo='cotizacion'`; 'no' → cancela.

`'cancelar'` aborta en cualquier paso (ya soportado por `sesiones.procesar`).

## Persistencia: `guardar_cotizacion(datos) -> str`

```text
with engine.begin() as conn:
    if datos["cliente_nuevo"]: crear_cliente(conn, rfc, nombre_fiscal, nombre_comercial, 'empresa')
    sucursal_id = (crear_sucursal(conn, rfc, suc, nombre) if datos["sucursal_nueva"]
                   else datos["sucursal_id"])           # puede ser None
    cot_id = insertar_cotizacion(conn, {cliente_rfc, sucursal_id, descripcion,
                                        importe, iva_tasa, fecha=hoy, estado='cotizada'})
    # espeja el número en cot_num
    UPDATE cotizaciones SET cot_num = cot_id WHERE id = cot_id
return f"Cotizacion #{cot_id} registrada para {nombre}. Total ${total:,.2f}."
```

- `id` (IDENTITY, `RETURNING id`) **es** el número secuencial global; se espeja en `cot_num`.
- `fecha = CURRENT_DATE`, `estado = 'cotizada'`.
- `crear_cliente`: `INSERT ... ON CONFLICT (rfc) DO NOTHING` (idempotente).
- Todo en una transacción: si algo falla, rollback total.

## Validaciones

| Campo | Regla |
|---|---|
| importe | `float` tras quitar `$`/`,`; debe ser > 0. Si no, re-pregunta. |
| iva_tasa | ∈ {0.08, 0.16} (mapeo arriba). Otro → re-pregunta. |
| RFC (cliente nuevo) | `[A-ZÑ&0-9]{12,13}` en mayúsculas. Coincide con el CHECK de longitud de la BD. |
| descripcion | no vacía (tras `strip`). |
| cliente | el flujo no avanza sin un RFC resuelto (existente o nuevo válido). |

## Webhook

- `_es_cotizar(texto)`: exacto en triggers o `get_close_matches(cutoff=0.82)`.
- En `_procesar_mensaje`, **antes** de los triggers de trabajo (evita colisión difflib):
  `if _es_cotizar(entrada): return iniciar_cotizacion(numero)`.
- Sesión activa con `datos["tipo"] == "cotizacion"` → `resultado = guardar_cotizacion(datos)`;
  `registrar(...)`; `return resultado`. **No** se llama `_recargar_datos()` (es de chatbot_db).

## Seed (`scripts/seed_clientes_cesym.py`)

Lista editable (fácil agregar más). Razones sociales de la auditoría (se afinan al
migrar CFDI):

```python
CLIENTES_SEED = [
    # (rfc, nombre_fiscal, nombre_comercial)
    ("WDM990126350", "WALDO'S DOLAR MART DE MEXICO", "WALDOS"),
    ("DME860313ND7", "DURA DE MEXICO, S.A. DE C.V.",  "DURA"),
    ("OOM090327365", "OHD OPERATORS DE MEXICO",       "GENIE"),
]
```
Insert idempotente (`ON CONFLICT (rfc) DO NOTHING`, `tipo='empresa'`); no sobrescribe
nombres (se afinan al migrar CFDI). Solo requiere INSERT → acorde al rol `cesym_app`.
Conecta vía `CESYM_DB_URL`. Correrlo dos veces = 3 clientes, sin error.

## Rol `cesym_app` (least-privilege)

`docs/ops/cesym_app_role.sql` (la contraseña la fija ops en el server, nunca en git):

```sql
-- CREATE ROLE cesym_app LOGIN PASSWORD '<definir en server>';
GRANT CONNECT ON DATABASE cesym_db TO cesym_app;
GRANT USAGE ON SCHEMA public TO cesym_app;
GRANT SELECT, INSERT          ON clientes, sucursales TO cesym_app;
GRANT SELECT, INSERT, UPDATE  ON cotizaciones         TO cesym_app;
```
IDENTITY no requiere GRANT extra de secuencia (a diferencia de SERIAL). Sin DELETE,
sin DDL, solo 3 tablas. `CESYM_DB_URL` apunta a este rol en el server.

## Tests (herméticos)

- `test_flujo_cotizacion.py`: cliente existente (1) / varios→elegir / 0→crear con RFC;
  sucursal existente / crear al vuelo / 'sin'→NULL; `datos` final correcto.
- `test_validaciones_cotizacion.py`: importe no numérico / ≤0; IVA inválido; IVA
  default 8 y 16; RFC inválido al crear cliente.
- `test_cotizaciones_pg.py` (SQLite): `crear_cliente` idempotente; `insertar_cotizacion`
  devuelve id y espeja `cot_num`; `guardar_cotizacion` atómico (cliente nuevo + cotización).
- `test_seed_clientes.py` (SQLite): correr dos veces → 3 clientes, sin duplicar.

Patrón: `monkeypatch` de `cesym_db.buscar_clientes`/`listar_sucursales` con un catálogo
en memoria (como `test_sesiones_workers.py`); writes contra SQLite en memoria con tablas
mínimas que reflejan `public` (como los tests `*_pg` actuales).

## Config

- `.env.example`: agregar `CESYM_DB_URL` con comentario (independiente de `DATABASE_URL`).
- Tabla de variables en `CLAUDE.md`: fila `CESYM_DB_URL`.

## Fuera de alcance

- `factura_conceptos` / IVA mixto, edición/borrado de cotizaciones por WhatsApp,
  catálogo de sucursales precargado, migración histórica de cotizaciones (Fase 4).
