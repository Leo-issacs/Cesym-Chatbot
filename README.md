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

### Totales y resumen

| Comando | Qué hace |
|---|---|
| `total` | Total general de cartera (facturado + pendiente) |
| `total facturado` | Solo el total de OC facturadas |
| `total pendiente` | Solo el total de cotizaciones pendientes |
| `total mensual` | Total del reporte mensual: cobrado vs sin fecha de pago |
| `resumen` | Vista general: conteos, montos, estados y resumen del reporte mensual |

### Cartera (Excel)

| Comando | Qué hace |
|---|---|
| `facturas` | Lista todas las OC facturadas con montos y fechas |
| `pendientes` | Lista todas las cotizaciones pendientes |
| `pendientes [suc]` | Cotizaciones pendientes de una sucursal específica |
| `estado [texto]` | Filtra facturas por estado (ej: `estado aceptada`) |
| `estado prioridad` | Muestra solo las facturas marcadas como prioridad |

### Reporte mensual (CSV)

| Comando | Qué hace |
|---|---|
| `cobradas` | Facturas del reporte mensual que ya tienen fecha de pago |
| `sin cobrar` | Facturas del reporte mensual sin fecha de pago registrada |
| `buscar cliente [nombre]` | Todas las facturas de un cliente (ej: `buscar cliente waldos`) |

### Cruce entre archivos

| Comando | Qué hace |
|---|---|
| `cruce` | Facturas que están en cartera como pendientes pero ya tienen pago en el reporte mensual |

### Búsquedas

| Comando | Qué hace |
|---|---|
| `buscar oc [texto]` | Busca por número de OC (ej: `buscar oc O01-507749`) |
| `buscar factura [num]` | Busca una factura por su número |
| `buscar cot [num]` | Busca una cotización pendiente por su número |
| `buscar suc [num]` | Todas las cotizaciones de una sucursal |

### Validaciones y otros

| Comando | Qué hace |
|---|---|
| `errores` | Detecta inconsistencias: montos vacíos, fechas faltantes, duplicados |
| `actualizar` | Descarga los archivos desde Google Drive |
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

## Archivos de datos

El sistema carga dos fuentes al iniciar.

### Excel de cartera: `CARTERA AL 11032026.xlsx`

#### Hoja: `OC FACTURADO`

| Campo | Descripción |
|---|---|
| `factura` | Número de la factura emitida |
| `oc` | Número de la Orden de Compra asociada |
| `monto_actual` | Monto pendiente de cobro (CURTRXAM) |
| `prioridad` | Flag de prioridad (`PRIORIDAD` o vacío) |
| `fecha` | Fecha de cálculo de la factura |
| `estado` | Estado: `ACEPTADA`, `PREV ACEPTADO`, etc. |

#### Hoja: `PTE OC 25-26`

| Campo | Descripción |
|---|---|
| `cot` | Número de cotización enviada |
| `suc` | Número de sucursal |
| `importe` | Monto cotizado |
| `concepto` | Descripción del servicio (MTTO IGUALA, ILUMINACION, etc.) |

### Reporte mensual: `reporteMensual_FACTURAS.csv`

Historial de todas las facturas emitidas en el período, con su fecha de pago. El campo `folio` es el mismo número que `factura` en el Excel de cartera, lo que permite cruzar ambas fuentes.

| Campo | Descripción |
|---|---|
| `folio` | Número de factura (enlaza con `factura` del Excel de cartera) |
| `cliente` | Nombre del cliente (WALDOS, TOYODA, OHD, etc.) |
| `fecha` | Fecha de emisión de la factura |
| `concepto` | Descripción del trabajo realizado |
| `total` | Monto facturado |
| `fecha_pago` | Fecha en que se registró el pago (vacío = sin cobrar) |

---

## Notas técnicas

- El Excel tiene filas vacías y encabezados desplazados. El loader detecta el encabezado real buscando palabras clave (`FACTURA`, `COT`) en columnas específicas, sin depender de posiciones fijas.
- Las últimas filas de cada hoja son totales/resumen del Excel. El cleaner las elimina detectando que no tienen número de factura/cotización válido.
- El CSV del reporte mensual puede tener encoding `utf-8-sig` o `latin-1` dependiendo del sistema que lo generó. El loader prueba ambos automáticamente.
- Las filas canceladas en el CSV (`C A N C E L A D O`) se excluyen automáticamente durante la limpieza.
- El reporte mensual es opcional: si no existe el CSV en `data/raw/`, el sistema carga solo el Excel de cartera sin errores.
- Ningún archivo de datos sube al repositorio de GitHub (controlado por `.gitignore`).

---

## Reglas de manejo de archivos

Estas reglas aplican ahora y seguirán aplicando cuando se integre Google Drive.

| Regla | Descripción |
|---|---|
| **No modificar el original** | El archivo Excel que llega del cliente no se toca. Nunca. |
| **Trabajar sobre copias** | Cualquier limpieza, validación o edición futura se hace sobre una copia en `02_Excels_Trabajo/`. |
| **Backup obligatorio** | Antes de cualquier escritura futura al Excel, el sistema debe crear un backup automático en `03_Backups/`. Esta función no existe aún, se implementará cuando se habilite la escritura. |
| **Los archivos reales no suben a GitHub** | El `.gitignore` excluye `data/raw/`, `data/backups/` y todos los `.xlsx`. El repositorio solo contiene código. |
| **Dónde viven los archivos reales** | Localmente en `data/raw/` durante el desarrollo. Cuando se integre Drive, vendrán de `01_Excels_Originales/` en la unidad compartida. |

---

## Estructura recomendada en Google Drive

Cuando se implemente la integración con Google Drive, los archivos del proyecto se organizarán en una carpeta compartida con esta estructura:

```
Cesym Chatbot/                        ← Carpeta raíz en Drive (acceso compartido)
│
├── 01_Excels_Originales/             ← Archivos tal como llegan. NUNCA se editan aquí.
│   └── CARTERA AL 11032026.xlsx
│   └── (futuros archivos de trabajos realizados)
│
├── 02_Excels_Trabajo/                ← Copias de trabajo. El sistema opera sobre estos.
│   └── (copias generadas automáticamente al iniciar un proceso)
│
├── 03_Backups/                       ← Respaldos con fecha/hora antes de cualquier escritura.
│   └── (generados automáticamente, nunca manuales)
│
├── 04_Reportes_Generados/            ← Reportes de calidad y consultas exportadas.
│   └── data_quality_report.md
│   └── (futuros reportes en Excel o PDF)
│
├── 05_Muestras_Sin_Datos_Reales/     ← Archivos con estructura real pero datos ficticios.
│   └── (para pruebas, demos y desarrollo sin exponer información real)
│
└── 06_Documentacion/                 ← Guías de uso, flujos, decisiones del proyecto.
    └── README.md
    └── TESTING.md
```

> **Nota:** Esta estructura aún no está conectada al código. Es la organización que se usará cuando se implemente `src/drive_connector.py` en una versión futura.

---

## Flujo recomendado de archivos

Este es el proceso que debe seguirse cada vez que se recibe un Excel actualizado, ahora y cuando se integre Drive.

```
1. RECIBIR EL EXCEL ORIGINAL
   └── El archivo llega por correo, WhatsApp o Drive desde el cliente.
       No se edita. No se renombra. No se abre en Excel para "corregir".

2. GUARDAR EN DRIVE (cuando esté integrado)
   └── Subir a: Cesym Chatbot/01_Excels_Originales/
       Nombre sugerido: CARTERA AL DDMMYYYY.xlsx

3. COPIAR A CARPETA DE TRABAJO
   └── El sistema (o el usuario manualmente por ahora) copia el archivo a:
         - Local:  data/raw/
         - Drive:  02_Excels_Trabajo/
       La copia es la que se lee. El original no se toca.

4. EJECUTAR LIMPIEZA Y VALIDACIÓN
   └── python main.py               ← Carga y limpia los datos
       python scripts/run_manual_tests.py  ← Genera reporte de calidad

5. REVISAR EL REPORTE DE CALIDAD
   └── Abrir data_quality_report.md y verificar:
         - Registros con fechas vacías
         - OC o cotizaciones duplicadas
         - Montos inválidos
         - Registros incompletos
       Cualquier inconsistencia debe consultarse con el origen del Excel
       antes de continuar.

6. VALIDAR RESULTADOS CON EL RESPONSABLE DEL EXCEL
   └── Si hay errores o datos raros, confirmar con la persona que generó
       el archivo si son válidos o si son errores de captura.

7. SOLO DESPUÉS: PERMITIR AUTOMATIZACIONES
   └── Una vez validado el Excel, se pueden activar:
         - Respuestas automáticas por WhatsApp
         - Exportación de reportes a Drive
         - Cruce con el segundo Excel (trabajos realizados)
         - Cualquier proceso que escriba o modifique datos
```

> **Regla de oro:** Nunca automatizar sobre un Excel que no fue revisado manualmente al menos una vez.

---

## Próximas versiones (roadmap)

**v1.x — Mejoras locales**
- [x] Soporte para el reporte mensual de facturas (CSV)
- [x] Cruce de información entre cartera y reporte mensual
- [ ] Detección de facturas y OC duplicadas en el comando `errores`
- [ ] Sistema de logs para registrar consultas

**v2 — Integración con Google Drive**
- [x] Descarga automática de archivos desde Google Drive (`src/drive.py`)
- [ ] Copia automática a carpeta de trabajo antes de procesar
- [ ] Backup automático con fecha/hora antes de cualquier escritura futura
- [ ] Exportación de reportes a `04_Reportes_Generados/` en Drive

**v3 — Automatización e IA**
- [x] Integración con Claude API para consultas en lenguaje natural (`src/ai_query.py`)
- [ ] Integración del tercer Excel (trabajos a clientes casuales)
- [ ] Conexión con WhatsApp (n8n o Twilio) para responder consultas desde el celular
- [ ] Notificaciones automáticas cuando se detecten inconsistencias
