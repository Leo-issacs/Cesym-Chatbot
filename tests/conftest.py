"""
conftest.py
-----------
Fixtures compartidas para todos los tests de pytest.
Se ejecutan una sola vez por sesión (scope="session") para no releer el Excel
en cada test.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.loader import load_facturado, load_pendiente
from src.cleaner import clean_facturado, clean_pendiente


@pytest.fixture(scope="session")
def raw_facturado():
    return load_facturado()


@pytest.fixture(scope="session")
def raw_pendiente():
    return load_pendiente()


@pytest.fixture(scope="session")
def facturado():
    df, _ = clean_facturado(load_facturado())
    return df


@pytest.fixture(scope="session")
def pendiente():
    df, _ = clean_pendiente(load_pendiente())
    return df


@pytest.fixture(scope="session")
def advertencias_facturado():
    _, warns = clean_facturado(load_facturado())
    return warns


@pytest.fixture(scope="session")
def advertencias_pendiente():
    _, warns = clean_pendiente(load_pendiente())
    return warns
