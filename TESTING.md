# TESTING.md — Fase de Pruebas

Guía de pruebas para el Cesym Chatbot antes de conectar WhatsApp, Drive o n8n.

---

## Cómo correr las pruebas

### Opción A: Pruebas manuales (script directo, sin dependencias extra)

```powershell
# Activar entorno virtual
.\venv_Cesym_Chatbot\Scripts\Activate.ps1

# Correr el script manual (también genera data_quality_report.md)
python scripts/run_manual_tests.py
```

Genera salida en consola con `[PASS]` / `[FAIL]` por cada prueba, y crea
el archivo `data_quality_report.md` con el análisis de calidad del Excel.

---

### Opción B: Pruebas automatizadas con pytest

```powershell
# Activar entorno virtual
.\venv_Cesym_Chatbot\Scripts\Activate.ps1

# Instalar dependencias (incluye pytest)
pip install -r requirements.txt

# Correr todos los tests
pytest tests/ -v

# Correr solo un módulo
pytest tests/test_loader.py -v
pytest tests/test_cleaner.py -v
pytest tests/test_queries.py -v
pytest tests/test_validator.py -v

# Con resumen de fallos al final
pytest tests/ -v --tb=short
```

---

## Estructura de archivos de prueba

```
tests/
├── conftest.py          → Fixtures compartidas (carga el Excel una vez por sesión)
├── test_loader.py       → Pruebas de lectura del Excel
├── test_cleaner.py      → Pruebas de limpieza y normalización
├── test_queries.py      → Pruebas del motor de consultas
└── test_validator.py    → Pruebas de detección de inconsistencias

scripts/
└── run_manual_tests.py  → Script manual + generador de data_quality_report.md
```

---

## Qué se está validando

### Lectura del Excel (`test_loader.py`)
| Prueba | Qué valida |
|--------|-----------|
| El archivo Excel existe | La ruta `data/raw/CARTERA AL 11032026.xlsx` es accesible |
| Hoja `OC FACTURADO` detectada | La hoja no fue renombrada ni eliminada |
| Hoja `PTE OC 25-26` detectada | Igual para la segunda hoja |
| Encabezado dinámico `FACTURA` | El parser detectó la fila correcta como header |
| Encabezado dinámico `COT` | Igual para pendientes |
| DataFrames no vacíos | Se leyeron filas reales de datos |

### Limpieza de datos (`test_cleaner.py`)
| Prueba | Qué valida |
|--------|-----------|
| Columnas renombradas correctamente | `factura`, `oc`, `monto_actual`, `prioridad`, `fecha`, `estado` |
| Filas de totales excluidas | El limpiador elimina filas como "TOTAL", "COTIZADO", etc. |
| Sin nulos en columna `factura` | Todos los registros tienen número de factura válido |
| Tipo `Int64` en facturas | Los números se guardaron como enteros, no como texto |
| Tipo `float` en montos | Los montos son numéricos |
| Tipo `datetime` en fechas | Las fechas de Excel se convirtieron correctamente |
| Fechas con año >= 2000 | Detecta conversiones de fecha fallidas (daría 1970 si falla) |
| No modifica el DataFrame original | El cleaner trabaja sobre copias, nunca sobre el original |

### Consultas (`test_queries.py`)
| Prueba | Qué valida |
|--------|-----------|
| `total` general | Devuelve string con `$` y sección de facturado y pendiente |
| `total facturado` | Monto positivo del total facturado |
| `total pendiente` | Monto positivo del total pendiente |
| `resumen` | Contiene conteos de registros |
| `facturas` | Lista con `Fac`, subtotal al final |
| `pendientes` | Lista con `Cot`, subtotal al final |
| `buscar factura [num]` | Encuentra la primera factura del dataset |
| `buscar factura 999999999` | Devuelve "no se encontró" |
| `buscar factura abc` | Devuelve error de tipo, no excepción |
| `buscar oc [texto]` | Búsqueda parcial por OC |
| `buscar cot [num]` | Encuentra la primera COT del dataset |
| `buscar suc [num]` | Encuentra la primera SUC del dataset |
| `estado aceptada` | Devuelve resultados o mensaje vacío, no excepción |
| `estado prioridad` | Igual para prioridad |
| Comando vacío | Devuelve mensaje de ayuda, no crash |
| Comando desconocido | Devuelve mensaje de error, no excepción |

### Validaciones (`test_validator.py`)
| Prueba | Qué valida |
|--------|-----------|
| `errores` devuelve string | El comando no lanza excepción |
| `errores` con DF vacío | Maneja edge case sin romper |
| Montos inválidos detectados | Facturas con monto 0 o vacío |
| Fechas vacías contabilizadas | Facturas sin fecha de facturación |
| Registros sin OC | Facturas que no tienen OC asignada |
| Cotizaciones duplicadas vía `errores` | Si hay duplicados, el comando los reporta |
| Facturas duplicadas (nivel datos) | Detecta duplicados directamente en el DataFrame |
| OC duplicadas (nivel datos) | Igual para números de OC |

---

## Qué resultados revisar manualmente

1. **`data_quality_report.md`** — generado por `scripts/run_manual_tests.py`:
   - Total de registros limpios vs filas RAW.
   - Montos inválidos, fechas vacías, OCs faltantes.
   - Registros duplicados (facturas, OC, COT).
   - Total facturado y total pendiente de OC.

2. **Salida de `pytest tests/test_validator.py -v`**:
   - Los tests de duplicados informan pero no fallan si no hay duplicados.
   - Revisa el conteo de `montos_invalidos_en_facturado` en consola.

3. **Advertencias del cleaner** (aparecen al correr `main.py`):
   - Si hay montos ≤ 0, fechas vacías o COTs duplicadas, se imprimen al inicio.

---

## Limitaciones actuales

- **Solo un archivo Excel**: las pruebas solo cubren `CARTERA AL 11032026.xlsx`.
- **Sin datos sintéticos**: los tests usan el Excel real, no datos controlados.
  Si el Excel cambia de estructura, los tests pueden fallar de forma inesperada.
- **Sin detección de facturas/OC duplicadas en el motor**: el comando `errores`
  no revisa duplicados en la hoja `OC FACTURADO` todavía (sí lo hace en pendientes).
- **Sin pruebas de concurrencia**: no se prueba qué pasa si dos instancias
  corren al mismo tiempo.
- **Sin pruebas de archivos corruptos**: no se prueba qué pasa si el Excel está
  abierto por otra aplicación o está dañado.

---

## Pruebas pendientes para versiones futuras

| Prueba | Versión |
|--------|---------|
| Lectura del segundo Excel (trabajos realizados) | v2 |
| Cruce de datos entre hojas (factura en ambos archivos) | v2 |
| Detección de facturas duplicadas en `errores` | v1.1 |
| Detección de OC duplicadas en `errores` | v1.1 |
| Pruebas con datos sintéticos (Excel de prueba) | v1.1 |
| Pruebas de rendimiento (archivos grandes) | v2 |
| Pruebas de CLI (comandos interactivos automatizados) | v2 |
| Pruebas de integración con Claude API | v3 |
| Pruebas de integración con WhatsApp | v3 |
| Pruebas de backup automático antes de escritura | v2 |
| Pruebas de modificación segura del Excel | v2 |
