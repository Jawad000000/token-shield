from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_embed_endpoint() -> None:
    client = TestClient(app)
    response = client.post("/embed", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json()["dimension"] == 384
