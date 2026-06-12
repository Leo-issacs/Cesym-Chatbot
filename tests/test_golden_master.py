"""
test_golden_master.py
----------------------
Golden master de query_engine.run_query: ejecuta una batería de comandos
representativos sobre los DataFrames SINTÉTICOS y compara la salida EXACTA
(carácter por carácter) contra snapshots guardados en tests/snapshots/.

PROPÓSITO
  Esta es la red de seguridad del switch a Postgres (PR-12/14): demuestra que el
  bot responde EXACTAMENTE lo mismo lea de Excel o de Postgres. La precisión
  textual exacta importa — cualquier diferencia (un espacio, un decimal) falla.

REGENERAR SNAPSHOTS (a propósito)
  Si un cambio de comportamiento es INTENCIONAL, regenera los snapshots con:

      UPDATE_SNAPSHOTS=1 pytest tests/test_golden_master.py     (bash)
      $env:UPDATE_SNAPSHOTS=1; pytest tests/test_golden_master.py   (PowerShell)

  ⚠ Regenerar = ACEPTAR la nueva salida como la correcta. Revisa el `git diff`
  de tests/snapshots/ ANTES de commitear: ahí se ve, línea por línea, qué cambió
  en lo que el bot le responde al usuario.
"""

import os
import warnings
from pathlib import Path

import pytest

SNAP_DIR = Path(__file__).parent / "snapshots"

# (slug de archivo, comando) — ~15 comandos representativos del bot.
COMANDOS = [
    ("total",                  "total"),
    ("resumen",                "resumen"),
    ("facturas",               "facturas"),
    ("pendientes_suc2",        "pendientes 2"),
    ("buscar_factura_8001",    "buscar factura 8001"),
    ("buscar_cliente_toyoda",  "buscar cliente TOYODA"),
    ("cobradas",               "cobradas"),
    ("sin_cobrar",             "sin cobrar"),
    ("cruce",                  "cruce"),
    ("trabajos",               "trabajos"),
    ("estado_prioridad",       "estado prioridad"),
    ("errores",                "errores"),
    ("ayuda",                  "ayuda"),
    ("comando_invalido",       "comando_que_no_existe"),
    ("buscar_cliente_typo",    "buscar cliente TOYODAA"),
]

_ACTUALIZAR = os.getenv("UPDATE_SNAPSHOTS") == "1"


def _comparar(slug: str, actual: str) -> None:
    ruta = SNAP_DIR / f"{slug}.txt"

    if _ACTUALIZAR:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        ruta.write_text(actual, encoding="utf-8", newline="\n")
        warnings.warn(
            f"[UPDATE_SNAPSHOTS] Regenerado {ruta.name}. Regenerar = ACEPTAR la "
            f"nueva salida como correcta: revisa el git diff antes de commitear."
        )
        return

    assert ruta.exists(), (
        f"No existe el snapshot '{ruta.name}'. Genéralo con UPDATE_SNAPSHOTS=1 y "
        f"revísalo antes de commitear."
    )
    esperado = ruta.read_text(encoding="utf-8")
    assert actual == esperado, (
        f"La salida de '{slug}' cambió respecto al golden master.\n"
        f"Si el cambio es INTENCIONAL, regenera con UPDATE_SNAPSHOTS=1 y revisa el diff.\n"
        f"────── esperado ──────\n{esperado}\n"
        f"────── actual ──────\n{actual}"
    )


@pytest.mark.parametrize("slug,comando", COMANDOS, ids=[c[0] for c in COMANDOS])
def test_golden_master(slug, comando, rq):
    _comparar(slug, rq(comando))
