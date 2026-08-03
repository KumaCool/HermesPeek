from fastapi.testclient import TestClient

from hermes_peek.app import app

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "hermes-peek"}


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "HermesPeek" in response.text


def test_legacy_absolute_path_preview_route_is_not_exposed() -> None:
    response = client.get("/preview", params={"path": "/tmp/example.md"})
    assert response.status_code == 404
