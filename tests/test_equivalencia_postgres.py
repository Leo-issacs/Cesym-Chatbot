"""
test_equivalencia_postgres.py
-----------------------------
Golden master de EQUIVALENCIA Excel ↔ Postgres (PR-12).

Demuestra que `run_query` responde EXACTAMENTE lo mismo lea los datos por la ruta
Excel (loader→cleaner) o por la ruta Postgres (datos_postgres), usando UN dataset
a medida representable en ambas (tests/fixtures/equivalencia.py).

Se compara contra snapshots en tests/snapshots/equivalencia/:
  - test_excel_*  : ruta cleaner == snapshot. Corre SIEMPRE (local y CI), sin BD.
  - test_postgres_*: ruta Postgres == snapshot. Corre solo si TEST_DATABASE_URL
    está definida (el servicio postgres efímero de CI). Se salta en local sin BD.

Como ambas mitades comparan contra el MISMO .txt, que ambas pasen prueba que las
dos rutas son idénticas.

REGENERAR (a propósito): UPDATE_SNAPSHOTS=1 (ver advertencia abajo). Regenerar =
aceptar la nueva salida como correcta; revisa el git diff antes de commitear.

⚠ TEST_DATABASE_URL debe apuntar a una BD DESECHABLE: el setup hace DROP SCHEMA
chatbot CASCADE. Nunca apuntes esto a producción.
"""

import os
import warnings
from pathlib import Path

import pytest

from src.query_engine import run_query
from tests.fixtures import equivalencia as eq

SNAP_DIR = Path(__file__).parent / "snapshots" / "equivalencia"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
_ACTUALIZAR = os.getenv("UPDATE_SNAPSHOTS") == "1"


def _comparar(slug: str, actual: str) -> None:
    ruta = SNAP_DIR / f"{slug}.txt"
    if _ACTUALIZAR:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        ruta.write_text(actual, encoding="utf-8", newline="\n")
        warnings.warn(
            f"[UPDATE_SNAPSHOTS] Regenerado equivalencia/{ruta.name}. Regenerar = "
            f"ACEPTAR la nueva salida como correcta: revisa el git diff."
        )
        return
    assert ruta.exists(), (
        f"No existe el snapshot equivalencia/{ruta.name}. Genéralo con "
        f"UPDATE_SNAPSHOTS=1 y revísalo antes de commitear."
    )
    esperado = ruta.read_text(encoding="utf-8")
    assert actual == esperado, (
        f"La salida de '{slug}' difiere del golden master de equivalencia.\n"
        f"Si el cambio es INTENCIONAL, regenera con UPDATE_SNAPSHOTS=1.\n"
        f"────── esperado ──────\n{esperado}\n"
        f"────── actual ──────\n{actual}"
    )


# ─── Mitad Excel (ruta cleaner): corre siempre, sin BD ───────────────────────
@pytest.fixture(scope="session")
def dfs_cleaner():
    return eq.cargar_dfs_via_cleaner()


@pytest.mark.parametrize("slug,comando", eq.COMANDOS, ids=[c[0] for c in eq.COMANDOS])
def test_excel_coincide_con_snapshot(slug, comando, dfs_cleaner):
    _comparar(slug, run_query(comando, *dfs_cleaner))


# ─── Mitad Postgres (ruta datos_postgres): solo si hay TEST_DATABASE_URL ─────
@pytest.fixture(scope="session")
def dfs_postgres():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL no definida — la mitad Postgres corre en CI")
    from src.db_postgres import get_engine
    from src.datos_postgres import cargar_datos_desde_postgres

    engine = get_engine(TEST_DATABASE_URL)
    eq.poblar_postgres(engine)
    facturado, pendiente, mensual, trabajos, _ = cargar_datos_desde_postgres(engine)
    return facturado, pendiente, mensual, trabajos


@pytest.mark.parametrize("slug,comando", eq.COMANDOS, ids=[c[0] for c in eq.COMANDOS])
def test_postgres_coincide_con_snapshot(slug, comando, dfs_postgres):
    _comparar(slug, run_query(comando, *dfs_postgres))
