# Cesym Chatbot

Chatbot de WhatsApp para consultar la cartera de facturas, cotizaciones pendientes y registrar trabajos realizados. Corre en la nube (Railway) y responde desde cualquier número conectado al sandbox de Twilio.

---

## ¿Qué hace?

- Consulta el Excel de cartera: facturas, OC, cotizaciones pendientes, reporte mensual
- Registra trabajos nuevos desde WhatsApp (flujo conversacional paso a paso)
- Descarga los archivos desde Google Drive al iniciar
- Sube automáticamente el Excel de trabajos a Drive al guardar un nuevo registro
- Responde en lenguaje natural gracias a Claude Haiku cuando el comando no se reconoce exactamente

---

## Arquitectura

```
WhatsApp (usuario)
      │
   Twilio (recibe y envía mensajes)
      │
   Railway (servidor FastAPI en la nube)
      │
   Google Drive (archivos Excel fuente)
```

El servidor corre en Railway. Al arrancar, descarga los Excels desde Drive a `data/raw/`. Todas las consultas operan sobre esos datos en memoria.

---

## Comandos disponibles (WhatsApp)

### Totales y resumen

| Comando | Qué hace |
|---|---|
| `total` | Total general (facturado + pendiente) |
| `total facturado` | Solo OC facturadas |
| `total pendiente` | Solo cotizaciones pendientes |
| `total mensual` | Cobrado vs sin fecha de pago |
| `resumen` | Vista general: conteos, montos, estados |

### Cartera

| Comando | Qué hace |
|---|---|
| `facturas` | Lista OC facturadas con montos y fechas |
| `pendientes` | Lista cotizaciones pendientes |
| `pendientes [suc]` | Cotizaciones de una sucursal específica |
| `estado [texto]` | Filtra facturas por estado (ej: `estado aceptada`) |
| `estado prioridad` | Solo las facturas marcadas como prioridad |
| `cobradas` | Facturas del reporte mensual con fecha de pago |
| `sin cobrar` | Facturas del reporte mensual sin pago |
| `cruce` | Facturas pendientes en cartera pero ya pagadas en el mensual |

### Trabajos

| Comando | Qué hace |
|---|---|
| `trabajos` | Lista todos los trabajos registrados |
| `trabajos [mes]` | Trabajos de un mes específico (ej: `trabajos mayo`) |
| `agregar trabajo` | Inicia el flujo para registrar un trabajo nuevo |
| `editar trabajo` | Edita un campo de un trabajo ya registrado |

### Búsquedas

| Comando | Qué hace |
|---|---|
| `buscar oc [texto]` | Busca por número de OC |
| `buscar factura [num]` | Busca una factura por número |
| `buscar cot [num]` | Busca una cotización por número |
| `buscar suc [num]` | Cotizaciones de una sucursal |
| `buscar cliente [nombre]` | Facturas de un cliente |
| `buscar tecnico [nombre]` | Trabajos de un técnico |

### Otros

| Comando | Qué hace |
|---|---|
| `errores` | Detecta inconsistencias en los datos |
| `actualizar` | Descarga los archivos desde Drive y recarga los datos |
| `ayuda` | Muestra el menú completo |

---

## Flujo de registro de trabajo

Al escribir `agregar trabajo`, el bot hace preguntas una por una:

1. Mes del trabajo
2. Técnico que lo realizó
3. Nombre del cliente
4. Domicilio
5. Teléfono (o "sin")
6. Tipo de trabajo
7. Monto cobrado (o "sin cobrar")
8. Quién recibe / firma

Al final muestra un resumen y pide confirmación antes de guardar. Escribe `cancelar` en cualquier momento para salir sin guardar.

El registro se guarda en el Excel `CONTROL DE INST. MINISPLIT 2026.xlsx` y se sube automáticamente a Drive.

---

## Variables de entorno

El servidor necesita estas variables configuradas en Railway:

| Variable | Descripción |
|---|---|
| `DRIVE_FOLDER_ID` | ID de la carpeta `02_Excels_Trabajo` en Google Drive |
| `GOOGLE_CREDENTIALS_JSON` | Contenido de `credentials.json` en base64 |
| `GOOGLE_TOKEN_JSON` | Contenido de `token.json` en base64 |
| `ANTHROPIC_API_KEY` | API key de Anthropic (para el fallback de lenguaje natural) |
| `SYNC_INTERVALO_HORAS` | Cada cuántas horas sincronizar Drive automáticamente (default: `6`) |

Para generar los valores base64 de las credenciales de Drive:

```powershell
.\venv_Cesym_Chatbot\Scripts\Activate.ps1
python scripts/export_credenciales.py
```

Copia los valores que imprime y pégalos en las variables de Railway.

---

## Despliegue en Railway

El proyecto ya está desplegado en Railway. Para actualizarlo basta con hacer push a `main`:

```powershell
git push
```

Railway detecta el push, reconstruye la imagen y reinicia el servidor automáticamente.

Si el servidor aparece en rojo (crash), revisar los logs en el dashboard de Railway. El error más común es que las credenciales de Drive estén mal copiadas.

### URL del servidor

```
https://web-production-2bb2c.up.railway.app
```

- `GET /` — health check, muestra cuántos registros hay cargados
- `POST /webhook` — endpoint que usa Twilio

---

## Conectar un número de WhatsApp al sandbox

1. Abrir WhatsApp desde el número que se quiere conectar
2. Enviar el mensaje de invitación al número del sandbox de Twilio  
   (se encuentra en Twilio → Messaging → Try it out → Send a WhatsApp message)
3. Una vez conectado, el número puede usar todos los comandos normalmente

El sandbox soporta varios números conectados al mismo tiempo. La conexión dura ~72 horas de inactividad; si expira, repetir el paso 2.

---

## Uso local (consola)

Para probar sin WhatsApp:

```powershell
.\venv_Cesym_Chatbot\Scripts\Activate.ps1
python main.py
```

Requiere tener los archivos Excel en `data/raw/` y el archivo `.env` con las variables configuradas.

---

## Estructura del proyecto

```
Cesym Chatbot/
│
├── main.py                  ← Entrada para uso desde consola
├── Procfile                 ← Comando de arranque para Railway
│
├── src/
│   ├── webhook.py           ← Servidor FastAPI (endpoint de Twilio)
│   ├── sesiones.py          ← Estado de conversaciones activas por número
│   ├── escritor.py          ← Escribe filas en el Excel de trabajos
│   ├── query_engine.py      ← Interpreta comandos y consulta los datos
│   ├── ai_query.py          ← Fallback de lenguaje natural con Claude Haiku
│   ├── cli.py               ← Interfaz de consola
│   ├── loader.py            ← Lee los archivos Excel y CSV
│   ├── cleaner.py           ← Limpia y normaliza los datos
│   └── drive.py             ← Descarga y sube archivos a Google Drive
│
├── scripts/
│   └── export_credenciales.py  ← Genera los valores base64 para Railway
│
├── data/
│   ├── raw/                 ← Archivos descargados de Drive (no sube a GitHub)
│   └── backups/             ← Backups automáticos antes de escribir (no sube a GitHub)
│
├── .env                     ← Variables de entorno locales (no sube a GitHub)
├── .env.example             ← Template de variables de entorno
└── requirements.txt         ← Dependencias del proyecto
```

---

## Archivos de datos en Drive

Los archivos viven en la carpeta `02_Excels_Trabajo` de Google Drive.

| Archivo | Contenido |
|---|---|
| `CARTERA AL *.xlsx` | Facturas, OC y cotizaciones pendientes (hoja `OC FACTURADO` y `PTE OC 25-26`) |
| `reporteMensual_FACTURAS.csv` | Historial de facturas con fechas de pago |
| `CONTROL DE INST. MINISPLIT 2026.xlsx` | Registro de trabajos realizados a clientes |

El sistema descarga estos archivos automáticamente al iniciar y los re-sincroniza cada 6 horas en background (configurable con `SYNC_INTERVALO_HORAS`). Para forzar una actualización inmediata desde WhatsApp, enviar `actualizar`.

---

## Reglas de archivos

- El Excel original nunca se modifica directamente
- Antes de cualquier escritura se crea un backup automático en `data/backups/`
- Los archivos de datos no suben a GitHub (excluidos por `.gitignore`)
- Los datos reales viven en Drive, no en el repositorio

---

## Roadmap

**Completado**
- [x] Lectura y limpieza de Excel de cartera
- [x] Consultas desde consola
- [x] Integración con Google Drive
- [x] Servidor WhatsApp via Twilio + Railway
- [x] Fallback de lenguaje natural con Claude Haiku
- [x] Tercer Excel: registro de trabajos
- [x] Flujo de registro de trabajo desde WhatsApp
- [x] Escritura al Excel con backup automático
- [x] Editar un trabajo ya registrado desde WhatsApp
- [x] Sync automático desde Drive cada N horas en background

**Pendiente**
- [ ] Sistema de logs de consultas
- [ ] Resumen semanal/mensual automático por WhatsApp
