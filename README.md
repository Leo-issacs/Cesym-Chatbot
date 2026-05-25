# Cesym Chatbot

Agente local en Python para consultar archivos Excel de cartera: facturas, órdenes de compra y cotizaciones pendientes.

La primera versión funciona completamente desde consola. No conecta WhatsApp ni modifica ningún archivo Excel original.

---

## ¿Qué hace este proyecto?

La empresa maneja su cartera en archivos Excel manualmente. Este sistema lee esos archivos, los limpia y permite hacer consultas en lenguaje sencillo desde la terminal, sin abrir Excel.

**Ejemplo de uso:**

```
cartera> total
cartera> buscar oc O01-507749
cartera> estado prioridad
cartera> errores
```

---

## Requisitos

- Python 3.11.9
- Las dependencias están en `requirements.txt`

---

## Instalación

```powershell
# 1. Activar el entorno virtual
.\venv_Cesym_Chatbot\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Colocar el Excel en la carpeta correcta
#    El archivo debe estar en:  data/raw/CARTERA AL 11032026.xlsx
```

---

## Cómo ejecutar

```powershell
.\venv_Cesym_Chatbot\Scripts\Activate.ps1
python main.py
```

El sistema cargará el Excel, limpiará los datos y mostrará un prompt interactivo:

```
╔══════════════════════════════════════════════╗
         CESYM CHATBOT — Consulta de Cartera
╚══════════════════════════════════════════════╝

Cargando datos del Excel...
  ✓ OC Facturado : 116 registros cargados
  ✓ OC Pendiente :  61 registros cargados

Escribe 'ayuda' para ver los comandos disponibles.

cartera>
```

---

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `total` | Total general de cartera (facturado + pendiente) |
| `total facturado` | Solo el total de OC facturadas |
| `total pendiente` | Solo el total de cotizaciones pendientes |
| `resumen` | Vista general: conteos, montos y desglose por estado |
| `facturas` | Lista todas las OC facturadas con montos y fechas |
| `pendientes` | Lista todas las cotizaciones pendientes |
| `pendientes [suc]` | Cotizaciones pendientes de una sucursal específica |
| `buscar oc [texto]` | Busca por número de OC (ej: `buscar oc O01-507749`) |
| `buscar factura [num]` | Busca una factura por su número |
| `buscar cot [num]` | Busca una cotización pendiente por su número |
| `buscar suc [num]` | Todas las cotizaciones de una sucursal |
| `estado [texto]` | Filtra facturas por estado (ej: `estado aceptada`) |
| `estado prioridad` | Muestra solo las facturas marcadas como prioridad |
| `errores` | Detecta inconsistencias: montos vacíos, fechas faltantes, duplicados |
| `ayuda` | Muestra el menú de comandos |
| `salir` | Cierra el sistema |

---

## Estructura del proyecto

```
Cesym Chatbot/
│
├── main.py                  ← Punto de entrada. Ejecuta el chatbot.
│
├── src/
│   ├── loader.py            ← Lee el Excel (solo lectura, no modifica nada)
│   ├── cleaner.py           ← Limpia y normaliza los datos del Excel
│   ├── query_engine.py      ← Interpreta los comandos y consulta los datos
│   └── cli.py               ← Interfaz de consola (el loop interactivo)
│
├── data/
│   └── raw/                 ← Aquí va el Excel original (NO sube a GitHub)
│
├── requirements.txt         ← Dependencias del proyecto
├── .env.example             ← Template para futuras variables de entorno
└── .gitignore               ← Archivos excluidos del repositorio
```

### ¿Qué hace cada archivo?

**`main.py`**
El punto de entrada. Solo llama a `cli.run()`. Si quieres ejecutar el proyecto, aquí empieza todo.

**`src/loader.py`**
Abre el Excel con `pandas` y devuelve los datos tal como están, sin limpiar nada. Detecta automáticamente dónde está el encabezado real de cada hoja, porque el Excel tiene filas vacías y títulos antes de los datos.

**`src/cleaner.py`**
Recibe los datos crudos del loader y los transforma:
- Renombra las columnas a nombres claros en español
- Elimina las filas de totales/resumen que el Excel incluye al final
- Convierte los tipos de datos (fechas como `datetime`, montos como `float`, etc.)
- Detecta problemas y los reporta como advertencias sin borrar nada

**`src/query_engine.py`**
El cerebro del sistema. Recibe el texto que escribe el usuario, lo divide en palabras, identifica el comando (verbo) y ejecuta la función correspondiente. Devuelve siempre texto formateado listo para imprimir.

**`src/cli.py`**
La interfaz. Coordina la carga, limpieza y consulta, y maneja el loop de `input()` donde el usuario escribe comandos. También muestra los mensajes de bienvenida y las advertencias de carga.

---

## Datos del Excel

El sistema lee dos hojas del archivo `CARTERA AL 11032026.xlsx`:

### Hoja: `OC FACTURADO`

| Campo | Descripción |
|---|---|
| `factura` | Número de la factura emitida |
| `oc` | Número de la Orden de Compra asociada |
| `monto_actual` | Monto pendiente de cobro (CURTRXAM) |
| `prioridad` | Flag de prioridad (`PRIORIDAD` o vacío) |
| `fecha` | Fecha de cálculo de la factura |
| `estado` | Estado: `ACEPTADA`, `PREV ACEPTADO`, etc. |

### Hoja: `PTE OC 25-26`

| Campo | Descripción |
|---|---|
| `cot` | Número de cotización enviada |
| `suc` | Número de sucursal |
| `importe` | Monto cotizado |
| `concepto` | Descripción del servicio (MTTO IGUALA, ILUMINACION, etc.) |

---

## Notas técnicas

- El Excel tiene filas vacías y encabezados desplazados. El loader detecta el encabezado real buscando palabras clave (`FACTURA`, `COT`) en columnas específicas, sin depender de posiciones fijas.
- Las últimas filas de cada hoja son totales/resumen del Excel. El cleaner las elimina detectando que no tienen número de factura/cotización válido.
- Ningún archivo de datos sube al repositorio de GitHub (controlado por `.gitignore`).

---

## Próximas versiones (roadmap)

- [ ] Soporte para un segundo Excel (trabajos realizados por tienda/sucursal)
- [ ] Cruce de información entre los dos archivos
- [ ] Integración con Claude API para consultas en lenguaje natural
- [ ] Conexión con WhatsApp para responder consultas desde el celular
- [ ] Sistema de logs para registrar consultas
- [ ] Backups automáticos antes de cualquier modificación futura
