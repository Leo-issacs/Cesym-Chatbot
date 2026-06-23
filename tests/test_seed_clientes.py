"""El seed de clientes es idempotente: correrlo dos veces deja 3 clientes."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import scripts.seed_clientes_cesym as seed


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE clientes (rfc TEXT PRIMARY KEY, nombre_fiscal TEXT NOT NULL,"
            " nombre_comercial TEXT, tipo TEXT)"))
    return eng


def test_seed_idempotente(engine):
    seed.sembrar(engine)
    n2 = seed.sembrar(engine)            # segunda corrida
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM clientes")).scalar()
        tipos = conn.execute(text("SELECT DISTINCT tipo FROM clientes")).scalars().all()
    assert total == 3 and n2 == 3 and tipos == ["empresa"]


def test_seed_incluye_waldos(engine):
    seed.sembrar(engine)
    with engine.connect() as conn:
        nf = conn.execute(text("SELECT nombre_fiscal FROM clientes WHERE rfc='WDM990126350'")).scalar()
    assert "WALDO" in nf
