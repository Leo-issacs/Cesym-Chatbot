# Reporte de Calidad de Datos
**Generado:** 2026-05-25 15:15:22
**Archivo:** `CARTERA AL 11032026.xlsx`

## Hojas detectadas
- `OC FACTURADO`
- `PTE OC 25-26`
- `Hoja1`

## Hoja: OC FACTURADO
| Métrica | Valor |
|---------|-------|
| Filas RAW (antes de limpieza) | 121 |
| Filas limpias | 117 |
| Filas ignoradas (totales/encabezados) | 4 |

**Columnas detectadas:** `factura, oc, monto_actual, prioridad, fecha, estado`

### Totales
- **Total OC Facturado:** `$695,107.52`

### Registros con monto inválido (cero, negativo o vacío)
- Ninguno detectado.

### Registros sin fecha
- **Cantidad:** 32
- **Facturas afectadas:** [8078, 8079, 8080, 8081, 8082, 8083, 8084, 8085, 8086, 8087, 8088, 8089, 8090, 8091, 8092, 8093, 8094, 8095, 8096, 8097, 8098, 8099, 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107, 8108, 8109]

### Registros sin OC asignada
- Ninguno detectado.

### Facturas duplicadas
- Ninguna detectada.

### OC duplicadas
- **Registros afectados:** 2
- **OC duplicadas:** ['O01-539206']

### Registros incompletos (sin OC, sin fecha o sin monto)
- **Cantidad:** 32
- **Facturas afectadas:** [8078, 8079, 8080, 8081, 8082, 8083, 8084, 8085, 8086, 8087, 8088, 8089, 8090, 8091, 8092, 8093, 8094, 8095, 8096, 8097, 8098, 8099, 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107, 8108, 8109]

### Advertencias del proceso de limpieza
- ⚠ 32 factura(s) sin fecha: [8078, 8079, 8080, 8081, 8082, 8083, 8084, 8085, 8086, 8087, 8088, 8089, 8090, 8091, 8092, 8093, 8094, 8095, 8096, 8097, 8098, 8099, 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107, 8108, 8109]

## Hoja: PTE OC 25-26
| Métrica | Valor |
|---------|-------|
| Filas RAW (antes de limpieza) | 64 |
| Filas limpias | 59 |
| Filas ignoradas (totales/encabezados) | 5 |

**Columnas detectadas:** `cot, suc, importe, concepto`

### Totales
- **Total Pendiente (PTE OC):** `$408,607.36`

### Cotizaciones con importe inválido
- Ninguna detectada.

### Cotizaciones duplicadas
- **Registros afectados:** 4
- **COTs duplicadas:** [74, 86]

### Sucursales con cotizaciones pendientes
- **Cantidad de sucursales:** 25
- **Números:** [1026, 1029, 3614, 3720, 5201, 5202, 5204, 5208, 5209, 5220, 6452, 6462, 6466, 6467, 6468, 6490, 6570, 6584, 6670, 6674, 6687, 6688, 6857, 6875, 6958]

### Advertencias del proceso de limpieza
- ⚠ Cotizaciones con número duplicado: [74, 86]

## Resumen global
| Concepto | Registros | Monto |
|----------|-----------|-------|
| OC Facturado | 117 | `$695,107.52` |
| PTE OC 25-26 | 59 | `$408,607.36` |
| **TOTAL CARTERA** | 176 | **`$1,103,714.88`** |

## Advertencias globales
- ⚠ 32 factura(s) sin fecha: [8078, 8079, 8080, 8081, 8082, 8083, 8084, 8085, 8086, 8087, 8088, 8089, 8090, 8091, 8092, 8093, 8094, 8095, 8096, 8097, 8098, 8099, 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107, 8108, 8109]
- ⚠ Cotizaciones con número duplicado: [74, 86]

## Limitaciones conocidas
- Solo se procesa el archivo `CARTERA AL 11032026.xlsx`.
- El segundo Excel (trabajos realizados) no está disponible aún.
- No se cruza información entre hojas todavía.
- La detección de facturas duplicadas y OC duplicadas no está en el motor de consultas (solo en este reporte).
