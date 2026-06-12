"""
test_reportes_auth.py
---------------------
Pruebas de seguridad del fix P0.4:

  1. GET /reportes/{filename} sanitiza el nombre y rechaza path traversal
     (../, %2F, rutas absolutas) y cualquier cosa que no sea un .html dentro de
     data/reportes/. Los nombres sin token (adivinables) no existen → 404.
  2. El comando 'logs' exige número autorizado aunque ENFORCE_WHITELIST esté
     apagado; con whitelist vacía, niega.

Herméticas: el endpoint se prueba llamando la corrutina con asyncio.run y
apuntando _REPORTES_DIR a un tmp_path. No levantan el servidor ni usan red.
"""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

import src.webhook as webhook


# ─── GET /reportes/{filename} ────────────────────────────────────────────────

@pytest.fixture
def reportes_dir(tmp_path, monkeypatch):
    """Apunta el endpoint a un directorio de reportes temporal y aislado."""
    monkeypatch.setattr(webhook, "_REPORTES_DIR", tmp_path)
    return tmp_path


def _servir(filename):
    return asyncio.run(webhook.servir_reporte(filename))


def test_sirve_html_con_token(reportes_dir):
    """Un reporte real (con token) dentro de la carpeta se sirve con 200."""
    nombre = "reporte_mensual_20260101_1200_AbCdEf123456.html"
    (reportes_dir / nombre).write_text("<html>ok</html>", encoding="utf-8")

    resp = _servir(nombre)

    assert isinstance(resp, FileResponse)
    assert resp.status_code == 200


def test_rechaza_traversal_dotdot(reportes_dir):
    """'../secret.html' no debe escapar de data/reportes/."""
    # Archivo sensible fuera de la carpeta de reportes.
    (reportes_dir.parent / "secret.html").write_text("secreto", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _servir("../secret.html")
    assert exc.value.status_code == 404


def test_rechaza_traversal_encoded_slash(reportes_dir):
    """Separadores codificados (%2F) no deben interpretarse como ruta."""
    (reportes_dir.parent / "secret.html").write_text("secreto", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _servir("..%2F..%2Fsecret.html")
    assert exc.value.status_code == 404


def test_rechaza_ruta_absoluta(reportes_dir, tmp_path):
    """Una ruta absoluta debe reducirse a su .name y no encontrarse → 404."""
    afuera = tmp_path.parent / "otro.html"
    afuera.write_text("x", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _servir(str(afuera))
    assert exc.value.status_code == 404


def test_rechaza_nombre_sin_token(reportes_dir):
    """Un nombre adivinable sin token no existe en la carpeta → 404."""
    with pytest.raises(HTTPException) as exc:
        _servir("reporte_mensual_20260101_1200.html")
    assert exc.value.status_code == 404


def test_rechaza_no_html(reportes_dir):
    """Aunque el archivo exista, si no es .html se rechaza."""
    (reportes_dir / "datos.txt").write_text("x", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _servir("datos.txt")
    assert exc.value.status_code == 404


# ─── comando 'logs' ──────────────────────────────────────────────────────────

def test_logs_niega_si_whitelist_vacia(monkeypatch):
    """Sin NUMEROS_AUTORIZADOS, 'logs' se niega a todos (aunque no haya enforce)."""
    monkeypatch.delenv("NUMEROS_AUTORIZADOS", raising=False)
    assert webhook._puede_ver_logs("whatsapp:+5210000000000") is False


def test_logs_niega_numero_no_autorizado(monkeypatch):
    """Un número fuera de la whitelist no puede ver los logs."""
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5210000000000")
    assert webhook._puede_ver_logs("whatsapp:+5219999999999") is False


def test_logs_permite_numero_autorizado(monkeypatch):
    """Un número en la whitelist sí puede ver los logs (sin depender del enforce)."""
    monkeypatch.delenv("ENFORCE_WHITELIST", raising=False)  # apagado a propósito
    monkeypatch.setenv("NUMEROS_AUTORIZADOS", "whatsapp:+5210000000000")
    assert webhook._puede_ver_logs("whatsapp:+5210000000000") is True
