from fastapi.testclient import TestClient

import src.webhook as webhook


def test_health_no_expone_datos_internos():
    respuesta = TestClient(webhook.app).get("/")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}
