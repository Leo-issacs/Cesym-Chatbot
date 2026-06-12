"""
webhook.py
----------
Servidor FastAPI que recibe mensajes de WhatsApp via Twilio y responde
con los resultados del sistema de consulta de cartera.

Arranque local (desarrollo con ngrok):
    uvicorn src.webhook:app --reload --port 8000

Despliegue cloud (Railway / Render):
    Procfile: web: uvicorn src.webhook:app --host 0.0.0.0 --port $PORT
"""

import asyncio
import functools
import os
from contextlib import asynccontextmanager
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Form, Response, HTTPException, Request
from fastapi.responses import FileResponse

from src.cli import _cargar_dotenv, _cargar_datos, _sincronizar_drive
from src.query_engine import run_query
from src.sesiones import tiene_sesion, iniciar, iniciar_editar, iniciar_borrar, procesar, cancelar
from src.escritor import agregar_trabajo, editar_trabajo, borrar_trabajo
from src.logger import registrar, leer_recientes
from src.seguridad import verificar_peticion, numero_autorizado, _numeros_autorizados

_LIMITE_WA = 1500  # limite por mensaje de WhatsApp via Twilio
_REPORTES_DIR = Path(__file__).parent.parent / "data" / "reportes"

# ─── Estado global ─────────────────────────────────────────────────────────────
_datos: dict = {
    "facturado": pd.DataFrame(),
    "pendiente": pd.DataFrame(),
    "facturas_mensual": pd.DataFrame(),
    "trabajos": pd.DataFrame(),
}
_cliente_ia = None
_traducir_fn = None
_ultima_sync: datetime | None = None


def _hay_datos() -> bool:
    return not _datos["facturado"].empty


def _recargar_datos() -> list[str]:
    global _ultima_sync
    fac, pte, men, tra, adv = _cargar_datos()
    _datos.update({"facturado": fac, "pendiente": pte,
                   "facturas_mensual": men, "trabajos": tra})
    _ultima_sync = datetime.now()
    return adv


def _init_ia():
    global _cliente_ia, _traducir_fn
    try:
        import anthropic
        from src.ai_query import traducir_a_comando
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            _cliente_ia = anthropic.Anthropic(api_key=key)
            _traducir_fn = traducir_a_comando
    except ImportError:
        pass


# ─── Arranque ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _cargar_dotenv()

    # En cloud: inicializar credenciales de Drive desde variables de entorno
    try:
        from src.drive import init_credenciales_desde_env
        init_credenciales_desde_env()
    except Exception:
        pass

    # Sincronizar datos desde Drive al iniciar (si está configurado)
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id:
        try:
            _sincronizar_drive()
        except Exception:
            pass  # Si falla, intenta cargar lo que haya en data/raw/

    # Restaurar sesiones y logs desde Drive (persisten entre redeploys)
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if folder_id:
        try:
            from src.drive import descargar_archivo_por_nombre
            import src.sesiones as _ses_mod
            base = Path(__file__).parent.parent
            if descargar_archivo_por_nombre("sesiones.json", folder_id, base / "data" / "sesiones.json"):
                _ses_mod._cargar()
            descargar_archivo_por_nombre("queries.log", folder_id, base / "data" / "logs" / "queries.log")
        except Exception:
            pass

    # Cargar datos si hay archivos disponibles (no crashear si no hay)
    try:
        _recargar_datos()
    except FileNotFoundError:
        pass  # Sin datos — el usuario debe enviar 'actualizar' desde WhatsApp

    _init_ia()

    # Sync automático desde Drive cada N horas (configurable con SYNC_INTERVALO_HORAS)
    intervalo_horas = int(os.getenv("SYNC_INTERVALO_HORAS", "6"))
    if os.getenv("DRIVE_FOLDER_ID"):
        asyncio.create_task(_sync_periodico(intervalo_horas))

    yield


async def _sync_periodico(intervalo_horas: int):
    """Sincroniza Drive en background cada N horas."""
    while True:
        await asyncio.sleep(intervalo_horas * 3600)
        try:
            _sincronizar_drive()
            _recargar_datos()
            folder_id = os.getenv("DRIVE_FOLDER_ID")
            if folder_id:
                try:
                    from src.logger import _LOG_PATH, _subir_log_a_drive
                    _subir_log_a_drive()
                except Exception:
                    pass
            print(f"[sync] Datos actualizados automáticamente desde Drive.")
        except Exception as e:
            print(f"[sync] Error al sincronizar: {e}")


app = FastAPI(lifespan=lifespan)


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _dividir_texto(texto: str) -> list[str]:
    """
    Divide un texto largo en partes de max _LIMITE_WA caracteres,
    cortando siempre en saltos de línea para no partir líneas a la mitad.
    """
    if len(texto) <= _LIMITE_WA:
        return [texto]

    partes = []
    while texto:
        if len(texto) <= _LIMITE_WA:
            partes.append(texto)
            break
        corte = texto.rfind("\n", 0, _LIMITE_WA)
        if corte == -1:
            corte = _LIMITE_WA
        partes.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip("\n")

    return partes


def _twiml(texto: str) -> Response:
    """Empaqueta texto en TwiML. Si supera el límite, lo divide en múltiples mensajes."""
    from twilio.twiml.messaging_response import MessagingResponse

    r = MessagingResponse()
    for parte in _dividir_texto(texto):
        r.message(parte)
    return Response(content=str(r), media_type="application/xml")


_TRIGGERS_AGREGAR = ["agregar trabajo", "nuevo trabajo", "registrar trabajo"]
_TRIGGERS_EDITAR  = ["editar trabajo", "modificar trabajo", "corregir trabajo"]
_TRIGGERS_BORRAR  = ["borrar trabajo", "eliminar trabajo", "cancelar trabajo"]


def _es_agregar_trabajo(texto: str) -> bool:
    t = texto.lower().strip()
    if t in (*_TRIGGERS_AGREGAR, "agregar"):
        return True
    return bool(get_close_matches(t, _TRIGGERS_AGREGAR, n=1, cutoff=0.82))


def _es_borrar_trabajo(texto: str) -> bool:
    t = texto.lower().strip()
    if t in _TRIGGERS_BORRAR:
        return True
    return bool(get_close_matches(t, _TRIGGERS_BORRAR, n=1, cutoff=0.82))


def _es_editar_trabajo(texto: str) -> bool:
    t = texto.lower().strip()
    if t in _TRIGGERS_EDITAR:
        return True
    return bool(get_close_matches(t, _TRIGGERS_EDITAR, n=1, cutoff=0.82))


def _formatear_para_editar(trabajos_df: pd.DataFrame) -> list[dict]:
    """Convierte el DataFrame de trabajos a lista de dicts JSON-serializable."""
    if trabajos_df is None or trabajos_df.empty:
        return []
    n = min(10, len(trabajos_df))
    df_tail = trabajos_df.iloc[-n:].reset_index(drop=True)
    offset = len(trabajos_df) - n
    resultado = []
    for i in range(len(df_tail)):
        row = df_tail.iloc[i]

        def s(val):
            try:
                if pd.isna(val):
                    return ""
            except (TypeError, ValueError):
                pass
            v = str(val).strip()
            return "" if v in ("nan", "NaN", "None") else v

        pagado_raw = row["pagado"]
        try:
            pagado_str = str(float(pagado_raw)) if pd.notna(pagado_raw) else ""
        except (TypeError, ValueError):
            pagado_str = ""

        resultado.append({
            "indice_real": offset + i,
            "mes":         s(row["mes"]),
            "tecnico":     s(row["tecnico"]),
            "cliente":     s(row["cliente"]),
            "tipo_trabajo":s(row["tipo_trabajo"]),
            "domicilio":   s(row["domicilio"]),
            "telefono":    s(row["telefono"]),
            "pagado":      pagado_str,
            "recibe":      s(row["recibe"]),
        })
    return resultado


def _ejecutar_consulta(entrada: str) -> str:
    respuesta = run_query(
        entrada,
        _datos["facturado"],
        _datos["pendiente"],
        _datos["facturas_mensual"],
        _datos["trabajos"],
    )
    if respuesta.startswith("Comando no reconocido") and _cliente_ia:
        cmd = _traducir_fn(entrada, _cliente_ia)
        if cmd:
            respuesta = run_query(
                cmd,
                _datos["facturado"],
                _datos["pendiente"],
                _datos["facturas_mensual"],
                _datos["trabajos"],
            )
    return respuesta


def _puede_ver_logs(numero: str) -> bool:
    """
    'logs' expone metadatos de conversaciones (números enmascarados, consultas).
    Exige que el número esté en NUMEROS_AUTORIZADOS aunque ENFORCE_WHITELIST esté
    apagado. Whitelist vacía → niega: a diferencia del caso general (donde lista
    vacía autoriza a todos para no bloquear a la empresa), aquí no hay motivo
    legítimo para exponer los logs a cualquiera.
    """
    if not _numeros_autorizados():
        return False
    autorizado, _ = numero_autorizado(numero)
    return autorizado


# ─── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    """Health check — también muestra cuántos registros hay cargados."""
    return {
        "status": "ok",
        "registros": {k: len(v) for k, v in _datos.items()},
        "ia": _cliente_ia is not None,
    }


@app.get("/reportes/{filename}")
async def servir_reporte(filename: str):
    """Sirve el HTML del reporte generado.

    Seguridad: el nombre se reduce a su componente final con Path(filename).name
    para neutralizar path traversal (../, %2F, rutas absolutas). Además se exige
    que el archivo resuelto sea exactamente un .html DENTRO de data/reportes/.
    """
    reportes_dir = _REPORTES_DIR.resolve()
    nombre = Path(filename).name
    path = (reportes_dir / nombre).resolve()
    if path.parent != reportes_dir or path.suffix != ".html" or not path.is_file():
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    return FileResponse(path, media_type="text/html")


@app.post("/webhook")
async def webhook(request: Request, Body: str = Form(...), From: str = Form(...)):
    # ── Seguridad (firma Twilio + whitelist) ──────────────────────────
    # En modo log-only (por defecto) esto solo registra; bloquea únicamente
    # si ENFORCE_TWILIO_SIGNATURE / ENFORCE_WHITELIST están activos.
    form = await request.form()
    params = {clave: str(valor) for clave, valor in form.items()}
    bloqueo = verificar_peticion(request, params, From)
    if bloqueo is not None:
        return bloqueo

    entrada = Body.strip()
    numero = From  # ej: "whatsapp:+521234567890"

    if not entrada:
        return _twiml("Hola. Escribe 'ayuda' para ver los comandos disponibles.")

    # --- Sesion activa (flujo de registro o edición) ---
    if tiene_sesion(numero):
        mensaje, datos_completos = procesar(numero, entrada)
        if datos_completos is not None:
            if datos_completos.get("tipo") == "editar":
                resultado = editar_trabajo(
                    datos_completos["indice"],
                    datos_completos["campo"],
                    datos_completos["valor"],
                )
            elif datos_completos.get("tipo") == "borrar":
                resultado = borrar_trabajo(datos_completos["indice"])
            else:
                resultado = agregar_trabajo(datos_completos)
            _recargar_datos()
            registrar(numero, entrada, resultado)
            return _twiml(resultado)
        return _twiml(mensaje)

    if entrada.lower() in ("salir", "exit", "quit"):
        return _twiml("Escribe 'ayuda' para ver los comandos disponibles.")

    if entrada.lower() == "logs":
        if not _puede_ver_logs(numero):
            return _twiml(
                "No tienes permiso para ver los logs. Pide acceso al administrador."
            )
        return _twiml(leer_recientes(20))

    # Borrar y editar van primero — comparten alta similitud con "agregar trabajo" en difflib
    if _es_borrar_trabajo(entrada):
        registros = _formatear_para_editar(_datos["trabajos"])
        return _twiml(iniciar_borrar(numero, registros))

    if _es_editar_trabajo(entrada):
        registros = _formatear_para_editar(_datos["trabajos"])
        return _twiml(iniciar_editar(numero, registros))

    # Iniciar flujo de registro (con tolerancia a typos)
    if _es_agregar_trabajo(entrada):
        return _twiml(iniciar(numero))

    if not _hay_datos() and entrada.lower() != "actualizar":
        return _twiml(
            "No hay datos cargados. Escribe 'actualizar' para descargar los archivos desde Google Drive."
        )

    if entrada.lower() in ("reporte", "reporte mensual", "reporte semanal"):
        periodo = "semanal" if "semanal" in entrada.lower() else "mensual"
        try:
            from src.reporte import generar_html
            loop = asyncio.get_event_loop()
            html_path = await loop.run_in_executor(
                None,
                functools.partial(
                    generar_html, periodo,
                    _datos["facturado"], _datos["pendiente"],
                    _datos["facturas_mensual"], _datos["trabajos"],
                ),
            )
            reports_folder_id = os.getenv("DRIVE_REPORTS_FOLDER_ID")
            if reports_folder_id:
                try:
                    from src.drive import subir_archivo
                    await loop.run_in_executor(
                        None,
                        functools.partial(subir_archivo, html_path, reports_folder_id, "text/html"),
                    )
                except Exception:
                    pass
            dominio = os.getenv("RAILWAY_PUBLIC_DOMAIN", "localhost:8000")
            url = f"https://{dominio}/reportes/{html_path.name}"
            registrar(numero, entrada, url)
            return _twiml(f"Reporte {periodo} listo:\n{url}")
        except Exception as e:
            return _twiml(f"Error al generar el reporte: {e}")

    if entrada.lower() == "actualizar":
        try:
            descargados = _sincronizar_drive()
            _recargar_datos()
            ts = _ultima_sync.strftime("%d/%m/%Y %H:%M") if _ultima_sync else "ahora"
            lineas = [f"Datos actualizados desde Drive ({ts})."]
            lineas += [f"  • {f}" for f in descargados]
            lineas.append(
                f"Cargados: {len(_datos['facturado'])} facturas | "
                f"{len(_datos['pendiente'])} pendientes | "
                f"{len(_datos['facturas_mensual'])} mensual | "
                f"{len(_datos['trabajos'])} trabajos"
            )
            return _twiml("\n".join(lineas))
        except Exception as e:
            return _twiml(f"Error al actualizar: {e}")

    respuesta = _ejecutar_consulta(entrada)
    registrar(numero, entrada, respuesta)
    return _twiml(respuesta)
