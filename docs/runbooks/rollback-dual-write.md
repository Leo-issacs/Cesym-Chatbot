# Runbook — Rollback del dual write a Postgres (`USE_POSTGRES_WRITES`)

**Cuándo usar:** el dual write de trabajos a Postgres (`USE_POSTGRES_WRITES=1`)
falla o se comporta mal en producción (errores en logs, trabajos que no aparecen,
duplicados de cliente/técnico, etc.) y querés volver al comportamiento estable de
solo-Excel.

## Rollback (vuelta a solo-Excel) — < 1 minuto

1. Railway → proyecto **Cesym Chatbot** → **Variables**.
2. Cambiá `USE_POSTGRES_WRITES` de `1` a **`0`** (o eliminá la variable; el default
   en código es `0`).
3. Railway redeploya automáticamente al guardar la variable.
4. En < 1 min el bot vuelve a escribir **solo en Excel** al registrar/editar/borrar
   trabajos. Las **lecturas** siguen desde Postgres (`USE_POSTGRES_READS=1`), sin cambio.

No hay rollback de código ni de datos: el flag apaga la ruta de escritura a Postgres
en caliente. El Excel siguió siendo la fuente de verdad de escritura todo el tiempo.

## Verificar que el rollback surtió efecto

- En los logs de Railway, al registrar un trabajo de prueba, **no** debe aparecer
  `[escritor_pg] Trabajo escrito en Postgres (id=…)`.
- El trabajo sí debe quedar en el Excel (y en Drive).

## Qué NO arregla el rollback

- Los trabajos que ya se escribieron en `chatbot.trabajos` mientras el flag estaba
  en `1` **siguen ahí**. Si hubo datos malos (p.ej. `cliente_id` mal resuelto), hay
  que corregirlos a mano en Supabase o reconstruir el schema con el ETL
  (`scripts/cargar_bd.py` → `scripts/migrar_sqlite_a_postgres.py`).
- Filas huérfanas en `chatbot.clientes`/`chatbot.tecnicos` creadas por
  `resolver_o_crear` durante pruebas: revisarlas/limpiarlas a mano si molestan.

## Notas

- El dual write es **best-effort**: si Postgres falla durante una escritura, el bot
  ya cae a solo-Excel y loguea `[escritor_pg] ... falló, solo Excel`. El rollback
  manual es para apagarlo del todo cuando el problema es persistente.
- `editar`/`borrar` usan el `pg_id` (clave estable) para Postgres y la clave natural
  (cliente+tipo+mes) para ubicar la fila del Excel. Si esa clave no matchea de forma
  única, se omite el Excel y Postgres queda autoritativo (ver `docs/DATA_FLOW.md`).
