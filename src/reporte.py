"""
reporte.py
----------
Genera el reporte PDF periódico (semanal o mensual) con métricas y gráficas
de cartera, trabajos y alertas. Envía el PDF por correo electrónico via Gmail.

Variables de entorno requeridas para enviar email:
  GMAIL_USER          → dirección Gmail remitente (ej: tuempresa@gmail.com)
  GMAIL_APP_PASSWORD  → contraseña de aplicación de Google (no la contraseña normal)
  REPORT_RECIPIENTS   → emails destinatarios separados por coma
"""

import io
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # sin GUI — necesario en servidor
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import json
import math

from src.cleaner import clean_facturado, clean_facturas_mensual, clean_pendiente, clean_trabajos
from src.loader import load_facturado, load_facturas_mensual, load_pendiente, load_trabajos

# Ruta del template HTML (junto a este archivo)
_HTML_TEMPLATE = Path(__file__).parent.parent / "reporte_cesym.html"

_MESES_ABREV = {
    1:"Ene", 2:"Feb", 3:"Mar", 4:"Abr", 5:"May", 6:"Jun",
    7:"Jul", 8:"Ago", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Dic",
}
_COLORES_ESTADO = ["#1B4F72", "#1E8449", "#D68910", "#95A5A6", "#8E44AD", "#C0392B"]

# ── Colores del PDF ───────────────────────────────────────────────────────────
AZUL        = colors.HexColor("#1a5276")
AZUL_MED    = colors.HexColor("#2e86c1")
AZUL_CLARO  = colors.HexColor("#d6eaf8")
VERDE       = colors.HexColor("#27ae60")
VERDE_CLARO = colors.HexColor("#d5f5e3")
NARANJA     = colors.HexColor("#e67e22")
NARANJA_CL  = colors.HexColor("#fdebd0")
ROJO        = colors.HexColor("#c0392b")
ROJO_CLARO  = colors.HexColor("#fadbd8")
GRIS        = colors.HexColor("#5d6d7e")
BLANCO      = colors.white

MESES_ORDEN = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
MESES_CORTO = {
    "ENERO": "Ene", "FEBRERO": "Feb", "MARZO": "Mar", "ABRIL": "Abr",
    "MAYO": "May", "JUNIO": "Jun", "JULIO": "Jul", "AGOSTO": "Ago",
    "SEPTIEMBRE": "Sep", "OCTUBRE": "Oct", "NOVIEMBRE": "Nov", "DICIEMBRE": "Dic",
}

# Estilo global de matplotlib
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.labelcolor": "#2c3e50",
    "xtick.color": "#2c3e50",
    "ytick.color": "#2c3e50",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

COLORES_GRAFICAS = ["#2e86c1", "#27ae60", "#e67e22", "#8e44ad", "#c0392b", "#1abc9c", "#5d6d7e"]


# ── Utilidades ────────────────────────────────────────────────────────────────
def _pesos(valor) -> str:
    if pd.isna(valor) or valor == 0:
        return "$0"
    return f"${valor:,.0f}"


def _grafica_a_imagen(fig, ancho_pt: float, alto_pt: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=ancho_pt, height=alto_pt)


# ── Carga de datos ────────────────────────────────────────────────────────────
def _cargar_datos():
    df_fac, _ = clean_facturado(load_facturado())
    df_pen, _ = clean_pendiente(load_pendiente())
    df_men, _ = clean_facturas_mensual(load_facturas_mensual())
    df_tra, _ = clean_trabajos(load_trabajos())
    return df_fac, df_pen, df_men, df_tra


# ── Gráficas ──────────────────────────────────────────────────────────────────
def _grafica_facturado_por_mes(df_fac: pd.DataFrame, ancho: float, alto: float) -> Image:
    df = df_fac.dropna(subset=["fecha", "monto_actual"]).copy()
    df["periodo"] = df["fecha"].dt.to_period("M")
    por_mes = df.groupby("periodo")["monto_actual"].sum().reset_index()
    por_mes["label"] = por_mes["periodo"].astype(str)
    por_mes = por_mes.tail(12)

    fig, ax = plt.subplots(figsize=(8, 3.5))
    bars = ax.bar(por_mes["label"], por_mes["monto_actual"], color=COLORES_GRAFICAS[0], width=0.6)
    ax.set_title("Monto Facturado por Mes (OC activas)", fontsize=12, fontweight="bold", color="#1a5276", pad=10)
    ax.set_xlabel("Mes")
    ax.set_ylabel("Monto ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    plt.xticks(rotation=40, ha="right", fontsize=8)

    for bar in bars:
        h = bar.get_height()
        if h > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2, h * 1.01,
                f"${h:,.0f}", ha="center", va="bottom", fontsize=7, color="#1a5276",
            )

    plt.tight_layout()
    return _grafica_a_imagen(fig, ancho, alto)


def _grafica_estados_pie(df_fac: pd.DataFrame, ancho: float, alto: float) -> Image:
    estados = df_fac["estado"].replace("", "SIN ESTADO").fillna("SIN ESTADO")
    conteo = estados.value_counts()
    umbral = conteo.sum() * 0.03
    conteo_agg = conteo[conteo >= umbral].copy()
    otros = conteo[conteo < umbral].sum()
    if otros > 0:
        conteo_agg["OTROS"] = otros

    fig, ax = plt.subplots(figsize=(5, 3.5))
    wedges, _, autotexts = ax.pie(
        conteo_agg.values,
        autopct="%1.1f%%",
        colors=COLORES_GRAFICAS[:len(conteo_agg)],
        startangle=90,
        pctdistance=0.78,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    for at in autotexts:
        at.set_fontsize(8)
        at.set_color("white")
        at.set_fontweight("bold")

    ax.legend(
        wedges, conteo_agg.index,
        loc="lower center", bbox_to_anchor=(0.5, -0.18),
        ncol=2, fontsize=7, frameon=False,
    )
    ax.set_title("Por Estado", fontsize=12, fontweight="bold", color="#1a5276", pad=10)
    plt.tight_layout()
    return _grafica_a_imagen(fig, ancho, alto)


def _grafica_cobradas_vs_pendientes(df_men: pd.DataFrame, ancho: float, alto: float) -> Image:
    df = df_men.dropna(subset=["fecha"]).copy()
    df["periodo"] = df["fecha"].dt.to_period("M")

    cobradas  = df[df["fecha_pago"].notna()].groupby("periodo")["total"].sum()
    pendientes = df[df["fecha_pago"].isna()].groupby("periodo")["total"].sum()

    todos = sorted(set(cobradas.index) | set(pendientes.index))[-12:]
    meses_str = [str(m) for m in todos]
    cob_vals = [cobradas.get(m, 0) for m in todos]
    pen_vals = [pendientes.get(m, 0) for m in todos]

    x = range(len(meses_str))
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(x, cob_vals, label="Cobradas", color=COLORES_GRAFICAS[1], width=0.6)
    ax.bar(x, pen_vals, bottom=cob_vals, label="Por cobrar", color=COLORES_GRAFICAS[2], width=0.6)
    ax.set_title("Cobradas vs Por Cobrar por Mes", fontsize=12, fontweight="bold", color="#1a5276", pad=10)
    ax.set_xlabel("Mes")
    ax.set_ylabel("Monto ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
    ax.set_xticks(list(x))
    ax.set_xticklabels(meses_str, rotation=40, ha="right", fontsize=8)
    ax.legend(fontsize=8, frameon=False)
    plt.tight_layout()
    return _grafica_a_imagen(fig, ancho, alto)


def _grafica_trabajos_por_mes(df_tra: pd.DataFrame, ancho: float, alto: float) -> Image:
    df = df_tra.copy()
    df["mes_num"] = df["mes"].map(MESES_ORDEN)
    df = df[df["mes_num"].notna()].copy()
    df["mes_num"] = df["mes_num"].astype(int)

    por_mes = (
        df.groupby(["mes_num", "mes"])
        .agg(cantidad=("cliente", "count"), cobrado=("pagado", "sum"))
        .reset_index()
        .sort_values("mes_num")
    )
    por_mes["label"] = por_mes["mes"].map(MESES_CORTO).fillna(por_mes["mes"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.5))

    ax1.bar(por_mes["label"], por_mes["cantidad"], color=COLORES_GRAFICAS[0], width=0.6)
    ax1.set_title("Trabajos por Mes", fontsize=11, fontweight="bold", color="#1a5276", pad=8)
    ax1.set_ylabel("Cantidad")
    plt.setp(ax1.get_xticklabels(), rotation=40, ha="right", fontsize=8)
    for i, (_, row) in enumerate(por_mes.iterrows()):
        ax1.text(i, row["cantidad"] + 0.1, str(int(row["cantidad"])),
                 ha="center", va="bottom", fontsize=8, color="#1a5276")

    ax2.bar(por_mes["label"], por_mes["cobrado"].fillna(0), color=COLORES_GRAFICAS[1], width=0.6)
    ax2.set_title("Monto Cobrado por Mes", fontsize=11, fontweight="bold", color="#1a5276", pad=8)
    ax2.set_ylabel("Monto ($)")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
    plt.setp(ax2.get_xticklabels(), rotation=40, ha="right", fontsize=8)

    plt.tight_layout()
    return _grafica_a_imagen(fig, ancho, alto)


def _grafica_tecnicos(df_tra: pd.DataFrame, ancho: float, alto: float) -> Image:
    df = df_tra[df_tra["tecnico"].notna() & ~df_tra["tecnico"].isin(["", "nan"])].copy()
    por_tec = (
        df.groupby("tecnico")
        .agg(cantidad=("cliente", "count"), cobrado=("pagado", "sum"))
        .reset_index()
        .sort_values("cantidad", ascending=True)
    )

    fig, ax = plt.subplots(figsize=(7, max(2.5, len(por_tec) * 0.55 + 0.5)))
    bars = ax.barh(por_tec["tecnico"], por_tec["cantidad"], color=COLORES_GRAFICAS[0], height=0.5)
    ax.set_title("Trabajos por Técnico", fontsize=12, fontweight="bold", color="#1a5276", pad=8)
    ax.set_xlabel("Cantidad de trabajos")
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 0.1, bar.get_y() + bar.get_height() / 2,
                str(int(w)), va="center", fontsize=9, color="#1a5276")

    plt.tight_layout()
    alto_real = min(alto, max(3 * cm, len(por_tec) * 1.5 * cm))
    return _grafica_a_imagen(fig, ancho, alto_real)


# ── Estilos PDF ───────────────────────────────────────────────────────────────
def _estilos() -> dict:
    return {
        "titulo": ParagraphStyle(
            "titulo", fontName="Helvetica-Bold", fontSize=22,
            textColor=BLANCO, alignment=TA_CENTER, spaceAfter=4,
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo", fontName="Helvetica", fontSize=10,
            textColor=BLANCO, alignment=TA_CENTER,
        ),
        "seccion": ParagraphStyle(
            "seccion", fontName="Helvetica-Bold", fontSize=13,
            textColor=AZUL, spaceBefore=10, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=9,
            textColor=colors.HexColor("#2c3e50"), spaceAfter=4,
        ),
        "alerta": ParagraphStyle(
            "alerta", fontName="Helvetica", fontSize=9,
            textColor=colors.HexColor("#7b241c"), spaceAfter=3,
        ),
        "nota": ParagraphStyle(
            "nota", fontName="Helvetica-Oblique", fontSize=8,
            textColor=GRIS, spaceAfter=2,
        ),
    }


def _estilo_tabla() -> TableStyle:
    return TableStyle([
        ("BACKGROUND",   (0, 0), (-1,  0), AZUL),
        ("TEXTCOLOR",    (0, 0), (-1,  0), BLANCO),
        ("FONTNAME",     (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1,  0), 9),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLANCO, AZUL_CLARO]),
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 8),
        ("GRID",         (0, 0), (-1, -1), 0.25, colors.HexColor("#bdc3c7")),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])


def _kpi_tabla(valor_str: str, label: str, color_borde, color_valor, ancho: float) -> Table:
    t = Table(
        [
            [Paragraph(valor_str, ParagraphStyle(
                "kv", fontName="Helvetica-Bold", fontSize=15,
                textColor=color_valor, alignment=TA_CENTER,
            ))],
            [Paragraph(label, ParagraphStyle(
                "kl", fontName="Helvetica", fontSize=8,
                textColor=GRIS, alignment=TA_CENTER,
            ))],
        ],
        colWidths=[ancho],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BLANCO),
        ("BOX",           (0, 0), (-1, -1), 1.5, color_borde),
        ("TOPPADDING",    (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


# ── Construcción del HTML ─────────────────────────────────────────────────────
def _safe(v) -> float:
    """Convierte a float; retorna 0 si NaN/None."""
    try:
        f = float(v)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def _periodo_label(periodo_str: str) -> str:
    """'2025-12' → 'Dic 2025'"""
    year, month = periodo_str.split("-")
    return f"{_MESES_ABREV[int(month)]} {year}"


def _construir_datos_reporte(
    df_fac: pd.DataFrame,
    df_pen: pd.DataFrame,
    df_men: pd.DataFrame,
    df_tra: pd.DataFrame,
    periodo: str,
) -> dict:
    """Calcula todos los KPIs y datos de gráficas listos para inyectar en el HTML."""
    hoy = datetime.now()

    # ── KPIs ─────────────────────────────────────────────────────
    total_facturado = _safe(df_fac["monto_actual"].sum()) if not df_fac.empty else 0.0
    total_cobrado   = _safe(df_men[df_men["fecha_pago"].notna()]["total"].sum()) if not df_men.empty else 0.0
    por_cobrar      = _safe(df_men[df_men["fecha_pago"].isna()]["total"].sum()) if not df_men.empty else 0.0
    total_trabajos  = len(df_tra)
    total_pen_oc    = _safe(df_pen["importe"].sum()) if not df_pen.empty else 0.0

    # ── Gráfica 1: Facturado por mes ────────────────────────────
    chart_fac = {"labels": [], "data": []}
    if not df_fac.empty:
        df = df_fac.dropna(subset=["fecha", "monto_actual"]).copy()
        df["periodo"] = df["fecha"].dt.to_period("M")
        por_mes = df.groupby("periodo")["monto_actual"].sum().reset_index().tail(12)
        chart_fac["labels"] = [_periodo_label(str(p)) for p in por_mes["periodo"]]
        chart_fac["data"]   = [round(_safe(v), 2) for v in por_mes["monto_actual"]]

    # ── Gráfica 2: Por estado ────────────────────────────────────
    chart_estados = []
    if not df_fac.empty:
        estados = df_fac["estado"].replace("", "SIN ESTADO").fillna("SIN ESTADO")
        conteo  = estados.value_counts()
        total_e = conteo.sum()
        umbral  = total_e * 0.03
        agg     = conteo[conteo >= umbral].copy()
        otros   = conteo[conteo < umbral].sum()
        if otros > 0:
            agg["OTROS"] = otros
        for i, (estado, cnt) in enumerate(agg.items()):
            label = "Sin Estado" if estado in ("SIN ESTADO", "nan", "") else str(estado).title()
            chart_estados.append({
                "label": label,
                "pct":   round(cnt / total_e * 100, 1),
                "color": _COLORES_ESTADO[i % len(_COLORES_ESTADO)],
            })

    # ── Gráfica 3: Cobradas vs Por Cobrar por mes ────────────────
    chart_cob = {"labels": [], "cobradas": [], "por_cobrar": []}
    if not df_men.empty:
        df = df_men.dropna(subset=["fecha"]).copy()
        df["periodo"]    = df["fecha"].dt.to_period("M")
        cobradas_g       = df[df["fecha_pago"].notna()].groupby("periodo")["total"].sum()
        pendientes_g     = df[df["fecha_pago"].isna()].groupby("periodo")["total"].sum()
        todos            = sorted(set(cobradas_g.index) | set(pendientes_g.index))[-12:]
        chart_cob["labels"]     = [_periodo_label(str(m)) for m in todos]
        chart_cob["cobradas"]   = [round(_safe(cobradas_g.get(m, 0)), 2) for m in todos]
        chart_cob["por_cobrar"] = [round(_safe(pendientes_g.get(m, 0)), 2) for m in todos]

    # ── Tabla de facturas sin cobrar ─────────────────────────────
    sin_cobrar = df_men[df_men["fecha_pago"].isna()].copy() if not df_men.empty else pd.DataFrame()
    tabla = []
    if not sin_cobrar.empty:
        for _, row in sin_cobrar.sort_values("fecha").iterrows():
            fecha_str = row["fecha"].strftime("%d/%m/%Y") if pd.notna(row["fecha"]) else ""
            tabla.append({
                "folio":   int(row["folio"]) if pd.notna(row["folio"]) else 0,
                "cliente": str(row["cliente"]),
                "monto":   round(_safe(row["total"]), 2),
                "fecha":   fecha_str,
            })

    # ── Alertas ──────────────────────────────────────────────────
    alertas = []
    if not sin_cobrar.empty:
        alertas.append(
            f"{len(sin_cobrar)} factura(s) sin cobrar — "
            f"importe total: <strong>${sin_cobrar['total'].sum():,.0f}</strong>"
        )
        if "fecha" in sin_cobrar.columns:
            hace_180 = pd.Timestamp.now() - pd.Timedelta(days=180)
            muy_ant = sin_cobrar[sin_cobrar["fecha"].notna() & (sin_cobrar["fecha"] < hace_180)]
            if not muy_ant.empty:
                alertas.append(
                    f"{len(muy_ant)} factura(s) con más de 180 días sin cobrar — "
                    "requieren seguimiento urgente"
                )
    if not df_fac.empty:
        sin_oc = df_fac[df_fac["oc"].isin(["nan", "", "NaN"])]
        if not sin_oc.empty:
            alertas.append(f"{len(sin_oc)} factura(s) sin OC asignada")
    if not df_tra.empty:
        sin_pago_tra = df_tra[df_tra["pagado"].isna()]
        if not sin_pago_tra.empty:
            alertas.append(f"{len(sin_pago_tra)} trabajo(s) sin monto de pago registrado")
    if not df_pen.empty:
        alertas.append(
            f"Cotizaciones pendientes de OC — importe total: "
            f"<strong>${total_pen_oc:,.0f}</strong>"
        )

    meses_es = {
        1:"enero", 2:"febrero", 3:"marzo", 4:"abril",
        5:"mayo", 6:"junio", 7:"julio", 8:"agosto",
        9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre",
    }
    fecha_generacion = f"{hoy.day} de {meses_es[hoy.month]} de {hoy.year}"

    return {
        "meta": {
            "periodo":          periodo.capitalize(),
            "fecha_generacion": fecha_generacion,
            "fecha_hoy_iso":    hoy.strftime("%Y-%m-%d"),
        },
        "kpis": {
            "total_facturado": round(total_facturado, 2),
            "total_cobrado":   round(total_cobrado, 2),
            "por_cobrar":      round(por_cobrar, 2),
            "trabajos":        total_trabajos,
        },
        "chart_facturado": chart_fac,
        "chart_estados":   chart_estados,
        "chart_cobradas":  chart_cob,
        "tabla_facturas":  tabla,
        "tabla_meta": {
            "total_count": len(sin_cobrar),
            "total_monto": round(_safe(sin_cobrar["total"].sum()) if not sin_cobrar.empty else 0, 2),
        },
        "alertas": alertas,
    }


def generar_html(periodo: str = "mensual") -> Path:
    """
    Genera el reporte HTML con datos reales inyectados desde los Excels.
    Guarda el archivo en data/reportes/ y retorna su ruta.
    """
    df_fac, df_pen, df_men, df_tra = _cargar_datos()
    datos = _construir_datos_reporte(df_fac, df_pen, df_men, df_tra, periodo)

    template = _HTML_TEMPLATE.read_text(encoding="utf-8")
    json_str = json.dumps(datos, ensure_ascii=False, indent=2)
    html = template.replace("__CESYM_DATA_JSON__", json_str)

    reportes_dir = Path(__file__).parent.parent / "data" / "reportes"
    reportes_dir.mkdir(parents=True, exist_ok=True)
    nombre = f"reporte_{periodo}_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    html_path = reportes_dir / nombre
    html_path.write_text(html, encoding="utf-8")

    return html_path


# ── Construcción del PDF ──────────────────────────────────────────────────────
def generar_pdf(periodo: str = "mensual") -> Path:
    """
    Genera el PDF del reporte y lo guarda en data/reportes/.
    Retorna la ruta al archivo generado.
    """
    df_fac, df_pen, df_men, df_tra = _cargar_datos()
    estilos = _estilos()

    reportes_dir = Path(__file__).parent.parent / "data" / "reportes"
    reportes_dir.mkdir(parents=True, exist_ok=True)

    fecha_hoy = datetime.now()
    nombre = f"reporte_{periodo}_{fecha_hoy.strftime('%Y%m%d_%H%M')}.pdf"
    pdf_path = reportes_dir / nombre

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"Reporte {periodo.capitalize()} — Cesym",
        author="Cesym Chatbot",
    )

    historia = []
    ancho = doc.width  # ancho útil de la página

    # ── Header ───────────────────────────────────────────────────────────────
    header = Table(
        [[Paragraph(f"Reporte {periodo.capitalize()}", estilos["titulo"])]],
        colWidths=[ancho],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), AZUL),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    historia.append(header)

    sub = Table(
        [[Paragraph(
            f"Generado el {fecha_hoy.strftime('%d de %B de %Y')}  •  Cesym",
            estilos["subtitulo"],
        )]],
        colWidths=[ancho],
    )
    sub.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), AZUL_MED),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    historia.append(sub)
    historia.append(Spacer(1, 0.5 * cm))

    # ── KPIs ─────────────────────────────────────────────────────────────────
    total_facturado    = df_fac["monto_actual"].sum() if not df_fac.empty else 0
    total_cobrado      = df_men[df_men["fecha_pago"].notna()]["total"].sum() if not df_men.empty else 0
    total_por_cobrar   = df_men[df_men["fecha_pago"].isna()]["total"].sum() if not df_men.empty else 0
    total_trabajos     = len(df_tra)
    total_pendiente_oc = df_pen["importe"].sum() if not df_pen.empty else 0

    kpi_w = ancho / 4 - 0.3 * cm
    kpis = Table(
        [[
            _kpi_tabla(_pesos(total_facturado), "Total Facturado\n(OC activas)", AZUL_MED, AZUL, kpi_w),
            _kpi_tabla(_pesos(total_cobrado), "Total Cobrado\n(reporte mensual)", VERDE, VERDE, kpi_w),
            _kpi_tabla(_pesos(total_por_cobrar), "Por Cobrar\n(sin fecha pago)", NARANJA, NARANJA, kpi_w),
            _kpi_tabla(str(total_trabajos), "Trabajos\nRegistrados", AZUL_MED, AZUL, kpi_w),
        ]],
        colWidths=[kpi_w + 0.3 * cm] * 4,
    )
    kpis.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))

    historia.append(Paragraph("Resumen Ejecutivo", estilos["seccion"]))
    historia.append(kpis)
    historia.append(Spacer(1, 0.4 * cm))

    # ── Sección: Cartera ─────────────────────────────────────────────────────
    historia.append(HRFlowable(width="100%", thickness=1.5, color=AZUL, spaceAfter=6))
    historia.append(Paragraph("Cartera de Facturas", estilos["seccion"]))

    if not df_fac.empty:
        img_barras = _grafica_facturado_por_mes(df_fac, ancho * 0.60, ancho * 0.28)
        img_pie    = _grafica_estados_pie(df_fac, ancho * 0.38, ancho * 0.30)
        fila_graficas = Table(
            [[img_barras, img_pie]],
            colWidths=[ancho * 0.62, ancho * 0.38],
        )
        fila_graficas.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        historia.append(fila_graficas)
        historia.append(Spacer(1, 0.3 * cm))

    if not df_men.empty:
        img_stacked = _grafica_cobradas_vs_pendientes(df_men, ancho, ancho * 0.32)
        historia.append(img_stacked)
        historia.append(Spacer(1, 0.3 * cm))

    # Tabla: facturas más antiguas sin cobrar
    sin_cobrar = df_men[df_men["fecha_pago"].isna()].copy() if not df_men.empty else pd.DataFrame()
    if not sin_cobrar.empty:
        historia.append(Paragraph(
            f"Facturas más antiguas sin cobrar ({len(sin_cobrar)} total — {_pesos(sin_cobrar['total'].sum())})",
            estilos["seccion"],
        ))
        filas = [["Folio", "Cliente", "Monto", "Fecha emisión"]]
        for _, row in sin_cobrar.sort_values("fecha").head(8).iterrows():
            fecha_str = row["fecha"].strftime("%d/%m/%Y") if pd.notna(row["fecha"]) else "—"
            filas.append([
                str(row["folio"]),
                str(row["cliente"])[:36],
                _pesos(row["total"]),
                fecha_str,
            ])
        t = Table(filas, colWidths=[ancho * x for x in [0.10, 0.50, 0.20, 0.20]])
        t.setStyle(_estilo_tabla())
        historia.append(t)
        historia.append(Spacer(1, 0.3 * cm))

    # Cotizaciones pendientes de OC
    if not df_pen.empty:
        historia.append(Paragraph(
            f"Cotizaciones pendientes de OC  ({len(df_pen)} — {_pesos(total_pendiente_oc)})",
            estilos["seccion"],
        ))
        filas_pen = [["Cotización", "Sucursal", "Importe", "Concepto"]]
        for _, row in df_pen.sort_values("importe", ascending=False).head(8).iterrows():
            filas_pen.append([
                str(row["cot"]),
                str(row["suc"]) if pd.notna(row["suc"]) else "—",
                _pesos(row["importe"]),
                str(row["concepto"])[:46],
            ])
        t = Table(filas_pen, colWidths=[ancho * x for x in [0.14, 0.11, 0.18, 0.57]])
        t.setStyle(_estilo_tabla())
        historia.append(t)

    # ── Sección: Trabajos ────────────────────────────────────────────────────
    historia.append(PageBreak())
    historia.append(HRFlowable(width="100%", thickness=1.5, color=AZUL, spaceAfter=6))
    historia.append(Paragraph("Control de Trabajos", estilos["seccion"]))

    if not df_tra.empty:
        img_trabajos = _grafica_trabajos_por_mes(df_tra, ancho, ancho * 0.33)
        historia.append(img_trabajos)
        historia.append(Spacer(1, 0.3 * cm))

        df_tec = df_tra[df_tra["tecnico"].notna() & ~df_tra["tecnico"].isin(["", "nan"])]
        if not df_tec.empty:
            n_tec = df_tec["tecnico"].nunique()
            alto_tec = min(8 * cm, max(3 * cm, n_tec * 1.5 * cm + 1 * cm))
            img_tec = _grafica_tecnicos(df_tra, ancho * 0.65, alto_tec)
            historia.append(img_tec)
            historia.append(Spacer(1, 0.3 * cm))

        historia.append(Paragraph("Últimos trabajos registrados", estilos["seccion"]))
        filas_tra = [["Mes", "Técnico", "Cliente", "Trabajo", "Pagado"]]
        for _, row in df_tra.tail(10).iterrows():
            filas_tra.append([
                str(row["mes"])[:9],
                str(row["tecnico"])[:14],
                str(row["cliente"])[:20],
                str(row["tipo_trabajo"])[:30],
                _pesos(row["pagado"]) if pd.notna(row["pagado"]) else "—",
            ])
        t = Table(filas_tra, colWidths=[ancho * x for x in [0.10, 0.16, 0.22, 0.36, 0.16]])
        t.setStyle(_estilo_tabla())
        historia.append(t)

    # ── Sección: Alertas ─────────────────────────────────────────────────────
    historia.append(Spacer(1, 0.5 * cm))
    historia.append(HRFlowable(width="100%", thickness=1.5, color=ROJO, spaceAfter=6))
    historia.append(Paragraph("Alertas y Observaciones", estilos["seccion"]))

    alertas = []

    if not df_fac.empty:
        sin_oc = df_fac[df_fac["oc"].isin(["nan", "", "NaN"])]
        if not sin_oc.empty:
            alertas.append(f"• {len(sin_oc)} factura(s) sin OC asignada: {sin_oc['factura'].tolist()}")

    if not sin_cobrar.empty and "fecha" in sin_cobrar.columns:
        hace_60 = pd.Timestamp.now() - pd.Timedelta(days=60)
        muy_antiguas = sin_cobrar[sin_cobrar["fecha"].notna() & (sin_cobrar["fecha"] < hace_60)]
        if not muy_antiguas.empty:
            alertas.append(
                f"• {len(muy_antiguas)} factura(s) sin cobrar con más de 60 días de antigüedad "
                f"({_pesos(muy_antiguas['total'].sum())})"
            )

    if not df_tra.empty:
        sin_pago = df_tra[df_tra["pagado"].isna()]
        if not sin_pago.empty:
            alertas.append(f"• {len(sin_pago)} trabajo(s) sin monto de pago registrado")

    if not df_pen.empty:
        alertas.append(
            f"• {len(df_pen)} cotización(es) pendientes de OC — "
            f"importe total: {_pesos(total_pendiente_oc)}"
        )

    if alertas:
        filas_al = [[Paragraph(a, estilos["alerta"])] for a in alertas]
        t = Table(filas_al, colWidths=[ancho])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), ROJO_CLARO),
            ("BOX",           (0, 0), (-1, -1), 1, ROJO),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ]))
        historia.append(t)
    else:
        historia.append(Paragraph("Sin alertas en este período.", estilos["body"]))

    historia.append(Spacer(1, 0.5 * cm))
    historia.append(Paragraph(
        f"Generado automáticamente por Cesym Chatbot — {fecha_hoy.strftime('%d/%m/%Y %H:%M')}",
        estilos["nota"],
    ))

    doc.build(historia)
    return pdf_path


# ── Envío por email ───────────────────────────────────────────────────────────
def enviar_reporte_email(pdf_path: Path, destinatarios: list[str], periodo: str = "mensual") -> None:
    """
    Envía el PDF generado por correo usando Gmail SMTP.
    Requiere: GMAIL_USER y GMAIL_APP_PASSWORD en el entorno.
    """
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_pass:
        raise ValueError(
            "Faltan variables de entorno: GMAIL_USER y/o GMAIL_APP_PASSWORD. "
            "Generá una contraseña de aplicación en myaccount.google.com/apppasswords."
        )

    fecha = datetime.now().strftime("%d/%m/%Y")
    asunto = f"Reporte {periodo.capitalize()} Cesym — {fecha}"
    cuerpo = (
        f"Hola,\n\n"
        f"Adjunto encontrarás el reporte {periodo} de Cesym con las métricas "
        f"de cartera y trabajos al {fecha}.\n\n"
        f"Generado automáticamente por Cesym Chatbot."
    )

    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = ", ".join(destinatarios)
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with open(pdf_path, "rb") as f:
        adjunto = MIMEBase("application", "octet-stream")
        adjunto.set_payload(f.read())
    encoders.encode_base64(adjunto)
    adjunto.add_header("Content-Disposition", f'attachment; filename="{pdf_path.name}"')
    msg.attach(adjunto)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, destinatarios, msg.as_string())


# ── Punto de entrada ──────────────────────────────────────────────────────────
def enviar_reporte_html_email(html_path: Path, destinatarios: list[str], periodo: str = "mensual") -> None:
    """
    Envía el HTML generado por correo como adjunto.
    Requiere: GMAIL_USER y GMAIL_APP_PASSWORD en el entorno.
    """
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_pass:
        raise ValueError(
            "Faltan variables de entorno: GMAIL_USER y/o GMAIL_APP_PASSWORD. "
            "Generá una contraseña de aplicación en myaccount.google.com/apppasswords."
        )

    fecha = datetime.now().strftime("%d/%m/%Y")
    asunto = f"Reporte {periodo.capitalize()} Cesym — {fecha}"
    cuerpo = (
        f"Hola,\n\n"
        f"Adjunto encontrarás el reporte {periodo} de Cesym con las métricas "
        f"de cartera y trabajos al {fecha}.\n\n"
        f"Abrí el archivo .html en cualquier navegador para ver el reporte interactivo "
        f"con gráficas y tablas.\n\n"
        f"Generado automáticamente por Cesym Chatbot."
    )

    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = ", ".join(destinatarios)
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with open(html_path, "rb") as f:
        adjunto = MIMEBase("application", "octet-stream")
        adjunto.set_payload(f.read())
    encoders.encode_base64(adjunto)
    adjunto.add_header("Content-Disposition", f'attachment; filename="{html_path.name}"')
    msg.attach(adjunto)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, destinatarios, msg.as_string())


def generar_y_enviar_reporte(periodo: str = "mensual") -> str:
    """
    Genera el reporte HTML con datos reales y lo envía por email.
    Retorna mensaje de estado (para WhatsApp o consola).
    """
    env_dest = os.getenv("REPORT_RECIPIENTS", "")
    destinatarios = [d.strip() for d in env_dest.split(",") if d.strip()]

    if not destinatarios:
        return (
            "No hay destinatarios configurados.\n"
            "Agrega REPORT_RECIPIENTS al entorno "
            "(ej: REPORT_RECIPIENTS=email1@gmail.com,email2@gmail.com)."
        )

    try:
        html_path = generar_html(periodo)
        enviar_reporte_html_email(html_path, destinatarios, periodo)
        return (
            f"Reporte {periodo} generado y enviado a:\n"
            + "\n".join(f"  • {d}" for d in destinatarios)
        )
    except Exception as e:
        return f"Error al generar o enviar el reporte: {e}"
