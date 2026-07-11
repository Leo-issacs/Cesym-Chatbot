"""
test_pendiente_cesym.py
-----------------------
Flag USE_CESYM_DB_PENDIENTE (default APAGADO): `pendiente` desde la vista
`cesym_db.chatbot_pendiente_v1`, con fallback al schema chatbot si falla.

Herméticos: sin BD. Se simulan los engines (objetos con .connect() de
contexto) y se intercepta pd.read_sql dentro del módulo para despachar
DataFrames sintéticos según el SQL que llega.
"""
from contextlib import contextmanager

import pandas as pd
import pytest

import src.datos_postgres as dp


# ─── Dobles de prueba ────────────────────────────────────────────────────────


class _EngineFalso:
    """Engine mínimo: .connect() como context manager que entrega un conn
    etiquetado, para que el read_sql falso sepa de qué 'base' viene."""

    def __init__(self, etiqueta):
        self.etiqueta = etiqueta

    @contextmanager
    def connect(self):
        yield self  # el propio engine hace de conn; solo importa la etiqueta


_FACTURADO = pd.DataFrame(
    {"factura": [8001], "oc": ["O01-1"], "monto_actual": [100.0],
     "prioridad": [""], "fecha": [None], "estado": [""]}
)
_PENDIENTE_BOT = pd.DataFrame(
    {"cot": [10, 11], "suc": [5208, 6674], "importe": [100.0, 200.0],
     "concepto": ["PUERTAS", ""]}
)
_MENSUAL = pd.DataFrame(
    {"folio": [8001], "cliente": ["WALDOS"], "fecha": [None],
     "concepto": ["x"], "total": [100.0], "fecha_pago": [None]}
)
_TRABAJOS = pd.DataFrame(
    {"id": [1], "mes": ["JUNIO"], "tecnico": ["LEO"], "cliente": ["X"],
     "rep_num": [""], "domicilio": [""], "telefono": [""],
     "tipo_trabajo": ["chico"], "pagado": [0.0], "recibe": [""]}
)
# La vista trae una fila extra (baseline cot=1 sin sucursal) además de las del bot.
_PENDIENTE_VISTA = pd.DataFrame(
    {"cot": [1, 10, 11], "suc": [None, 5208, 6674],
     "importe": [1500.0, 100.0, 200.0], "concepto": [None, "PUERTAS", ""]}
)


def _read_sql_falso(vista_falla=False):
    def _fake(sql, conn):
        s = str(sql)
        if "chatbot_pendiente_v1" in s:
            assert conn.etiqueta == "cesym", "la vista debe leerse del engine de cesym_db"
            if vista_falla:
                raise RuntimeError("vista no disponible (simulado)")
            return _PENDIENTE_VISTA.copy()
        assert conn.etiqueta == "chatbot", "las tablas del bot deben leerse de chatbot_db"
        if "OC_EMITIDA" in s:
            return _FACTURADO.copy()
        if "COT_PENDIENTE" in s:
            return _PENDIENTE_BOT.copy()
        if "facturas" in s:
            return _MENSUAL.copy()
        return _TRABAJOS.copy()
    return _fake


def _cargar(monkeypatch, flag=None, vista_falla=False, cesym_engine="auto"):
    if flag is None:
        monkeypatch.delenv("USE_CESYM_DB_PENDIENTE", raising=False)
    else:
        monkeypatch.setenv("USE_CESYM_DB_PENDIENTE", flag)
    monkeypatch.setattr(dp.pd, "read_sql", _read_sql_falso(vista_falla))
    kwargs = {"engine": _EngineFalso("chatbot")}
    if cesym_engine == "auto":
        kwargs["cesym_engine"] = _EngineFalso("cesym")
    return dp.cargar_datos_desde_postgres(**kwargs)


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_flag_apagado_por_default_usa_chatbot(monkeypatch):
    """Sin la variable, `pendiente` sale del schema chatbot y cesym_db NI SE TOCA."""
    def _no_llamar():
        raise AssertionError("get_cesym_engine no debe llamarse con el flag apagado")
    import src.cesym_db as cdb
    monkeypatch.setattr(cdb, "get_cesym_engine", _no_llamar)

    _, pendiente, _, _, adv = _cargar(monkeypatch, flag=None, cesym_engine=None)
    pd.testing.assert_frame_equal(pendiente, _PENDIENTE_BOT)
    assert not any("cesym" in a for a in adv)


def test_flag_cero_explicito_usa_chatbot(monkeypatch):
    _, pendiente, _, _, _ = _cargar(monkeypatch, flag="0", cesym_engine=None)
    pd.testing.assert_frame_equal(pendiente, _PENDIENTE_BOT)


def test_flag_encendido_lee_la_vista(monkeypatch):
    _, pendiente, _, _, adv = _cargar(monkeypatch, flag="1")
    assert list(pendiente.columns) == ["cot", "suc", "importe", "concepto"]
    assert len(pendiente) == 3  # incluye la baseline extra de cesym_db
    assert 1 in pendiente["cot"].tolist()
    # concepto NULL de la vista debe llegar como '' (contrato del query engine)
    assert (pendiente["concepto"] == "").sum() == 2
    assert not any("fallback" in a for a in adv)


def test_flag_encendido_normaliza_tipos(monkeypatch):
    _, pendiente, _, _, _ = _cargar(monkeypatch, flag="1")
    # suc trae un NULL (baseline) -> Int64 nullable, nunca float64 con .0
    assert str(pendiente["suc"].dtype) == "Int64"
    # cot no trae nulos -> int64 igual que la ruta chatbot
    assert str(pendiente["cot"].dtype) == "int64"
    assert pendiente["importe"].dtype == "float64"


def test_fallo_de_vista_cae_a_chatbot(monkeypatch, caplog):
    with caplog.at_level("ERROR"):
        _, pendiente, _, _, adv = _cargar(monkeypatch, flag="1", vista_falla=True)
    pd.testing.assert_frame_equal(pendiente, _PENDIENTE_BOT)
    assert any("chatbot_pendiente_v1" in r.message for r in caplog.records)
    assert any("fallback" in a for a in adv)


def test_flag_no_afecta_los_otros_dataframes(monkeypatch):
    fact_off, _, mens_off, trab_off, _ = _cargar(monkeypatch, flag="0", cesym_engine=None)
    fact_on, _, mens_on, trab_on, _ = _cargar(monkeypatch, flag="1")
    pd.testing.assert_frame_equal(fact_off, fact_on)
    pd.testing.assert_frame_equal(mens_off, mens_on)
    pd.testing.assert_frame_equal(trab_off, trab_on)
