"""
seed_clientes_cesym.py
----------------------
Seed idempotente del catálogo cesym_db.clientes con los clientes principales.
Para agregar más, añade una tupla a CLIENTES_SEED. Correrlo de nuevo no duplica.

Uso (en el servidor, vía SSH):
    CESYM_DB_URL="postgresql://cesym_app:***@localhost:5432/cesym_db" \
        python scripts/seed_clientes_cesym.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cesym_db import get_cesym_engine
from src.cotizaciones_pg import crear_cliente

# (rfc, nombre_fiscal, nombre_comercial). Todos tipo 'empresa'.
# Razones sociales de la auditoría; se afinan al migrar los CFDI (nombre del SAT).
CLIENTES_SEED = [
    ("WDM990126350", "WALDO'S DOLAR MART DE MEXICO", "WALDOS"),
    ("DME860313ND7", "DURA DE MEXICO, S.A. DE C.V.",  "DURA"),
    ("OOM090327365", "OHD OPERATORS DE MEXICO",       "GENIE"),
]


def sembrar(engine=None) -> int:
    """Upsert idempotente de CLIENTES_SEED. Devuelve cuántos se procesaron."""
    eng = engine or get_cesym_engine()
    with eng.begin() as conn:
        for rfc, nombre_fiscal, nombre_comercial in CLIENTES_SEED:
            crear_cliente(conn, rfc, nombre_fiscal, nombre_comercial, "empresa")
    return len(CLIENTES_SEED)


if __name__ == "__main__":
    n = sembrar()
    print(f"[seed] {n} clientes sembrados/actualizados en cesym_db.clientes.")
