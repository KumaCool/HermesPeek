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


def test_preview_allowed_file(tmp_path, monkeypatch) -> None:
    document = tmp_path / "hello.md"
    document.write_text("# Hello <Peek>", encoding="utf-8")
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(tmp_path))

    response = client.get("/preview", params={"path": str(document)})

    assert response.status_code == 200
    assert "# Hello &lt;Peek&gt;" in response.text


def test_preview_rejects_outside_root(tmp_path, monkeypatch) -> None:
    document = tmp_path / "hello.md"
    document.write_text("hello", encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(allowed))

    response = client.get("/preview", params={"path": str(document)})

    assert response.status_code == 403


def test_preview_rejects_sensitive_file(tmp_path, monkeypatch) -> None:
    document = tmp_path / ".env"
    document.write_text("TOKEN=secret", encoding="utf-8")
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(tmp_path))

    response = client.get("/preview", params={"path": str(document)})

    assert response.status_code == 403
